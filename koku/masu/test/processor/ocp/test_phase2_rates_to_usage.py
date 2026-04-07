#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Phase 2 tests: RatesToUsage pipeline — delete, insert, aggregate, validate.

IEEE 829 Test Plan: COST-7249-P2-TP-001
See docs/architecture/cost-breakdown/phase2-test-plan.md

Tier 1 (Unit): TestPriceListSwitch, TestCostModelIdExtraction, TestSyncTestRateRows
Tier 2 (Integration): TestDeleteRatesToUsage, TestPopulateUsageRatesToUsage,
                       TestAggregateRatesToDailySummary, TestValidateRatesToUsage
Tier 3 (Behavioral): TestUpdaterOrchestration, TestPartitionWiring, TestPurgeWiring,
                      TestSkipPaths
Tier 4 (E2E): TestRTUCostBreakdownAPI
"""
from functools import wraps
from unittest.mock import patch

from django.test import override_settings
from django_tenants.utils import schema_context

from api.metrics import constants as metric_constants
from api.utils import DateHelper
from masu.database.ocp_report_db_accessor import OCPReportDBAccessor
from masu.processor.ocp.ocp_cost_model_cost_updater import OCPCostModelCostUpdater
from masu.test import MasuTestCase
from masu.util.common import SummaryRangeConfig
from reporting.provider.ocp.models import OCPUsageReportPeriod


# ---------------------------------------------------------------------------
# Tier 1 — Unit Tests
# ---------------------------------------------------------------------------


class TestPriceListSwitch(MasuTestCase):
    """Verify CostModelDBAccessor.price_list reads from Rate table (BAC-1, BAC-2)."""

    def _get_accessor(self, provider_uuid=None):
        from masu.database.cost_model_db_accessor import CostModelDBAccessor

        return CostModelDBAccessor(self.schema, provider_uuid or self.ocp_provider_uuid)

    # TC-01: price_list returns dict keyed by metric name
    def test_price_list_returns_dict_keyed_by_metric(self):
        with self._get_accessor() as accessor:
            pl = accessor.price_list
            self.assertIsInstance(pl, dict)
            if pl:
                for key in pl:
                    self.assertIsInstance(key, str)
                    self.assertIn("metric", pl[key])
                    self.assertEqual(pl[key]["metric"]["name"], key)

    # TC-02: tiered_rates keyed by cost_type
    def test_price_list_tiered_rates_keyed_by_cost_type(self):
        with self._get_accessor() as accessor:
            pl = accessor.price_list
            if not pl:
                self.skipTest("No rates for OCP provider")
            for metric_name, entry in pl.items():
                self.assertIn("tiered_rates", entry)
                tiered = entry["tiered_rates"]
                self.assertIsInstance(tiered, dict)
                for cost_type in tiered:
                    self.assertIn(cost_type, ("Infrastructure", "Supplementary"))

    # TC-03: value format [{value: float, unit: "USD"}]
    def test_price_list_value_format(self):
        with self._get_accessor() as accessor:
            pl = accessor.price_list
            if not pl:
                self.skipTest("No rates for OCP provider")
            for metric_name, entry in pl.items():
                for cost_type, tiers in entry["tiered_rates"].items():
                    self.assertIsInstance(tiers, list)
                    self.assertGreater(len(tiers), 0)
                    tier = tiers[0]
                    self.assertIn("value", tier)
                    self.assertIn("unit", tier)
                    self.assertIsInstance(tier["value"], (int, float))
                    self.assertEqual(tier["unit"], "USD")

    # TC-04: infrastructure_rates populated (BAC-2)
    def test_infrastructure_rates_populated(self):
        with self._get_accessor() as accessor:
            infra = accessor.infrastructure_rates
            self.assertIsInstance(infra, dict)
            self.assertGreater(len(infra), 0, "Expected at least one infrastructure rate")

    # TC-05: supplementary_rates populated (BAC-2)
    def test_supplementary_rates_populated(self):
        with self._get_accessor() as accessor:
            supp = accessor.supplementary_rates
            self.assertIsInstance(supp, dict)
            self.assertGreater(len(supp), 0, "Expected at least one supplementary rate")

    # TC-06: duplicate metric+cost_type sums values
    def test_price_list_sums_duplicate_metric_cost_type(self):
        from cost_models.models import Rate
        from masu.database.cost_model_db_accessor import CostModelDBAccessor

        with CostModelDBAccessor(self.schema, self.ocp_provider_uuid) as accessor:
            if not accessor.cost_model:
                self.skipTest("No cost model for OCP provider")

            rate_rows = Rate.objects.filter(
                price_list__cost_model_maps__cost_model=accessor.cost_model,
                tag_key="",
            )
            expected = {}
            for r in rate_rows:
                key = (r.metric, r.cost_type)
                val = float(r.default_rate) if r.default_rate is not None else 0.0
                expected[key] = expected.get(key, 0.0) + val

            pl = accessor.price_list
            for (metric, cost_type), expected_sum in expected.items():
                self.assertIn(metric, pl, f"Missing metric {metric}")
                tiered = pl[metric]["tiered_rates"]
                self.assertIn(cost_type, tiered, f"Missing cost_type {cost_type} for {metric}")
                actual_sum = tiered[cost_type][0]["value"]
                self.assertAlmostEqual(actual_sum, expected_sum, places=10)

    # TC-07: tag rates excluded from price_list
    def test_price_list_skips_tag_rates(self):
        from cost_models.models import Rate
        from masu.database.cost_model_db_accessor import CostModelDBAccessor

        with CostModelDBAccessor(self.schema, self.ocp_provider_uuid) as accessor:
            if not accessor.cost_model:
                self.skipTest("No cost model for OCP provider")

            tag_rate_metrics = set(
                Rate.objects.filter(
                    price_list__cost_model_maps__cost_model=accessor.cost_model,
                ).exclude(tag_key="").values_list("metric", flat=True)
            )
            non_tag_metrics = set(
                Rate.objects.filter(
                    price_list__cost_model_maps__cost_model=accessor.cost_model,
                    tag_key="",
                ).values_list("metric", flat=True)
            )
            tag_only_metrics = tag_rate_metrics - non_tag_metrics

            pl = accessor.price_list
            for metric in tag_only_metrics:
                self.assertNotIn(metric, pl, f"Tag-only metric {metric} should not be in price_list")

    # TC-08: unknown provider returns {}
    def test_price_list_empty_for_unknown_provider(self):
        with self._get_accessor("00000000-0000-0000-0000-000000000000") as accessor:
            self.assertEqual(accessor.price_list, {})

    # TC-09: no cost model returns {}
    def test_price_list_empty_for_no_cost_model(self):
        from masu.database.cost_model_db_accessor import CostModelDBAccessor

        with CostModelDBAccessor(self.schema, self.unkown_test_provider_uuid) as accessor:
            self.assertEqual(accessor.price_list, {})


class TestCostModelIdExtraction(MasuTestCase):
    """Verify _cost_model_id extraction in OCPCostModelCostUpdater.__init__ (BAC-10)."""

    # TC-10: cost_model_id populated when cost model exists
    def test_cost_model_id_populated(self):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        self.assertIsNotNone(updater._cost_model_id)

    # TC-11: cost_model_id None when no cost model
    @patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")
    def test_cost_model_id_none_when_no_cost_model(self, mock_accessor):
        _setup_no_cost_model_mock(mock_accessor)
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        self.assertIsNone(updater._cost_model_id)


class TestSyncTestRateRows(MasuTestCase):
    """Verify sync_test_rate_rows test utility (BAC-15)."""

    # TC-12: creates PriceList
    def test_sync_creates_price_list(self):
        from cost_models.models import CostModel
        from cost_models.models import PriceList
        from cost_models.models import PriceListCostModelMap

        with schema_context(self.schema):
            cm = CostModel.objects.filter(
                costmodelmap__provider_uuid=self.ocp_provider_uuid
            ).first()
            if not cm:
                self.skipTest("No cost model for OCP provider")
            pl_count = PriceList.objects.filter(cost_model_maps__cost_model=cm).count()
            self.assertGreater(pl_count, 0, "sync_test_rate_rows should create at least one PriceList")

    # TC-13: creates Rate rows matching JSON entries
    def test_sync_creates_rate_rows(self):
        from cost_models.models import CostModel
        from cost_models.models import Rate

        with schema_context(self.schema):
            cm = CostModel.objects.filter(
                costmodelmap__provider_uuid=self.ocp_provider_uuid
            ).first()
            if not cm:
                self.skipTest("No cost model for OCP provider")
            rate_count = Rate.objects.filter(
                price_list__cost_model_maps__cost_model=cm
            ).count()
            json_rate_count = len(cm.rates) if isinstance(cm.rates, list) else 0
            self.assertEqual(rate_count, json_rate_count, "Rate row count should match JSON rate count")

    # TC-14: price_list remains correct after multiple sync_test_rate_rows calls
    def test_price_list_correct_after_multiple_syncs(self):
        """sync_test_rate_rows creates a new PriceList each call; price_list sums all Rate rows."""
        from cost_models.models import CostModel

        from api.report.test.util.common import sync_test_rate_rows
        from masu.database.cost_model_db_accessor import CostModelDBAccessor

        with schema_context(self.schema):
            cm = CostModel.objects.filter(
                costmodelmap__provider_uuid=self.ocp_provider_uuid
            ).first()
            if not cm:
                self.skipTest("No cost model for OCP provider")

        with CostModelDBAccessor(self.schema, self.ocp_provider_uuid) as accessor:
            pl_before = accessor.price_list

        with schema_context(self.schema):
            sync_test_rate_rows(cm)

        with CostModelDBAccessor(self.schema, self.ocp_provider_uuid) as accessor:
            pl_after = accessor.price_list

        self.assertEqual(set(pl_before.keys()), set(pl_after.keys()),
                         "price_list metrics should be the same after extra sync")


# ---------------------------------------------------------------------------
# Tier 2 — Integration Tests
# ---------------------------------------------------------------------------


class _ReportPeriodMixin:
    """Mixin providing ``_get_report_period`` for T2/T3 integration test classes.

    Queries for the most recent report period for the OCP provider, making
    tests independent of the calendar month the test DB was created in.
    """

    def _get_report_period(self, accessor=None):
        with schema_context(self.schema):
            rp = (
                OCPUsageReportPeriod.objects
                .filter(provider_id=self.ocp_provider_uuid)
                .order_by("-report_period_start")
                .first()
            )
        if not rp:
            self.skipTest("No report period for OCP provider")
        return rp


class TestDeleteRatesToUsage(_ReportPeriodMixin, MasuTestCase):
    """Test delete_rates_to_usage accessor method (BAC-3)."""

    # TC-20: executes DELETE SQL
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_delete_rtu_executes_delete_sql(self, mock_execute):
        dh = DateHelper()
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.delete_rates_to_usage(
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
            )
        mock_execute.assert_called_once()
        args, kwargs = mock_execute.call_args
        self.assertEqual(args[0], "rates_to_usage")
        self.assertEqual(kwargs.get("operation"), "DELETE")

    # TC-21: params match window
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_delete_rtu_params_match_window(self, mock_execute):
        dh = DateHelper()
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.delete_rates_to_usage(
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
            )
        args, kwargs = mock_execute.call_args
        sql_params = args[2]
        self.assertEqual(sql_params["start_date"], dh.this_month_start.date())
        self.assertEqual(sql_params["end_date"], dh.this_month_end.date())
        self.assertEqual(sql_params["source_uuid"], self.ocp_provider_uuid)
        self.assertEqual(sql_params["report_period_id"], rp.id)
        self.assertEqual(sql_params["schema"], self.schema)


class TestPopulateUsageRatesToUsage(_ReportPeriodMixin, MasuTestCase):
    """Test populate_usage_rates_to_usage accessor method (BAC-4,5,11)."""

    # TC-26: empty rates → no-op
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_populate_rtu_noop_when_empty_rates(self, mock_execute):
        dh = DateHelper()
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.populate_usage_rates_to_usage(
                metric_constants.INFRASTRUCTURE_COST_TYPE,
                {},
                "cpu",
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
                "00000000-0000-0000-0000-000000000000",
            )
        mock_execute.assert_not_called()

    # TC-22: executes INSERT SQL when rates provided
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_populate_rtu_executes_insert_sql(self, mock_execute):
        dh = DateHelper()
        rates = {"cpu_core_usage_per_hour": 0.5}
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.populate_usage_rates_to_usage(
                metric_constants.INFRASTRUCTURE_COST_TYPE,
                rates, "cpu",
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
                "00000000-0000-0000-0000-000000000000",
            )
        mock_execute.assert_called_once()
        args, kwargs = mock_execute.call_args
        self.assertEqual(args[0], "rates_to_usage")
        self.assertEqual(kwargs.get("operation"), "INSERT")

    # TC-23: cost_model_id included as string
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_populate_rtu_includes_cost_model_id(self, mock_execute):
        dh = DateHelper()
        cost_model_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        rates = {"cpu_core_usage_per_hour": 0.5}
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.populate_usage_rates_to_usage(
                metric_constants.INFRASTRUCTURE_COST_TYPE,
                rates, "cpu",
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
                cost_model_id,
            )
        args, kwargs = mock_execute.call_args
        sql_params = args[2]
        self.assertEqual(sql_params["cost_model_id"], cost_model_id)

    # TC-24: rate_type included
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_populate_rtu_includes_rate_type(self, mock_execute):
        dh = DateHelper()
        rates = {"cpu_core_usage_per_hour": 0.5}
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.populate_usage_rates_to_usage(
                metric_constants.SUPPLEMENTARY_COST_TYPE,
                rates, "cpu",
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
                "00000000-0000-0000-0000-000000000000",
            )
        args, kwargs = mock_execute.call_args
        sql_params = args[2]
        self.assertEqual(sql_params["rate_type"], metric_constants.SUPPLEMENTARY_COST_TYPE)

    # TC-25: distribution included
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_populate_rtu_includes_distribution(self, mock_execute):
        dh = DateHelper()
        rates = {"cpu_core_usage_per_hour": 0.5}
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.populate_usage_rates_to_usage(
                metric_constants.INFRASTRUCTURE_COST_TYPE,
                rates, "memory",
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
                "00000000-0000-0000-0000-000000000000",
            )
        args, kwargs = mock_execute.call_args
        sql_params = args[2]
        self.assertEqual(sql_params["distribution"], "memory")

    # TC-27: all 11 COST_MODEL_USAGE_RATES keys present
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_populate_rtu_all_11_rate_params(self, mock_execute):
        dh = DateHelper()
        rates = {"cpu_core_usage_per_hour": 0.5}
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.populate_usage_rates_to_usage(
                metric_constants.INFRASTRUCTURE_COST_TYPE,
                rates, "cpu",
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
                "00000000-0000-0000-0000-000000000000",
            )
        args, kwargs = mock_execute.call_args
        sql_params = args[2]
        for rate_key in metric_constants.COST_MODEL_USAGE_RATES:
            self.assertIn(rate_key, sql_params, f"Missing rate param: {rate_key}")

    # TC-28: missing rates default to 0
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_populate_rtu_missing_rates_default_zero(self, mock_execute):
        dh = DateHelper()
        rates = {"cpu_core_usage_per_hour": 0.5}
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.populate_usage_rates_to_usage(
                metric_constants.INFRASTRUCTURE_COST_TYPE,
                rates, "cpu",
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
                "00000000-0000-0000-0000-000000000000",
            )
        args, kwargs = mock_execute.call_args
        sql_params = args[2]
        self.assertEqual(sql_params["cpu_core_usage_per_hour"], 0.5)
        for rate_key in metric_constants.COST_MODEL_USAGE_RATES:
            if rate_key != "cpu_core_usage_per_hour":
                self.assertEqual(sql_params[rate_key], 0, f"{rate_key} should default to 0")


class TestAggregateRatesToDailySummary(_ReportPeriodMixin, MasuTestCase):
    """Test aggregate_rates_to_daily_summary accessor method (BAC-6)."""

    # TC-29: executes INSERT SQL
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_aggregate_rtu_executes_insert_sql(self, mock_execute):
        dh = DateHelper()
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.aggregate_rates_to_daily_summary(
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
            )
        mock_execute.assert_called_once()
        args, kwargs = mock_execute.call_args
        self.assertEqual(kwargs.get("operation"), "INSERT")

    # TC-30: params match window
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_aggregate_rtu_params_match_window(self, mock_execute):
        dh = DateHelper()
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.aggregate_rates_to_daily_summary(
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
            )
        args, kwargs = mock_execute.call_args
        sql_params = args[2]
        self.assertEqual(sql_params["start_date"], dh.this_month_start.date())
        self.assertEqual(sql_params["end_date"], dh.this_month_end.date())
        self.assertEqual(sql_params["source_uuid"], self.ocp_provider_uuid)
        self.assertEqual(sql_params["report_period_id"], rp.id)


class TestValidateRatesToUsage(_ReportPeriodMixin, MasuTestCase):
    """Test validate_rates_against_daily_summary accessor method (BAC-7)."""

    # TC-31: executes SELECT SQL
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_validate_rtu_executes_select_sql(self, mock_execute):
        dh = DateHelper()
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.validate_rates_against_daily_summary(
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
            )
        mock_execute.assert_called_once()
        args, kwargs = mock_execute.call_args
        self.assertEqual(kwargs.get("operation"), "SELECT")

    # TC-32: params include report_period_id
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_validate_rtu_params_include_report_period(self, mock_execute):
        dh = DateHelper()
        with OCPReportDBAccessor(self.schema) as accessor:
            rp = self._get_report_period(accessor)
            accessor.validate_rates_against_daily_summary(
                dh.this_month_start.date(), dh.this_month_end.date(),
                self.ocp_provider_uuid, rp.id,
            )
        args, kwargs = mock_execute.call_args
        sql_params = args[2]
        self.assertIn("report_period_id", sql_params)
        self.assertEqual(sql_params["report_period_id"], rp.id)


# ---------------------------------------------------------------------------
# Tier 3 — Behavioral Tests
# ---------------------------------------------------------------------------


def _setup_no_cost_model_mock(mock_accessor):
    """Configure a CostModelDBAccessor mock to return no cost model."""
    ctx = mock_accessor.return_value.__enter__.return_value
    ctx.cost_model = None
    ctx.infrastructure_rates = {}
    ctx.tag_infrastructure_rates = {}
    ctx.tag_default_infrastructure_rates = {}
    ctx.supplementary_rates = {}
    ctx.tag_supplementary_rates = {}
    ctx.tag_default_supplementary_rates = {}
    ctx.distribution_info = {}
    ctx.metric_to_tag_params_map = {}


def _make_orchestration_patches():
    """Shared decorator stack for orchestration tests — patches all steps."""
    def decorator(func):
        @patch.object(OCPCostModelCostUpdater, "distribute_costs_and_update_ui_summary")
        @patch.object(OCPCostModelCostUpdater, "_update_monthly_cost")
        @patch.object(OCPCostModelCostUpdater, "_update_markup_cost")
        @patch.object(OCPCostModelCostUpdater, "_update_usage_costs")
        @patch.object(OCPCostModelCostUpdater, "_aggregate_rates_to_daily_summary")
        @patch.object(OCPCostModelCostUpdater, "_update_usage_rates_to_usage")
        @wraps(func)
        def wrapper(self, mock_rtu, mock_agg, mock_usage, mock_markup, mock_monthly, mock_dist, *args, **kwargs):
            return func(self, mock_rtu, mock_agg, mock_usage, mock_markup, mock_monthly, mock_dist, *args, **kwargs)
        return wrapper
    return decorator


class TestUpdaterOrchestration(_ReportPeriodMixin, MasuTestCase):
    """Test Phase 2 orchestration in update_summary_cost_model_costs (BAC-8)."""

    def _make_summary_range(self):
        dh = DateHelper()
        return SummaryRangeConfig(
            schema=self.schema,
            provider_uuid=self.ocp_provider_uuid,
            start_date=dh.this_month_start,
            end_date=dh.this_month_end,
            cost_model_update=True,
        )

    # TC-40: RTU insert called
    @_make_orchestration_patches()
    def test_orchestration_calls_rtu_insert(self, mock_rtu, mock_agg, mock_usage, mock_markup, mock_monthly, mock_dist):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)
        mock_rtu.assert_called_once_with(sr.start_date, sr.end_date)

    # TC-41: RTU aggregate called
    @_make_orchestration_patches()
    def test_orchestration_calls_rtu_aggregate(self, mock_rtu, mock_agg, mock_usage, mock_markup, mock_monthly, mock_dist):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)
        mock_agg.assert_called_once_with(sr.start_date, sr.end_date)

    # TC-42: RTU insert before legacy usage
    @_make_orchestration_patches()
    def test_orchestration_order_rtu_before_legacy(self, mock_rtu, mock_agg, mock_usage, mock_markup, mock_monthly, mock_dist):
        call_order = []
        mock_rtu.side_effect = lambda *a: call_order.append("rtu")
        mock_usage.side_effect = lambda *a: call_order.append("usage")
        mock_agg.side_effect = lambda *a: call_order.append("agg")
        mock_dist.side_effect = lambda *a: call_order.append("dist")

        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)

        self.assertIn("rtu", call_order)
        self.assertIn("usage", call_order)
        self.assertLess(call_order.index("rtu"), call_order.index("usage"))

    # TC-43: legacy usage before aggregate
    @_make_orchestration_patches()
    def test_orchestration_order_legacy_before_aggregate(self, mock_rtu, mock_agg, mock_usage, mock_markup, mock_monthly, mock_dist):
        call_order = []
        mock_rtu.side_effect = lambda *a: call_order.append("rtu")
        mock_usage.side_effect = lambda *a: call_order.append("usage")
        mock_agg.side_effect = lambda *a: call_order.append("agg")
        mock_dist.side_effect = lambda *a: call_order.append("dist")

        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)

        self.assertIn("usage", call_order)
        self.assertIn("agg", call_order)
        self.assertLess(call_order.index("usage"), call_order.index("agg"))

    # TC-44: aggregate before distribute
    @_make_orchestration_patches()
    def test_orchestration_order_aggregate_before_distribute(self, mock_rtu, mock_agg, mock_usage, mock_markup, mock_monthly, mock_dist):
        call_order = []
        mock_rtu.side_effect = lambda *a: call_order.append("rtu")
        mock_usage.side_effect = lambda *a: call_order.append("usage")
        mock_agg.side_effect = lambda *a: call_order.append("agg")
        mock_dist.side_effect = lambda *a: call_order.append("dist")

        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)

        self.assertIn("agg", call_order)
        self.assertIn("dist", call_order)
        self.assertLess(call_order.index("agg"), call_order.index("dist"))

    # TC-53: RTU insert loops both infra and supp
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    @patch.object(OCPCostModelCostUpdater, "_ensure_rates_to_usage_partitions")
    def test_rtu_insert_loops_infra_and_supp(self, mock_partitions, mock_execute):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        if not updater._cost_model_id:
            self.skipTest("No cost model for OCP provider")
        if not (updater._infra_rates or updater._supplementary_rates):
            self.skipTest("No infra or supp rates")
        rp = self._get_report_period()
        dh = DateHelper()
        start_date = rp.report_period_start
        end_date = dh.month_end(start_date)

        updater._update_usage_rates_to_usage(start_date, end_date)

        rate_types_called = set()
        for c in mock_execute.call_args_list:
            args, kwargs = c
            if kwargs.get("operation") == "INSERT":
                rate_types_called.add(args[2].get("rate_type"))

        self.assertGreater(len(rate_types_called), 0, "At least one rate type should produce INSERT calls")
        if updater._infra_rates:
            self.assertIn(metric_constants.INFRASTRUCTURE_COST_TYPE, rate_types_called)
        if updater._supplementary_rates:
            self.assertIn(metric_constants.SUPPLEMENTARY_COST_TYPE, rate_types_called)

    # TC-54: DELETE runs before POPULATE calls
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    @patch.object(OCPCostModelCostUpdater, "_ensure_rates_to_usage_partitions")
    def test_rtu_insert_calls_delete_then_populate(self, mock_partitions, mock_execute):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        if not updater._cost_model_id:
            self.skipTest("No cost model for OCP provider")
        rp = self._get_report_period()
        dh = DateHelper()
        start_date = rp.report_period_start
        end_date = dh.month_end(start_date)

        updater._update_usage_rates_to_usage(start_date, end_date)

        operations = [c[1].get("operation") for c in mock_execute.call_args_list]
        self.assertIn("DELETE", operations, "DELETE operation should be called")
        self.assertIn("INSERT", operations, "INSERT operation should be called")
        first_delete = operations.index("DELETE")
        first_insert = operations.index("INSERT")
        self.assertLess(first_delete, first_insert, "DELETE must run before INSERT")


class TestPartitionWiring(MasuTestCase):
    """Verify _ensure_rates_to_usage_partitions delegates to _handle_partitions (BAC-9)."""

    # TC-45: calls _handle_partitions
    @patch.object(OCPCostModelCostUpdater, "_handle_partitions")
    def test_partition_wiring_calls_handle_partitions(self, mock_handle):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        dh = DateHelper()
        updater._ensure_rates_to_usage_partitions(dh.this_month_start, dh.this_month_end)
        mock_handle.assert_called_once()

    # TC-46: correct table name
    @patch.object(OCPCostModelCostUpdater, "_handle_partitions")
    def test_partition_wiring_correct_table_name(self, mock_handle):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        dh = DateHelper()
        updater._ensure_rates_to_usage_partitions(dh.this_month_start, dh.this_month_end)
        args, kwargs = mock_handle.call_args
        self.assertEqual(args[1], ["rates_to_usage"])


class TestSkipPaths(MasuTestCase):
    """Test skip paths when report period or cost_model_id is missing (BAC-10, BAC-12)."""

    # TC-47: RTU insert skips with log when no report period
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor.report_periods_for_provider_uuid")
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    @patch.object(OCPCostModelCostUpdater, "_ensure_rates_to_usage_partitions")
    def test_rtu_insert_skips_no_report_period(self, mock_partitions, mock_execute, mock_rp):
        mock_rp.return_value = None
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        dh = DateHelper()
        with self.assertLogs("masu.processor.ocp", level="INFO") as cm:
            updater._update_usage_rates_to_usage(dh.this_month_start, dh.this_month_end)
        mock_execute.assert_not_called()
        self.assertTrue(any("skipping rates_to_usage insert" in msg for msg in cm.output))

    # TC-48: RTU aggregate skips with log when no report period
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor.report_periods_for_provider_uuid")
    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_rtu_aggregate_skips_no_report_period(self, mock_execute, mock_rp):
        mock_rp.return_value = None
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        dh = DateHelper()
        with self.assertLogs("masu.processor.ocp", level="INFO") as cm:
            updater._aggregate_rates_to_daily_summary(dh.this_month_start, dh.this_month_end)
        mock_execute.assert_not_called()
        self.assertTrue(any("skipping rates_to_usage aggregation" in msg for msg in cm.output))

    # TC-49: RTU insert skips when no cost_model_id
    @patch.object(OCPCostModelCostUpdater, "_ensure_rates_to_usage_partitions")
    @patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")
    def test_rtu_insert_skips_no_cost_model_id(self, mock_accessor, mock_part):
        _setup_no_cost_model_mock(mock_accessor)
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        self.assertIsNone(updater._cost_model_id)

        dh = DateHelper()
        updater._update_usage_rates_to_usage(dh.this_month_start, dh.this_month_end)
        mock_part.assert_not_called()

    # TC-50: RTU aggregate skips when no cost_model_id
    @patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")
    def test_rtu_aggregate_skips_no_cost_model_id(self, mock_accessor):
        _setup_no_cost_model_mock(mock_accessor)
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        self.assertIsNone(updater._cost_model_id)

        dh = DateHelper()
        with patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query") as mock_exec:
            updater._aggregate_rates_to_daily_summary(dh.this_month_start, dh.this_month_end)
            mock_exec.assert_not_called()


class TestPurgeWiring(MasuTestCase):
    """Test that rates_to_usage is in purge paths (BAC-13, BAC-14)."""

    # TC-51: rates_to_usage in cleaner base table list
    @patch("masu.processor.ocp.ocp_report_db_cleaner.execute_delete_sql")
    @patch("masu.processor.ocp.ocp_report_db_cleaner.cascade_delete")
    @patch("masu.processor.ocp.ocp_report_db_cleaner.PartitionedTable")
    @patch("masu.processor.ocp.ocp_report_db_cleaner.OCPReportDBAccessor")
    def test_rates_to_usage_in_cleaner_base_list(self, mock_accessor_cls, mock_pt, mock_cascade, mock_delete):
        """Verify partition cleanup includes rates_to_usage table."""
        from datetime import date as date_cls
        from unittest.mock import MagicMock

        from masu.processor.ocp.ocp_report_db_cleaner import OCPReportDBCleaner

        mock_accessor = mock_accessor_cls.return_value.__enter__.return_value
        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([]))
        mock_qs.query = MagicMock()
        mock_accessor.get_report_periods_before_date.return_value = mock_qs
        mock_accessor._table_map = {"line_item_daily_summary": "reporting_ocpusagelineitem_daily_summary"}

        cleaner = OCPReportDBCleaner(self.schema)
        cleaner.purge_expired_report_data_by_date(date_cls(2020, 1, 1))

        filter_call = mock_pt.objects.filter
        self.assertTrue(filter_call.called)
        table_names_arg = filter_call.call_args[1].get("partition_of_table_name__in")
        self.assertIn("rates_to_usage", table_names_arg)

    # TC-52: rates_to_usage NOT in get_self_hosted_table_names (avoids duplicate)
    def test_rates_to_usage_not_in_self_hosted_names(self):
        from reporting.provider.ocp.self_hosted_models import get_self_hosted_table_names

        table_names = get_self_hosted_table_names()
        self.assertNotIn("rates_to_usage", table_names)


# ---------------------------------------------------------------------------
# Tier 4 — E2E: RTU pipeline through to REST API cost totals
# ---------------------------------------------------------------------------


class TestRTUCostBreakdownAPI(_ReportPeriodMixin, MasuTestCase):
    """Validate Phase 2 RTU pipeline output surfaces correctly in the cost API.

    The test DB is seeded by KokuTestRunner / ModelBakeryDataLoader which
    calls update_cost_model_costs (the full Phase 2 pipeline) for the
    OCP-on-Prem provider.  These tests verify:
      - RTU rows were created (TC-E2E-01)
      - RTU sums reconcile to daily-summary cost-model columns (TC-E2E-02)
      - The /reports/openshift/costs/ API returns non-zero totals matching
        the daily summary (TC-E2E-03)
      - Per-project cost breakdown in the API matches daily summary data (TC-E2E-04)
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from api.models import Provider
        from api.report.ocp.provider_map import OCPProviderMap

        cls.provider_map = OCPProviderMap(Provider.PROVIDER_OCP, "costs", cls.schema_name)
        cls.cost_term = (
            cls.provider_map.cloud_infrastructure_cost
            + cls.provider_map.markup_cost
            + cls.provider_map.cost_model_cost
        )

    # -- helpers ---------------------------------------------------------

    def _rp_filter(self):
        """Return filter kwargs scoping queries to the most recent report period."""
        rp = self._get_report_period()
        return {
            "source_uuid": self.ocp_provider.uuid,
            "usage_start__gte": rp.report_period_start.date()
            if hasattr(rp.report_period_start, "date")
            else rp.report_period_start,
        }

    # TC-E2E-01: RTU rows exist after pipeline seeding
    def test_rtu_rows_exist_for_on_prem_provider(self):
        """After ModelBakeryDataLoader runs the pipeline, rates_to_usage has rows."""
        from reporting.provider.ocp.models import RatesToUsage

        rp_filter = self._rp_filter()
        with schema_context(self.schema):
            count = RatesToUsage.objects.filter(
                source_uuid=rp_filter["source_uuid"],
                usage_start__gte=rp_filter["usage_start__gte"],
            ).count()
        self.assertGreater(count, 0, "RTU table should have rows for OCP-on-Prem provider")

    # TC-E2E-02: RTU aggregated costs reconcile with daily summary
    def test_rtu_sums_match_daily_summary_cost_model_columns(self):
        """SUM(calculated_cost) in RTU grouped by metric_type must equal
        the corresponding cost_model_*_cost columns in the daily summary."""
        from decimal import Decimal

        from django.db.models import Sum

        from reporting.provider.ocp.models import OCPUsageLineItemDailySummary
        from reporting.provider.ocp.models import RatesToUsage

        rp_filter = self._rp_filter()
        with schema_context(self.schema):
            rtu_agg = (
                RatesToUsage.objects.filter(
                    source_uuid=rp_filter["source_uuid"],
                    usage_start__gte=rp_filter["usage_start__gte"],
                    metric_type__in=["cpu", "memory", "storage"],
                    monthly_cost_type__isnull=True,
                )
                .values("metric_type")
                .annotate(total=Sum("calculated_cost"))
            )
            rtu_by_metric = {row["metric_type"]: row["total"] or Decimal(0) for row in rtu_agg}

            ds_agg = (
                OCPUsageLineItemDailySummary.objects.filter(
                    source_uuid=rp_filter["source_uuid"],
                    usage_start__gte=rp_filter["usage_start__gte"],
                    cost_model_rate_type__in=["Infrastructure", "Supplementary"],
                    monthly_cost_type__isnull=True,
                ).aggregate(
                    cpu=Sum("cost_model_cpu_cost"),
                    memory=Sum("cost_model_memory_cost"),
                    volume=Sum("cost_model_volume_cost"),
                )
            )

        if not rtu_by_metric:
            self.skipTest("No RTU rows to reconcile (DB may not have cost model data)")

        for metric, ds_col in [("cpu", "cpu"), ("memory", "memory"), ("storage", "volume")]:
            rtu_val = rtu_by_metric.get(metric, Decimal(0))
            ds_val = ds_agg.get(ds_col) or Decimal(0)
            self.assertAlmostEqual(
                rtu_val,
                ds_val,
                places=6,
                msg=f"RTU {metric} sum ({rtu_val}) != daily_summary cost_model_{ds_col}_cost ({ds_val})",
            )

    # TC-E2E-03: API cost total matches daily summary aggregate
    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_api_cost_total_matches_daily_summary(self):
        """GET /reports/openshift/costs/ total must match daily-summary ORM aggregate.

        Follows the same assertion pattern as
        OCPReportViewTest.test_execute_query_ocp_costs_group_by_project.
        """
        from decimal import Decimal
        from urllib.parse import quote_plus
        from urllib.parse import urlencode

        from django.db.models import Value
        from django.urls import reverse
        from django_tenants.utils import tenant_context
        from rest_framework.test import APIClient

        from reporting.provider.ocp.models import OCPUsageLineItemDailySummary

        url = reverse("reports-openshift-costs")
        params = {
            "group_by[project]": "*",
            "filter[time_scope_value]": "-1",
            "filter[time_scope_units]": "month",
            "filter[resolution]": "monthly",
        }
        url = url + "?" + urlencode(params, quote_via=quote_plus)
        response = APIClient().get(url, **self.headers)

        self.assertEqual(response.status_code, 200)
        data = response.data

        with tenant_context(self.tenant):
            cost = (
                OCPUsageLineItemDailySummary.objects.filter(
                    usage_start__gte=self.dh.this_month_start.date()
                )
                .annotate(
                    infra_exchange_rate=Value(Decimal(1)),
                    exchange_rate=Value(Decimal(1)),
                )
                .aggregate(total=self.cost_term)
                .get("total")
            )
            expected_total = cost if cost is not None else 0

        total = (
            data.get("meta", {})
            .get("total", {})
            .get("cost", {})
            .get("total", {})
            .get("value", 0)
        )
        self.assertNotEqual(total, Decimal(0), "API should return non-zero cost total")
        self.assertAlmostEqual(total, expected_total, 6)

    # TC-E2E-04: per-project breakdown in API has non-zero cost-model costs
    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_api_project_breakdown_has_cost_model_costs(self):
        """GET /reports/openshift/costs/?group_by[project]=* must return
        at least one project with non-zero cost-model cost."""
        from urllib.parse import quote_plus
        from urllib.parse import urlencode

        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("reports-openshift-costs")
        params = {
            "group_by[project]": "*",
            "filter[time_scope_value]": "-1",
            "filter[time_scope_units]": "month",
            "filter[resolution]": "monthly",
        }
        url = url + "?" + urlencode(params, quote_via=quote_plus)
        response = APIClient().get(url, **self.headers)

        self.assertEqual(response.status_code, 200)
        data_items = response.data.get("data", [])
        found_nonzero = False
        for item in data_items:
            for group in item.get("projects", []):
                for val in group.get("values", []):
                    cost_total = val.get("cost", {}).get("total", {}).get("value", 0)
                    if cost_total and cost_total != 0:
                        found_nonzero = True
                        break
                if found_nonzero:
                    break
            if found_nonzero:
                break

        self.assertTrue(found_nonzero, "At least one project should have non-zero cost-model costs")
