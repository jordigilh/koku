#
# Copyright 2021 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Database accessor for OCP rate data."""
import logging
from collections import defaultdict

from django.db import transaction

from api.metrics import constants as metric_constants
from cost_models.models import CostModel
from cost_models.models import Rate

LOG = logging.getLogger(__name__)


class CostModelDBAccessor:
    """Class to interact with customer reporting tables."""

    def __init__(self, schema, provider_uuid):
        """Establish the database connection.

        Args:
            schema (str): The customer schema to associate with
            provider_uuid (str): Provider uuid

        """
        self.schema = schema
        self.provider_uuid = provider_uuid
        self._cost_model = None

    def __enter__(self):
        """Enter context manager."""
        connection = transaction.get_connection()
        connection.set_schema(self.schema)
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        """Context manager reset schema to public and exit."""
        connection = transaction.get_connection()
        connection.set_schema_to_public()

    @property
    def cost_model(self):
        """Return the cost model database object."""
        if self._cost_model is None:
            self._cost_model = CostModel.objects.filter(costmodelmap__provider_uuid=self.provider_uuid).first()
        return self._cost_model

    @property
    def price_list(self):
        """Return the tiered (non-tag) rates defined on this cost model.

        Reads from the Rate table (via PriceListCostModelMap → PriceList → Rate).
        Output dict matches the legacy JSON-based format so all downstream
        properties (infrastructure_rates, supplementary_rates, etc.) work unchanged.

        Tag rates (Rate rows with a non-empty tag_key) are skipped here;
        they are handled by tag_based_price_list (also Rate-table-backed).
        """
        if not self.cost_model:
            return {}
        rate_rows = Rate.objects.filter(
            price_list__cost_model_maps__cost_model=self.cost_model
        ).only("metric", "cost_type", "default_rate", "description", "tag_key")

        metric_rate_map = {}
        for rate in rate_rows:
            if rate.tag_key:
                continue

            metric_name = rate.metric
            cost_type = rate.cost_type
            value = float(rate.default_rate) if rate.default_rate is not None else 0.0

            if metric_name in metric_rate_map:
                existing = metric_rate_map[metric_name]
                tiered = existing["tiered_rates"]
                if cost_type in tiered:
                    tiered[cost_type][0]["value"] += value
                else:
                    tiered[cost_type] = [{"value": value, "unit": "USD"}]
            else:
                metric_rate_map[metric_name] = {
                    "metric": {"name": metric_name},
                    "cost_type": cost_type,
                    "description": rate.description,
                    "tiered_rates": {
                        cost_type: [{"value": value, "unit": "USD"}],
                    },
                }

        return metric_rate_map

    @property
    def infrastructure_rates(self):
        """Return the rates designated as infrastructure cost."""
        return {
            key: value.get("tiered_rates").get(metric_constants.INFRASTRUCTURE_COST_TYPE)[0].get("value")
            for key, value in self.price_list.items()
            if metric_constants.INFRASTRUCTURE_COST_TYPE in value.get("tiered_rates").keys()
        }

    @property
    def supplementary_rates(self):
        """Return the rates designated as supplementary cost."""
        return {
            key: value.get("tiered_rates").get(metric_constants.SUPPLEMENTARY_COST_TYPE)[0].get("value")
            for key, value in self.price_list.items()
            if metric_constants.SUPPLEMENTARY_COST_TYPE in value.get("tiered_rates").keys()
        }

    @property
    def markup(self):
        if self.cost_model:
            return self.cost_model.markup
        return {}

    @property
    def distribution_info(self):
        """Returns distribution info field in the cost model."""
        if self.cost_model:
            return self.cost_model.distribution_info
        return {}

    def get_rates(self, value):
        """Get the rates."""
        return self.price_list.get(value)

    @property
    def metric_to_tag_params_map(self):
        """Returns the tag rate parameters, read from the Rate table."""
        if not self.cost_model:
            return {}
        tag_rates = Rate.objects.filter(
            price_list__cost_model_maps__cost_model=self.cost_model
        ).exclude(tag_key="").only("metric", "cost_type", "tag_key", "tag_values")

        metric_map = defaultdict(list)
        for rate in tag_rates:
            tag_rate_param = {
                "rate_type": rate.cost_type,
                "tag_key": rate.tag_key,
            }
            kv_pairs_rates = {}
            for tv in rate.tag_values:
                if tv.get("default"):
                    tag_rate_param["default_rate"] = float(tv.get("value", 0))
                else:
                    kv_pairs_rates[tv.get("tag_value")] = float(tv.get("value", 0))
            if kv_pairs_rates:
                tag_rate_param["value_rates"] = kv_pairs_rates
            metric_map[rate.metric].append(tag_rate_param)
        return metric_map

    @property
    def tag_based_price_list(self):
        """Return the rates defined on this cost model that come from tag based rates.

        Reads from the Rate table instead of CostModel.rates JSON.
        Output format matches the legacy JSON-based structure for backward
        compatibility with downstream properties (tag_infrastructure_rates, etc.).
        """
        if not self.cost_model:
            return {}
        tag_rate_rows = Rate.objects.filter(
            price_list__cost_model_maps__cost_model=self.cost_model
        ).exclude(tag_key="").only("metric", "cost_type", "tag_key", "tag_values")

        metric_rate_map = {}
        for rate in tag_rate_rows:
            metric_name = rate.metric
            metric_cost_type = rate.cost_type
            tag_rate_dict = {}
            default_rate = 0
            for tv in rate.tag_values:
                rate_value = float(tv.get("value", 0))
                unit = tv.get("unit", "USD")
                default = tv.get("default", False)
                if default:
                    default_rate = rate_value
                tag_value = tv.get("tag_value", "")
                tag_rate_dict[tag_value] = {"unit": unit, "value": rate_value, "default": default}
            tag_entry = {"tag_key": rate.tag_key, "tag_values": tag_rate_dict, "tag_key_default": default_rate}

            if metric_name in metric_rate_map:
                existing = metric_rate_map[metric_name]
                cost_dict = existing.get("tag_rates", {})
                if metric_cost_type in cost_dict:
                    cost_dict[metric_cost_type].append(tag_entry)
                else:
                    cost_dict[metric_cost_type] = [tag_entry]
                existing["tag_rates"] = cost_dict
            else:
                metric_rate_map[metric_name] = {
                    "metric": {"name": metric_name},
                    "cost_type": metric_cost_type,
                    "tag_rates": {metric_cost_type: [tag_entry]},
                }
        return metric_rate_map

    @property
    def tag_infrastructure_rates(self):
        """
        Return the rates designated as infrastructure cost from tag based rates.
        The format for this is
        {
            metric: {
                tag_key: {
                    tag_value: value_rate, tag_value_2: value_rate
                }
            }
        }
        This is in order to keep tag values associated with their key
        """
        results_dict = {}
        for key, value in self.tag_based_price_list.items():
            if metric_constants.INFRASTRUCTURE_COST_TYPE in value.get("tag_rates").keys():
                tag_dict = {}
                for tag in value.get("tag_rates").get(metric_constants.INFRASTRUCTURE_COST_TYPE):
                    tag_key = tag.get("tag_key")
                    tag_values = {}
                    for value_key, val in tag.get("tag_values").items():
                        tag_values[value_key] = val.get("value")
                    tag_dict[tag_key] = tag_values
                    results_dict[key] = tag_dict
        return results_dict

    @property
    def tag_default_infrastructure_rates(self):
        """
        Return the default infrastructure rates for each key that has a defined rate
        It is returned in the format
        {
            metric: {
                key: {
                    'default_value': <value>, 'defined_keys': [values, to, be, ignored]
                }
            }
        }
        Where the keys to be ignored is a list of tag values that have defined rates
        """
        results_dict = {}
        for key, value in self.tag_based_price_list.items():
            if metric_constants.INFRASTRUCTURE_COST_TYPE in value.get("tag_rates").keys():
                tag_dict = {}
                for tag in value.get("tag_rates").get(metric_constants.INFRASTRUCTURE_COST_TYPE):
                    tag_key = tag.get("tag_key")
                    tag_keys_to_ignore = list(tag.get("tag_values").keys())
                    default_value = tag.get("tag_key_default")
                    # NOTE: defined keys is actually list of values that have a rate associated with them.
                    tag_dict[tag_key] = {"default_value": default_value, "defined_keys": tag_keys_to_ignore}
                    results_dict[key] = tag_dict
        return results_dict

    @property
    def tag_supplementary_rates(self):
        """
        Return the rates designated as supplementary cost from tag based rates.
        The format for this is
        {
            metric: {
                tag_key: {
                    tag_value: value_rate, tag_value_2: value_rate
                }
            }
        }
        This is in order to keep tag values associated with their key
        """
        results_dict = {}
        for key, value in self.tag_based_price_list.items():
            if metric_constants.SUPPLEMENTARY_COST_TYPE in value.get("tag_rates").keys():
                tag_dict = {}
                for tag in value.get("tag_rates").get(metric_constants.SUPPLEMENTARY_COST_TYPE):
                    tag_key = tag.get("tag_key")
                    tag_values = {}
                    for value_key, val in tag.get("tag_values").items():
                        tag_values[value_key] = val.get("value")
                    tag_dict[tag_key] = tag_values
                    results_dict[key] = tag_dict
        return results_dict

    @property
    def tag_default_supplementary_rates(self):
        """
        Return the default supplementary rates for each key that has a defined rate
        It is returned in the format
        {
            metric: {
                key: {
                    'default_value': <value>, 'defined_keys': [values, to, be, ignored]
                }
            }
        }
        Where the keys to be ignored is a list of tag values that have defined rates
        """
        results_dict = {}
        for key, value in self.tag_based_price_list.items():
            if metric_constants.SUPPLEMENTARY_COST_TYPE in value.get("tag_rates").keys():
                tag_dict = {}
                for tag in value.get("tag_rates").get(metric_constants.SUPPLEMENTARY_COST_TYPE):
                    tag_key = tag.get("tag_key")
                    tag_keys_to_ignore = list(tag.get("tag_values").keys())
                    default_value = tag.get("tag_key_default")
                    # Note: defined_keys is actually a list of tag values that have a specific rate
                    tag_dict[tag_key] = {"default_value": default_value, "defined_keys": tag_keys_to_ignore}
                    results_dict[key] = tag_dict
        return results_dict
