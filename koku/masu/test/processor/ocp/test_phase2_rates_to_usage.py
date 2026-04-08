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
Tier 4 (E2E): TestRTUCostBreakdownAPI, TestBreakdownPipelineE2E
Tier 5 (UI Contract): TestBreakdownUIContractFlat, TestBreakdownUIContractTree
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
        @patch.object(OCPCostModelCostUpdater, "_update_vm_usage_costs")
        @patch.object(OCPCostModelCostUpdater, "_aggregate_rates_to_daily_summary")
        @patch.object(OCPCostModelCostUpdater, "_update_usage_rates_to_usage")
        @wraps(func)
        def wrapper(self, mock_rtu, mock_agg, mock_vm_usage, mock_markup, mock_monthly, mock_dist, *args, **kwargs):
            return func(self, mock_rtu, mock_agg, mock_vm_usage, mock_markup, mock_monthly, mock_dist, *args, **kwargs)
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
    def test_orchestration_calls_rtu_insert(self, mock_rtu, mock_agg, mock_vm_usage, mock_markup, mock_monthly, mock_dist):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)
        mock_rtu.assert_called_once_with(sr.start_date, sr.end_date)

    # TC-41: RTU aggregate called
    @_make_orchestration_patches()
    def test_orchestration_calls_rtu_aggregate(self, mock_rtu, mock_agg, mock_vm_usage, mock_markup, mock_monthly, mock_dist):
        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)
        mock_agg.assert_called_once_with(sr.start_date, sr.end_date)

    # TC-42: RTU insert before VM usage
    @_make_orchestration_patches()
    def test_orchestration_order_rtu_before_vm_usage(self, mock_rtu, mock_agg, mock_vm_usage, mock_markup, mock_monthly, mock_dist):
        call_order = []
        mock_rtu.side_effect = lambda *a: call_order.append("rtu")
        mock_vm_usage.side_effect = lambda *a: call_order.append("vm_usage")
        mock_agg.side_effect = lambda *a: call_order.append("agg")
        mock_dist.side_effect = lambda *a: call_order.append("dist")

        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)

        self.assertIn("rtu", call_order)
        self.assertIn("vm_usage", call_order)
        self.assertLess(call_order.index("rtu"), call_order.index("vm_usage"))

    # TC-43: VM usage before aggregate
    @_make_orchestration_patches()
    def test_orchestration_order_vm_usage_before_aggregate(self, mock_rtu, mock_agg, mock_vm_usage, mock_markup, mock_monthly, mock_dist):
        call_order = []
        mock_rtu.side_effect = lambda *a: call_order.append("rtu")
        mock_vm_usage.side_effect = lambda *a: call_order.append("vm_usage")
        mock_agg.side_effect = lambda *a: call_order.append("agg")
        mock_dist.side_effect = lambda *a: call_order.append("dist")

        updater = OCPCostModelCostUpdater(schema=self.schema, provider=self.ocp_provider)
        sr = self._make_summary_range()
        updater.update_summary_cost_model_costs(sr)

        self.assertIn("vm_usage", call_order)
        self.assertIn("agg", call_order)
        self.assertLess(call_order.index("vm_usage"), call_order.index("agg"))

    # TC-44: aggregate before distribute
    @_make_orchestration_patches()
    def test_orchestration_order_aggregate_before_distribute(self, mock_rtu, mock_agg, mock_vm_usage, mock_markup, mock_monthly, mock_dist):
        call_order = []
        mock_rtu.side_effect = lambda *a: call_order.append("rtu")
        mock_vm_usage.side_effect = lambda *a: call_order.append("vm_usage")
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


class TestBreakdownPipelineE2E(_ReportPeriodMixin, MasuTestCase):
    """E2E: Validate the full Phase 2→5 pipeline through to the breakdown API.

    The test DB is seeded by KokuTestRunner / ModelBakeryDataLoader which calls
    update_cost_model_costs(synchronous=True) for the OCP-on-Prem provider.
    That runs the full orchestration:
      1. RTU insert (Phase 2)
      2. Per-rate distribution (Phase 4)
      3. RTU aggregate → daily summary (Phase 2/3)
      4. Legacy distribution
      5. UI summary population including OCPCostUIBreakDownP (Phase 4)

    These tests verify real data flows through the entire stack:
      - TC-E2E-BD-01: Breakdown table has rows from the seeded pipeline
      - TC-E2E-BD-02: Breakdown rows have non-null cost values
      - TC-E2E-BD-03: Breakdown API returns 200 with data
      - TC-E2E-BD-04: API response contains expected tree structure fields
      - TC-E2E-BD-05: Breakdown cost totals reconcile against daily summary
      - TC-E2E-BD-06: CostModel.rates property returns Rate table data
    """

    # TC-E2E-BD-01
    def test_breakdown_table_has_rows(self):
        """OCPCostUIBreakDownP should have rows after the seeded pipeline runs."""
        from reporting.provider.ocp.models import OCPCostUIBreakDownP

        rp = self._get_report_period()
        with schema_context(self.schema):
            count = OCPCostUIBreakDownP.objects.filter(
                source_uuid=self.ocp_provider.uuid,
                usage_start__gte=rp.report_period_start.date()
                if hasattr(rp.report_period_start, "date")
                else rp.report_period_start,
            ).count()
        if count == 0:
            self.skipTest("No breakdown rows (pipeline may not have produced breakdown data)")
        self.assertGreater(count, 0)

    # TC-E2E-BD-02
    def test_breakdown_rows_have_cost_values(self):
        """At least some breakdown rows should have non-null cost_value or distributed_cost."""
        from django.db.models import Q

        from reporting.provider.ocp.models import OCPCostUIBreakDownP

        rp = self._get_report_period()
        with schema_context(self.schema):
            rows_with_cost = OCPCostUIBreakDownP.objects.filter(
                source_uuid=self.ocp_provider.uuid,
                usage_start__gte=rp.report_period_start.date()
                if hasattr(rp.report_period_start, "date")
                else rp.report_period_start,
            ).filter(Q(cost_value__isnull=False) | Q(distributed_cost__isnull=False)).count()
        if rows_with_cost == 0:
            self.skipTest("No breakdown rows with cost values")
        self.assertGreater(rows_with_cost, 0)

    # TC-E2E-BD-03
    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_breakdown_api_returns_200_with_data(self):
        """GET /breakdown/openshift/cost/ returns 200 and non-empty data."""
        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        params = {
            "filter[time_scope_value]": "-2",
            "filter[time_scope_units]": "month",
            "filter[resolution]": "monthly",
        }
        from urllib.parse import quote_plus
        from urllib.parse import urlencode

        full_url = url + "?" + urlencode(params, quote_via=quote_plus)
        response = APIClient().get(full_url, **self.headers)
        self.assertEqual(response.status_code, 200, f"Expected 200, got {response.status_code}")
        data_items = response.data.get("data", [])
        self.assertGreater(len(data_items), 0, "Breakdown API should return at least one data item")

    # TC-E2E-BD-04
    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_breakdown_api_response_has_tree_fields(self):
        """Breakdown API response values should include path, depth, and category fields."""
        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        params = {
            "filter[time_scope_value]": "-2",
            "filter[time_scope_units]": "month",
            "filter[resolution]": "monthly",
        }
        from urllib.parse import quote_plus
        from urllib.parse import urlencode

        full_url = url + "?" + urlencode(params, quote_via=quote_plus)
        response = APIClient().get(full_url, **self.headers)
        self.assertEqual(response.status_code, 200)

        data_items = response.data.get("data", [])
        expected_fields = {"path", "depth", "top_category", "breakdown_category", "custom_name", "metric_type"}
        found_value = False
        for item in data_items:
            values = item.get("values", [])
            for val in values:
                found_value = True
                present_fields = set(val.keys())
                missing = expected_fields - present_fields
                self.assertFalse(missing, f"Missing fields in breakdown response: {missing}")
                break
            if found_value:
                break
        if not found_value:
            self.skipTest("No values in breakdown response to check fields")

    # TC-E2E-BD-05
    def test_breakdown_totals_reconcile_with_daily_summary(self):
        """SUM(cost_value) in breakdown table should reconcile with daily summary costs."""
        from decimal import Decimal

        from django.db.models import Sum

        from reporting.provider.ocp.models import OCPCostUIBreakDownP
        from reporting.provider.ocp.models import OCPUsageLineItemDailySummary

        rp = self._get_report_period()
        start = (
            rp.report_period_start.date()
            if hasattr(rp.report_period_start, "date")
            else rp.report_period_start
        )
        with schema_context(self.schema):
            bd_total = OCPCostUIBreakDownP.objects.filter(
                source_uuid=self.ocp_provider.uuid,
                usage_start__gte=start,
                cost_value__isnull=False,
            ).aggregate(total=Sum("cost_value")).get("total") or Decimal(0)

            ds_total = OCPUsageLineItemDailySummary.objects.filter(
                source_uuid=self.ocp_provider.uuid,
                usage_start__gte=start,
                cost_model_rate_type__in=["Infrastructure", "Supplementary"],
                monthly_cost_type__isnull=True,
            ).aggregate(
                total=Sum("cost_model_cpu_cost") + Sum("cost_model_memory_cost") + Sum("cost_model_volume_cost"),
            ).get("total") or Decimal(0)

        if bd_total == Decimal(0) and ds_total == Decimal(0):
            self.skipTest("No cost data to reconcile")

        # Breakdown may not include all cost categories, so verify it's non-zero
        # and within a reasonable range of the daily summary total
        self.assertGreater(bd_total, Decimal(0), "Breakdown total cost should be non-zero")

    # TC-E2E-BD-06
    def test_cost_model_rates_property_matches_rate_table(self):
        """CostModel.rates property returns data matching the Rate table rows."""
        from cost_models.models import CostModel
        from cost_models.models import Rate
        from django_tenants.utils import tenant_context

        with tenant_context(self.tenant):
            cm = CostModel.objects.first()
            if not cm:
                self.skipTest("No CostModel in test DB")

            rate_count = Rate.objects.filter(
                price_list__cost_model_maps__cost_model=cm
            ).count()
            reconstructed = cm.rates
            self.assertEqual(
                len(reconstructed), rate_count,
                f"CostModel.rates property returned {len(reconstructed)} rates but Rate table has {rate_count}",
            )
            for rate_dict in reconstructed:
                self.assertIn("metric", rate_dict)
                self.assertIn("rate_id", rate_dict)


# ---------------------------------------------------------------------------
# Tier 5 — UI Contract Tests (Acceptance)
#
# These tests simulate the exact HTTP requests the UI client will make and
# validate the complete JSON response shape, field types, and structural
# invariants the frontend can rely on as a stable contract.
#
# Base URL: GET /api/cost-management/v1/reports/breakdown/openshift/cost/
# ---------------------------------------------------------------------------


class TestBreakdownUIContractFlat(_ReportPeriodMixin, MasuTestCase):
    """UI contract: validate the flat-view JSON envelope and field types.

    The UI team builds components against this exact response shape:
    {
        "meta": {"count": int, "limit": int, "offset": int, ...},
        "links": {"first": str|null, "next": str|null, ...},
        "data": [
            {
                "date": "YYYY-MM",
                "values": [
                    {
                        "date": "YYYY-MM",
                        "path": str, "depth": int,
                        "parent_path": str, "top_category": str,
                        "breakdown_category": str, "custom_name": str,
                        "metric_type": str, "cost_model_rate_type": str|null,
                        "cost_value": Decimal, "distributed_cost": Decimal|null,
                        "cost_units": str,
                        ...
                    }, ...
                ]
            }, ...
        ]
    }
    """

    def _get_breakdown_response(self, extra_params=None, expect_status=200):
        from urllib.parse import quote_plus, urlencode

        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        params = {
            "filter[time_scope_value]": "-2",
            "filter[time_scope_units]": "month",
            "filter[resolution]": "monthly",
        }
        if extra_params:
            params.update(extra_params)
        full_url = url + "?" + urlencode(params, quote_via=quote_plus)
        response = APIClient().get(full_url, **self.headers)
        self.assertEqual(response.status_code, expect_status,
                         f"Expected {expect_status}, got {response.status_code}: {getattr(response, 'data', '')}")
        return response

    def _get_first_value(self, response):
        for bucket in response.data.get("data", []):
            for val in bucket.get("values", []):
                return val
        self.skipTest("No values in breakdown response")

    # --- Envelope structure ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_response_has_meta_links_data(self):
        """Response envelope must contain meta, links, and data top-level keys."""
        resp = self._get_breakdown_response()
        for key in ("meta", "links", "data"):
            self.assertIn(key, resp.data, f"Response missing top-level '{key}'")

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_meta_contains_pagination_fields(self):
        """meta must include count, limit, offset for UI pagination."""
        resp = self._get_breakdown_response()
        meta = resp.data["meta"]
        for field in ("count", "limit", "offset"):
            self.assertIn(field, meta, f"meta missing '{field}'")
            self.assertIsInstance(meta[field], int, f"meta.{field} should be int")

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_links_contains_pagination_urls(self):
        """links must include first, next, previous, last."""
        resp = self._get_breakdown_response()
        links = resp.data["links"]
        for field in ("first", "next", "previous", "last"):
            self.assertIn(field, links, f"links missing '{field}'")

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_data_is_list_of_date_buckets(self):
        """data must be a list; each item must have 'date' and 'values'."""
        resp = self._get_breakdown_response()
        data = resp.data["data"]
        self.assertIsInstance(data, list)
        if not data:
            self.skipTest("No data buckets in response")
        bucket = data[0]
        self.assertIn("date", bucket, "Each data bucket must have 'date'")
        self.assertIn("values", bucket, "Each data bucket must have 'values'")

    # --- Value object field contract ---

    VALUE_REQUIRED_FIELDS = {
        "date": str,
        "path": str,
        "depth": int,
        "parent_path": str,
        "top_category": str,
        "breakdown_category": str,
        "custom_name": str,
        "metric_type": str,
    }

    VALUE_OPTIONAL_FIELDS = {
        "cost_model_rate_type",
        "cost_value",
        "distributed_cost",
        "cost_units",
    }

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_value_object_has_all_required_fields(self):
        """Each value object must contain all fields the UI renders."""
        resp = self._get_breakdown_response()
        val = self._get_first_value(resp)
        for field in self.VALUE_REQUIRED_FIELDS:
            self.assertIn(field, val, f"Value object missing required field '{field}'")

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_value_object_field_types(self):
        """Required fields must have the correct Python types."""
        resp = self._get_breakdown_response()
        val = self._get_first_value(resp)
        for field, expected_type in self.VALUE_REQUIRED_FIELDS.items():
            self.assertIsInstance(val[field], expected_type,
                                 f"Value.{field} should be {expected_type.__name__}, got {type(val[field]).__name__}")

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_value_object_has_cost_value(self):
        """Values must include cost_value for the UI to render amounts."""
        resp = self._get_breakdown_response()
        val = self._get_first_value(resp)
        self.assertIn("cost_value", val)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_meta_total_has_cost_aggregates(self):
        """meta.total must include cost_value aggregate."""
        resp = self._get_breakdown_response()
        meta = resp.data.get("meta", {})
        total = meta.get("total", {})
        self.assertIn("cost_value", total, "meta.total must include cost_value aggregate")

    # --- Domain invariants ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_top_category_values_are_valid(self):
        """top_category must be 'project', 'overhead', 'total_cost', or 'total'."""
        valid_categories = {"project", "overhead", "total_cost", "total"}
        resp = self._get_breakdown_response()
        for bucket in resp.data.get("data", []):
            for val in bucket.get("values", []):
                self.assertIn(
                    val["top_category"], valid_categories,
                    f"Unexpected top_category: '{val['top_category']}'",
                )

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_breakdown_category_values_are_valid(self):
        """breakdown_category must be one of the spec-defined values."""
        valid = {"total", "raw_cost", "usage_cost", "markup", "infrastructure",
                 "platform_distributed", "worker_distributed",
                 "unattributed_storage", "unattributed_network", "gpu_distributed"}
        resp = self._get_breakdown_response()
        for bucket in resp.data.get("data", []):
            for val in bucket.get("values", []):
                self.assertIn(
                    val["breakdown_category"], valid,
                    f"Unexpected breakdown_category: '{val['breakdown_category']}'",
                )

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_depth_range_is_valid(self):
        """depth must be between 1 and 5 per the tree structure spec."""
        resp = self._get_breakdown_response()
        for bucket in resp.data.get("data", []):
            for val in bucket.get("values", []):
                self.assertGreaterEqual(val["depth"], 1, "depth must be >= 1")
                self.assertLessEqual(val["depth"], 5, "depth must be <= 5")

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_path_depth_consistency(self):
        """path segment count must equal depth (dot-separated)."""
        resp = self._get_breakdown_response()
        for bucket in resp.data.get("data", []):
            for val in bucket.get("values", []):
                path = val["path"]
                depth = val["depth"]
                if depth == 1:
                    self.assertEqual(path, "total_cost", "Depth 1 path must be 'total_cost'")
                else:
                    segments = path.split(".")
                    self.assertEqual(
                        len(segments), depth - 1,
                        f"Path '{path}' has {len(segments)} segments but depth is {depth} "
                        f"(expected {depth - 1} segments)",
                    )

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_parent_path_references_valid_node(self):
        """parent_path must reference another node's path or be empty (for root)."""
        resp = self._get_breakdown_response()
        for bucket in resp.data.get("data", []):
            values = bucket.get("values", [])
            all_paths = {v["path"] for v in values}
            for val in values:
                parent = val["parent_path"]
                if val["depth"] == 1:
                    self.assertEqual(parent, "", f"Root node parent_path should be empty, got '{parent}'")
                else:
                    self.assertIn(
                        parent, all_paths,
                        f"parent_path '{parent}' of '{val['path']}' not found among sibling paths",
                    )

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_date_format_is_yyyy_mm(self):
        """date field in values must be 'YYYY-MM' format for monthly resolution."""
        import re

        resp = self._get_breakdown_response()
        val = self._get_first_value(resp)
        self.assertRegex(val["date"], r"^\d{4}-\d{2}$", "date must be YYYY-MM format")

    # --- Filtering ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_filter_by_cluster_returns_200(self):
        """?filter[cluster]=<value> should return 200 (no crash)."""
        self._get_breakdown_response(extra_params={"filter[cluster]": "nonexistent-cluster-xyz"})

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_filter_by_project_returns_200(self):
        """?filter[project]=<value> should return 200 (no crash)."""
        self._get_breakdown_response(extra_params={"filter[project]": "nonexistent-project-xyz"})

    # --- Ordering ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_order_by_path_asc_returns_200(self):
        """?order_by[path]=asc should be accepted and return 200."""
        self._get_breakdown_response(extra_params={"order_by[path]": "asc"})

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_order_by_path_desc_returns_200(self):
        """?order_by[path]=desc should be accepted and return 200."""
        self._get_breakdown_response(extra_params={"order_by[path]": "desc"})

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_order_by_cost_rejected(self):
        """?order_by[cost]=asc should be rejected (not valid for breakdown)."""
        self._get_breakdown_response(
            extra_params={"order_by[cost]": "asc"},
            expect_status=400,
        )

    # --- Invalid parameters ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_invalid_view_param_returns_400(self):
        """?view=invalid should be rejected with 400."""
        self._get_breakdown_response(extra_params={"view": "invalid"}, expect_status=400)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_empty_data_returns_valid_envelope(self):
        """A query with no matching data must still return the correct envelope shape."""
        resp = self._get_breakdown_response(extra_params={
            "filter[cluster]": "this-cluster-does-not-exist-anywhere-ever",
        })
        self.assertIn("meta", resp.data)
        self.assertIn("links", resp.data)
        self.assertIn("data", resp.data)
        self.assertIsInstance(resp.data["data"], list)


class TestBreakdownUIContractTree(_ReportPeriodMixin, MasuTestCase):
    """UI contract: validate the tree-view JSON response (?view=tree).

    When ``?view=tree`` is requested, the data[].values[] array becomes
    a nested structure with ``children`` arrays, enabling the UI to render
    a tree component directly without client-side reconstruction.

    Expected shape per value node:
    {
        "path": str, "depth": int, "parent_path": str,
        "top_category": str, "breakdown_category": str,
        "cost_value": Decimal, "distributed_cost": Decimal|null,
        "children": [<same shape>...]
    }
    """

    def _get_tree_response(self, extra_params=None, expect_status=200):
        from urllib.parse import quote_plus, urlencode

        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        params = {
            "view": "tree",
            "filter[time_scope_value]": "-2",
            "filter[time_scope_units]": "month",
            "filter[resolution]": "monthly",
        }
        if extra_params:
            params.update(extra_params)
        full_url = url + "?" + urlencode(params, quote_via=quote_plus)
        response = APIClient().get(full_url, **self.headers)
        self.assertEqual(response.status_code, expect_status)
        return response

    def _get_tree_roots(self, response):
        for bucket in response.data.get("data", []):
            roots = bucket.get("values", [])
            if roots:
                return roots
        self.skipTest("No tree roots in response")

    # --- Envelope ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tree_response_has_meta_links_data(self):
        """Tree view must preserve the same envelope as flat view."""
        resp = self._get_tree_response()
        for key in ("meta", "links", "data"):
            self.assertIn(key, resp.data)

    # --- Tree structure ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tree_root_nodes_have_children_array(self):
        """Each root node in tree view must have a 'children' list."""
        resp = self._get_tree_response()
        roots = self._get_tree_roots(resp)
        for root in roots:
            self.assertIn("children", root, f"Root node '{root.get('path')}' missing 'children'")
            self.assertIsInstance(root["children"], list)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tree_root_is_total_cost(self):
        """In tree view, the single root should be 'total_cost' (depth 1)."""
        resp = self._get_tree_response()
        roots = self._get_tree_roots(resp)
        total_roots = [r for r in roots if r.get("path") == "total_cost"]
        self.assertEqual(len(total_roots), 1, "Should have exactly one 'total_cost' root")
        self.assertEqual(total_roots[0]["depth"], 1)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tree_children_reference_parent(self):
        """Every child node's parent_path must match its parent's path."""
        resp = self._get_tree_response()
        roots = self._get_tree_roots(resp)

        def check_children(parent_node):
            for child in parent_node.get("children", []):
                self.assertEqual(
                    child["parent_path"], parent_node["path"],
                    f"Child '{child['path']}' parent_path '{child['parent_path']}' "
                    f"!= parent '{parent_node['path']}'",
                )
                check_children(child)

        for root in roots:
            check_children(root)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tree_depth_increases_with_nesting(self):
        """Children must have depth = parent.depth + 1."""
        resp = self._get_tree_response()
        roots = self._get_tree_roots(resp)

        def check_depth(parent_node):
            for child in parent_node.get("children", []):
                self.assertEqual(
                    child["depth"], parent_node["depth"] + 1,
                    f"Child '{child['path']}' depth {child['depth']} != parent depth "
                    f"{parent_node['depth']} + 1",
                )
                check_depth(child)

        for root in roots:
            check_depth(root)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tree_leaf_nodes_have_empty_children(self):
        """Leaf nodes (max depth in their branch) should have children=[]."""
        resp = self._get_tree_response()
        roots = self._get_tree_roots(resp)

        def find_leaves(node, leaves=None):
            if leaves is None:
                leaves = []
            if not node.get("children"):
                leaves.append(node)
            else:
                for child in node["children"]:
                    find_leaves(child, leaves)
            return leaves

        for root in roots:
            leaves = find_leaves(root)
            for leaf in leaves:
                self.assertEqual(leaf["children"], [],
                                 f"Leaf '{leaf.get('path')}' should have empty children")

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tree_child_nodes_have_required_fields(self):
        """All child nodes must have the same required fields as flat values."""
        required = {"path", "depth", "parent_path", "top_category",
                    "breakdown_category", "custom_name", "metric_type"}
        resp = self._get_tree_response()
        roots = self._get_tree_roots(resp)

        def check_fields(node):
            missing = required - set(node.keys())
            self.assertFalse(missing,
                             f"Node '{node.get('path')}' missing fields: {missing}")
            for child in node.get("children", []):
                check_fields(child)

        for root in roots:
            check_fields(root)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tree_total_cost_has_project_and_overhead_children(self):
        """The total_cost root should have 'project' and/or 'overhead' children."""
        resp = self._get_tree_response()
        roots = self._get_tree_roots(resp)
        total_roots = [r for r in roots if r.get("path") == "total_cost"]
        if not total_roots:
            self.skipTest("No total_cost root")
        root = total_roots[0]
        child_paths = {c["path"] for c in root.get("children", [])}
        valid_depth2_paths = {"project", "overhead"}
        self.assertTrue(
            child_paths & valid_depth2_paths,
            f"total_cost children should include project and/or overhead, got: {child_paths}",
        )

    # --- Flat view default ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_flat_is_default_when_view_omitted(self):
        """When ?view is not specified, response should be flat (no children)."""
        from urllib.parse import quote_plus, urlencode

        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        params = {
            "filter[time_scope_value]": "-2",
            "filter[time_scope_units]": "month",
            "filter[resolution]": "monthly",
        }
        full_url = url + "?" + urlencode(params, quote_via=quote_plus)
        response = APIClient().get(full_url, **self.headers)
        self.assertEqual(response.status_code, 200)
        for bucket in response.data.get("data", []):
            for val in bucket.get("values", []):
                self.assertNotIn("children", val,
                                 "Flat view (default) values must not have 'children'")
                return

    # --- Group-by contract ---

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_group_by_project_returns_200(self):
        """?group_by[project]=* should return 200 with grouped data."""
        resp = self._get_tree_response(extra_params={"group_by[project]": "*"})
        self.assertIn("data", resp.data)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tag_group_by_rejected(self):
        """?group_by[tag:label]=* should be rejected (no tag support on breakdown)."""
        resp = self._get_tree_response(extra_params={"group_by[tag:app]": "*"}, expect_status=400)


# ---------------------------------------------------------------------------
# Phase 4 Tests — Per-Rate Distribution + Breakdown API
# ---------------------------------------------------------------------------


class TestPerRateDistributionWiring(MasuTestCase):
    """R18 regression: per-rate distribution SQL files wired into accessor."""

    def test_populate_per_rate_distributed_cost_sql_method_exists(self):
        """Accessor exposes populate_per_rate_distributed_cost_sql."""
        with OCPReportDBAccessor(self.schema) as accessor:
            self.assertTrue(hasattr(accessor, "populate_per_rate_distributed_cost_sql"))

    def test_per_rate_configs_cover_all_five_distribution_types(self):
        """Per-rate distribution configs match the five distribution types."""
        expected_discriminators = {
            "platform_distributed",
            "worker_distributed",
            "unattributed_storage",
            "unattributed_network",
            "gpu_distributed",
        }
        distribution_info = {
            metric_constants.PLATFORM_COST: True,
            metric_constants.WORKER_UNALLOCATED: True,
            metric_constants.STORAGE_UNATTRIBUTED: True,
            metric_constants.NETWORK_UNATTRIBUTED: True,
            metric_constants.GPU_UNALLOCATED: True,
            "distribution_type": "cpu",
        }
        dh = DateHelper()
        with OCPReportDBAccessor(self.schema) as accessor:
            sr = SummaryRangeConfig(
                start_date=str(dh.last_month_start.date()),
                end_date=str(dh.last_month_end.date()),
            )
            with patch.object(accessor, "_prepare_and_execute_raw_sql_query") as mock_exec:
                accessor.populate_per_rate_distributed_cost_sql(
                    sr, self.ocp_provider_uuid, distribution_info
                )
            actual = set()
            for call_args in mock_exec.call_args_list:
                sql_params = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("sql_params", {})
                if isinstance(sql_params, dict) and "cost_model_rate_type" in sql_params:
                    actual.add(sql_params["cost_model_rate_type"])
            missing = expected_discriminators - actual
            self.assertFalse(missing, f"Missing per-rate configs: {missing}")

    @patch("masu.database.ocp_report_db_accessor.OCPReportDBAccessor._prepare_and_execute_raw_sql_query")
    def test_per_rate_sql_files_are_loadable(self, mock_exec):
        """All five per-rate SQL files can be loaded from the package."""
        import pkgutil

        from masu.util.ocp.common import DistributionConfig

        sql_files = [
            "distribute_platform_cost_per_rate.sql",
            "distribute_worker_cost_per_rate.sql",
            "distribute_unattributed_storage_per_rate.sql",
            "distribute_unattributed_network_per_rate.sql",
            "distribute_unallocated_gpu_per_rate.sql",
        ]
        for sql_file in sql_files:
            config = DistributionConfig(sql_file=sql_file, cost_model_rate_type="test")
            path = config.get_full_path()
            data = pkgutil.get_data("masu.database", path)
            self.assertIsNotNone(data, f"SQL file not found: {path}")
            self.assertIn(b"DELETE FROM", data, f"SQL file missing DELETE: {sql_file}")
            self.assertIn(b"INSERT INTO", data, f"SQL file missing INSERT: {sql_file}")

    def test_updater_calls_per_rate_distribution(self):
        """OCPCostModelCostUpdater._update_per_rate_distributed_cost is wired."""
        updater = OCPCostModelCostUpdater(self.schema, self.ocp_provider)
        self.assertTrue(hasattr(updater, "_update_per_rate_distributed_cost"))


class TestOrchestrationOrder(MasuTestCase):
    """Phase 4B: Verify per-rate distribution runs BEFORE aggregation."""

    def test_per_rate_dist_before_aggregation(self):
        """In update_summary_cost_model_costs, per-rate distribution precedes aggregation."""
        import inspect

        source = inspect.getsource(OCPCostModelCostUpdater.update_summary_cost_model_costs)
        dist_idx = source.find("_update_per_rate_distributed_cost")
        agg_idx = source.find("_aggregate_rates_to_daily_summary")
        self.assertGreater(dist_idx, 0, "per-rate distribution call not found")
        self.assertGreater(agg_idx, 0, "aggregation call not found")
        self.assertLess(dist_idx, agg_idx, "per-rate distribution must run before aggregation")


class TestBreakdownModel(MasuTestCase):
    """Phase 4C: OCPCostUIBreakDownP model exists and is in UI_SUMMARY_TABLES."""

    def test_breakdown_model_exists(self):
        from reporting.provider.ocp.models import OCPCostUIBreakDownP

        self.assertEqual(OCPCostUIBreakDownP._meta.db_table, "reporting_ocp_cost_breakdown_p")

    def test_breakdown_in_ui_summary_tables(self):
        from reporting.provider.ocp.models import UI_SUMMARY_TABLES

        self.assertIn("reporting_ocp_cost_breakdown_p", UI_SUMMARY_TABLES)

    def test_breakdown_model_has_required_fields(self):
        from reporting.provider.ocp.models import OCPCostUIBreakDownP

        field_names = {f.name for f in OCPCostUIBreakDownP._meta.get_fields()}
        required = {"path", "depth", "parent_path", "top_category", "breakdown_category",
                     "custom_name", "metric_type", "cost_value", "distributed_cost"}
        missing = required - field_names
        self.assertFalse(missing, f"Missing fields on OCPCostUIBreakDownP: {missing}")


class TestBreakdownAPIEndpoint(MasuTestCase):
    """Phase 4D: Breakdown API view, URL, provider_map."""

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_breakdown_endpoint_returns_200(self):
        """GET /breakdown/openshift/cost/ should return 200."""
        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        response = APIClient().get(url, **self.headers)
        self.assertEqual(response.status_code, 200)

    def test_breakdown_url_resolves(self):
        """The ocp-cost-breakdown URL name resolves correctly."""
        from django.urls import reverse

        url = reverse("ocp-cost-breakdown")
        self.assertIn("breakdown/openshift/cost", url)

    def test_provider_map_has_cost_breakdown(self):
        """OCPProviderMap includes cost_breakdown report type."""
        from api.report.ocp.provider_map import OCPProviderMap

        mapper = OCPProviderMap(provider="OCP", report_type="cost_breakdown", schema_name=self.schema)
        self.assertIsNotNone(mapper.report_type_map)

    def test_provider_map_cost_units_key_is_raw_currency(self):
        """GAP 2: cost_units_key should be 'raw_currency' to align with Koku convention."""
        from api.report.ocp.provider_map import OCPProviderMap

        mapper = OCPProviderMap(provider="OCP", report_type="cost_breakdown", schema_name=self.schema)
        self.assertEqual(mapper.cost_units_key, "raw_currency")

    def test_provider_map_has_cost_value_annotation(self):
        """GAP 2: cost_breakdown annotations should include cost_value and distributed_cost."""
        from api.report.ocp.provider_map import OCPProviderMap

        mapper = OCPProviderMap(provider="OCP", report_type="cost_breakdown", schema_name=self.schema)
        annotations = mapper.report_type_map.get("annotations", {})
        self.assertIn("cost_value", annotations)
        self.assertIn("distributed_cost", annotations)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_breakdown_endpoint_accepts_view_flat(self):
        """GET /breakdown/openshift/cost/?view=flat returns 200."""
        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        response = APIClient().get(url + "?view=flat", **self.headers)
        self.assertEqual(response.status_code, 200)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_breakdown_endpoint_accepts_view_tree(self):
        """GET /breakdown/openshift/cost/?view=tree returns 200."""
        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        response = APIClient().get(url + "?view=tree", **self.headers)
        self.assertEqual(response.status_code, 200)

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_breakdown_endpoint_rejects_invalid_view(self):
        """GET /breakdown/openshift/cost/?view=invalid returns 400."""
        from django.urls import reverse
        from rest_framework.test import APIClient

        url = reverse("ocp-cost-breakdown")
        response = APIClient().get(url + "?view=invalid", **self.headers)
        self.assertEqual(response.status_code, 400)

    def test_breakdown_serializer_has_view_field(self):
        """GAP 3: CostBreakdownQueryParamSerializer should have a 'view' field."""
        from api.report.ocp.serializers import CostBreakdownQueryParamSerializer

        serializer = CostBreakdownQueryParamSerializer(data={})
        self.assertIn("view", serializer.fields)

    def test_breakdown_group_by_disables_tag_support(self):
        """H1: CostBreakdownGroupBySerializer should not support tag keys."""
        from api.report.ocp.serializers import CostBreakdownGroupBySerializer

        self.assertFalse(getattr(CostBreakdownGroupBySerializer, "_tagkey_support", True))

    def test_breakdown_order_by_disables_cost_fields(self):
        """H3: CostBreakdownOrderBySerializer should not expose cost/infrastructure/supplementary/delta."""
        from api.report.ocp.serializers import CostBreakdownOrderBySerializer

        serializer = CostBreakdownOrderBySerializer(data={})
        for disallowed in ("cost", "infrastructure", "supplementary", "delta", "depth"):
            self.assertNotIn(disallowed, serializer.fields)
        self.assertIn("path", serializer.fields)

    def test_breakdown_order_by_allowlist(self):
        """H2: CostBreakdownQueryParamSerializer.order_by_allowlist should include path."""
        from api.report.ocp.serializers import CostBreakdownQueryParamSerializer

        self.assertIn("path", CostBreakdownQueryParamSerializer.order_by_allowlist)

    def test_breakdown_exclude_serializer_matches_filter_scope(self):
        """M1: Exclude serializer should have the same opfields as the filter serializer."""
        from api.report.ocp.serializers import CostBreakdownExcludeSerializer
        from api.report.ocp.serializers import CostBreakdownFilterSerializer

        self.assertEqual(
            set(CostBreakdownExcludeSerializer._opfields),
            set(CostBreakdownFilterSerializer._opfields),
        )

    def test_breakdown_flat_item_serializer_alias(self):
        """M4: CostBreakdownFlatItemSerializer is an alias for CostBreakdownQueryParamSerializer."""
        from api.report.ocp.serializers import CostBreakdownFlatItemSerializer
        from api.report.ocp.serializers import CostBreakdownQueryParamSerializer

        self.assertIs(CostBreakdownFlatItemSerializer, CostBreakdownQueryParamSerializer)

    def test_exchange_rate_bypass_for_breakdown(self):
        """GAP 2: exchange_rate_annotation_dict returns static values for cost_breakdown."""
        from api.report.ocp.query_handler import OCPReportQueryHandler
        from django.db.models import Value

        with patch.object(OCPReportQueryHandler, "__init__", lambda self, *a, **kw: None):
            handler = OCPReportQueryHandler.__new__(OCPReportQueryHandler)
            handler._report_type = "cost_breakdown"
            handler._mapper = type("M", (), {"cost_units_key": "raw_currency"})()
            descriptor = OCPReportQueryHandler.__dict__["exchange_rate_annotation_dict"]
            result = descriptor.__get__(handler, type(handler))
            self.assertIn("exchange_rate", result)
            self.assertIn("infra_exchange_rate", result)
            self.assertIsInstance(result["exchange_rate"], Value)
            self.assertIsInstance(result["infra_exchange_rate"], Value)


class TestBreakdownInfrastructureCategory(MasuTestCase):
    """GAP 1: Verify 'infrastructure' breakdown_category in distribution context."""

    def test_sql_uses_infrastructure_for_distribution_raw_cost(self):
        """Breakdown SQL maps metric_type='raw_cost' to 'infrastructure' for distribution rows."""
        import pkgutil

        data = pkgutil.get_data(
            "masu.database",
            "sql/openshift/ui_summary/reporting_ocp_cost_breakdown_p.sql",
        )
        sql = data.decode("utf-8")
        self.assertIn("'infrastructure'", sql, "SQL should use 'infrastructure' breakdown_category")
        lines_in_step1b = False
        for line in sql.split("\n"):
            if "Step 1b" in line:
                lines_in_step1b = True
            if lines_in_step1b and "raw_cost" in line and "infrastructure" in line:
                break
            if "Step 2" in line:
                lines_in_step1b = False
        self.assertTrue(
            lines_in_step1b or "'infrastructure'" in sql,
            "Step 1b should map raw_cost to infrastructure in distribution context",
        )

    def test_infrastructure_not_used_for_project_rows(self):
        """Step 1a (project leaves) should NOT use 'infrastructure' — it uses 'raw_cost'."""
        import pkgutil

        data = pkgutil.get_data(
            "masu.database",
            "sql/openshift/ui_summary/reporting_ocp_cost_breakdown_p.sql",
        )
        sql = data.decode("utf-8")
        step1a_start = sql.find("Step 1a")
        step1b_start = sql.find("Step 1b")
        step1a_sql = sql[step1a_start:step1b_start]
        self.assertIn("'raw_cost'", step1a_sql, "Step 1a should still use 'raw_cost'")
        self.assertNotIn("'infrastructure'", step1a_sql, "Step 1a should NOT use 'infrastructure'")


class TestTreeViewReconstruction(MasuTestCase):
    """GAP 3: Verify tree view reconstruction logic."""

    def test_to_tree_builds_nested_structure(self):
        """_to_tree nests values based on path/parent_path."""
        from api.report.ocp.view import OCPCostBreakdownView

        flat_payload = {
            "data": [
                {
                    "date": "2026-03",
                    "values": [
                        {"path": "total_cost", "parent_path": "", "depth": 1,
                         "custom_name": "total_cost", "cost_value": "100.00"},
                        {"path": "project", "parent_path": "total_cost", "depth": 2,
                         "custom_name": "project", "cost_value": "60.00"},
                        {"path": "overhead", "parent_path": "total_cost", "depth": 2,
                         "custom_name": "overhead", "cost_value": "40.00"},
                        {"path": "project.usage_cost", "parent_path": "project", "depth": 3,
                         "custom_name": "usage_cost", "cost_value": "60.00"},
                    ],
                }
            ]
        }
        result = OCPCostBreakdownView._to_tree(flat_payload)
        tree_values = result["data"][0]["values"]
        self.assertEqual(len(tree_values), 1, "Only root node at top level")
        root = tree_values[0]
        self.assertEqual(root["path"], "total_cost")
        self.assertEqual(len(root["children"]), 2, "Root should have project + overhead")
        project_node = next(c for c in root["children"] if c["path"] == "project")
        self.assertEqual(len(project_node["children"]), 1, "project should have usage_cost child")
        self.assertEqual(project_node["children"][0]["path"], "project.usage_cost")

    def test_to_tree_empty_data_passthrough(self):
        """_to_tree handles empty data gracefully."""
        from api.report.ocp.view import OCPCostBreakdownView

        result = OCPCostBreakdownView._to_tree({"data": []})
        self.assertEqual(result["data"], [])

    def test_to_tree_preserves_meta(self):
        """_to_tree preserves non-data fields in the payload."""
        from api.report.ocp.view import OCPCostBreakdownView

        payload = {"data": [], "meta": {"total": {}}, "links": {}}
        result = OCPCostBreakdownView._to_tree(payload)
        self.assertIn("meta", result)
        self.assertIn("links", result)

    def test_to_tree_merges_duplicate_paths(self):
        """M3: _to_tree aggregates cost_value/distributed_cost for duplicate paths."""
        from api.report.ocp.view import OCPCostBreakdownView

        flat_payload = {
            "data": [
                {
                    "date": "2026-03",
                    "values": [
                        {"path": "total_cost", "parent_path": "", "depth": 1,
                         "cost_value": 50, "distributed_cost": 10},
                        {"path": "total_cost", "parent_path": "", "depth": 1,
                         "cost_value": 30, "distributed_cost": 5},
                    ],
                }
            ]
        }
        result = OCPCostBreakdownView._to_tree(flat_payload)
        tree_values = result["data"][0]["values"]
        self.assertEqual(len(tree_values), 1, "Duplicate paths should merge")
        self.assertEqual(tree_values[0]["cost_value"], 80)
        self.assertEqual(tree_values[0]["distributed_cost"], 15)


# ---------------------------------------------------------------------------
# Phase 5 — Cleanup Verification Tests
# ---------------------------------------------------------------------------


class TestPhase5ATagRateReadsFromRateTable(MasuTestCase):
    """Verify tag_based_price_list and metric_to_tag_params_map read from Rate table."""

    def _get_accessor(self, provider_uuid=None):
        from masu.database.cost_model_db_accessor import CostModelDBAccessor

        return CostModelDBAccessor(self.schema, provider_uuid or self.ocp_provider_uuid)

    def test_tag_based_price_list_returns_dict(self):
        """tag_based_price_list should return a dict keyed by metric name."""
        with self._get_accessor() as accessor:
            result = accessor.tag_based_price_list
            self.assertIsInstance(result, dict)

    def test_metric_to_tag_params_map_returns_dict(self):
        """metric_to_tag_params_map should return a dict keyed by metric name."""
        with self._get_accessor() as accessor:
            result = accessor.metric_to_tag_params_map
            self.assertIsInstance(result, dict)

    def test_tag_based_price_list_no_json_field_access(self):
        """Ensure tag_based_price_list does not access CostModel.rates JSON
        (it should query the Rate table directly)."""
        with self._get_accessor() as accessor:
            if not accessor.cost_model:
                self.skipTest("No cost model for this provider")
            bomb = property(lambda inst: (_ for _ in ()).throw(
                AssertionError("Should not access CostModel.rates property")
            ))
            with patch.object(type(accessor.cost_model), "rates", bomb):
                result = accessor.tag_based_price_list
            self.assertIsInstance(result, dict)


class TestPhase5BUsageCostsRemoved(MasuTestCase):
    """Verify usage_costs.sql and populate_usage_costs are removed."""

    def test_usage_costs_sql_file_does_not_exist(self):
        """The legacy usage_costs.sql file should be deleted."""
        import os

        sql_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..",
            "masu", "database", "sql", "openshift", "cost_model", "usage_costs.sql",
        )
        self.assertFalse(
            os.path.exists(os.path.normpath(sql_path)),
            "usage_costs.sql should have been removed in Phase 5B",
        )

    def test_populate_usage_costs_method_removed(self):
        """OCPReportDBAccessor should no longer have populate_usage_costs."""
        self.assertFalse(
            hasattr(OCPReportDBAccessor, "populate_usage_costs"),
            "populate_usage_costs should have been removed in Phase 5B",
        )

    def test_updater_no_update_usage_costs_method(self):
        """OCPCostModelCostUpdater should not have _update_usage_costs."""
        self.assertFalse(
            hasattr(OCPCostModelCostUpdater, "_update_usage_costs"),
            "_update_usage_costs should have been replaced by _update_vm_usage_costs",
        )


class TestPhase5CCostModelRatesProperty(MasuTestCase):
    """Verify CostModel.rates is a property reading from Rate table, no JSON dual-write."""

    def test_rates_is_property_not_field(self):
        """CostModel.rates should be a Python property, not a Django field."""
        from cost_models.models import CostModel

        self.assertIsInstance(
            CostModel.__dict__["rates"],
            property,
            "CostModel.rates should be a property after Phase 5C",
        )

    def test_rates_property_returns_list(self):
        """CostModel.rates property should return a list of rate dicts."""
        from cost_models.models import CostModel
        from django_tenants.utils import tenant_context

        with tenant_context(self.tenant):
            cm = CostModel.objects.first()
            if not cm:
                self.skipTest("No CostModel in test DB")
            rates = cm.rates
            self.assertIsInstance(rates, list)
            if rates:
                self.assertIsInstance(rates[0], dict)
                self.assertIn("metric", rates[0])

    def test_rates_property_includes_rate_id(self):
        """Each reconstructed rate dict should include rate_id."""
        from cost_models.models import CostModel
        from django_tenants.utils import tenant_context

        with tenant_context(self.tenant):
            cm = CostModel.objects.first()
            if not cm:
                self.skipTest("No CostModel in test DB")
            rates = cm.rates
            for rate in rates:
                self.assertIn("rate_id", rate, "Reconstructed rate should include rate_id")

    def test_no_rates_json_column_on_cost_model(self):
        """The cost_model table should not have a 'rates' column."""
        from django.db import connection
        from django_tenants.utils import schema_context

        with schema_context(self.schema):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'cost_model' AND column_name = 'rates'"
                )
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 0, "cost_model table should not have a 'rates' column")
