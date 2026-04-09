#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M7: Update audit trigger to capture cost_model_context from CostModelMap.

Adds cost_model_context column to cost_model_audit and updates the trigger
function to JOIN CostModelMap to capture context assignments. Also adds a
lightweight trigger on cost_model_map for context-assignment changes.
"""
from django.db import migrations


AUDIT_COLUMNS = (
    "operation, audit_timestamp, provider_uuids, "
    "uuid, name, description, source_type, created_timestamp, updated_timestamp, "
    "rates, markup, distribution, distribution_info, currency, cost_model_context"
)

FORWARD_SQL = f"""
-- Add cost_model_context column to audit table
ALTER TABLE cost_model_audit
    ADD COLUMN IF NOT EXISTS cost_model_context VARCHAR(50);

-- Replace trigger function to capture context (explicit column names)
CREATE OR REPLACE FUNCTION process_cost_model_audit()
RETURNS TRIGGER AS $$
DECLARE
    context_val VARCHAR(50);
BEGIN
    -- Capture context name from CostModelMap for the cost model being modified
    SELECT cmc.name INTO context_val
    FROM cost_model_map cmm
    INNER JOIN cost_model_context cmc ON cmm.cost_model_context = cmc.uuid
    WHERE cmm.cost_model_id = COALESCE(NEW.uuid, OLD.uuid)
    LIMIT 1;

    IF (TG_OP = 'DELETE') THEN
        INSERT INTO cost_model_audit ({AUDIT_COLUMNS})
        SELECT 'DELETE', now(),
            ARRAY(SELECT provider_uuid FROM cost_model_map WHERE cost_model_id = OLD.uuid),
            OLD.uuid, OLD.name, OLD.description, OLD.source_type,
            OLD.created_timestamp, OLD.updated_timestamp,
            OLD.rates, OLD.markup, OLD.distribution, OLD.distribution_info,
            OLD.currency, context_val;
        RETURN OLD;
    ELSIF (TG_OP = 'UPDATE') THEN
        INSERT INTO cost_model_audit ({AUDIT_COLUMNS})
        SELECT 'UPDATE', now(),
            ARRAY(SELECT provider_uuid FROM cost_model_map WHERE cost_model_id = NEW.uuid),
            NEW.uuid, NEW.name, NEW.description, NEW.source_type,
            NEW.created_timestamp, NEW.updated_timestamp,
            NEW.rates, NEW.markup, NEW.distribution, NEW.distribution_info,
            NEW.currency, context_val;
        RETURN NEW;
    ELSIF (TG_OP = 'INSERT') THEN
        INSERT INTO cost_model_audit ({AUDIT_COLUMNS})
        SELECT 'INSERT', now(),
            ARRAY(SELECT provider_uuid FROM cost_model_map WHERE cost_model_id = NEW.uuid),
            NEW.uuid, NEW.name, NEW.description, NEW.source_type,
            NEW.created_timestamp, NEW.updated_timestamp,
            NEW.rates, NEW.markup, NEW.distribution, NEW.distribution_info,
            NEW.currency, context_val;
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Lightweight trigger on cost_model_map for context assignment changes
CREATE OR REPLACE FUNCTION process_cost_model_map_audit()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        INSERT INTO cost_model_audit ({AUDIT_COLUMNS})
        SELECT 'DELETE', now(), ARRAY[OLD.provider_uuid],
            cm.uuid, cm.name, cm.description, cm.source_type, cm.created_timestamp,
            cm.updated_timestamp, cm.rates, cm.markup, cm.distribution,
            cm.distribution_info, cm.currency,
            (SELECT cmc.name FROM cost_model_context cmc WHERE cmc.uuid = OLD.cost_model_context)
        FROM cost_model cm WHERE cm.uuid = OLD.cost_model_id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT') THEN
        INSERT INTO cost_model_audit ({AUDIT_COLUMNS})
        SELECT 'INSERT', now(), ARRAY[NEW.provider_uuid],
            cm.uuid, cm.name, cm.description, cm.source_type, cm.created_timestamp,
            cm.updated_timestamp, cm.rates, cm.markup, cm.distribution,
            cm.distribution_info, cm.currency,
            (SELECT cmc.name FROM cost_model_context cmc WHERE cmc.uuid = NEW.cost_model_context)
        FROM cost_model cm WHERE cm.uuid = NEW.cost_model_id;
        RETURN NEW;
    ELSIF (TG_OP = 'UPDATE') THEN
        INSERT INTO cost_model_audit ({AUDIT_COLUMNS})
        SELECT 'UPDATE', now(), ARRAY[NEW.provider_uuid],
            cm.uuid, cm.name, cm.description, cm.source_type, cm.created_timestamp,
            cm.updated_timestamp, cm.rates, cm.markup, cm.distribution,
            cm.distribution_info, cm.currency,
            (SELECT cmc.name FROM cost_model_context cmc WHERE cmc.uuid = NEW.cost_model_context)
        FROM cost_model cm WHERE cm.uuid = NEW.cost_model_id;
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cost_model_map_audit ON cost_model_map;
CREATE TRIGGER cost_model_map_audit
AFTER INSERT OR UPDATE OR DELETE ON cost_model_map
FOR EACH ROW EXECUTE FUNCTION process_cost_model_map_audit();
"""

REVERSE_SQL = f"""
-- Remove the cost_model_map trigger
DROP TRIGGER IF EXISTS cost_model_map_audit ON cost_model_map;
DROP FUNCTION IF EXISTS process_cost_model_map_audit();

-- Remove cost_model_context column from audit table
ALTER TABLE cost_model_audit DROP COLUMN IF EXISTS cost_model_context;

-- Restore original trigger function (without context capture, explicit columns)
CREATE OR REPLACE FUNCTION process_cost_model_audit()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        INSERT INTO cost_model_audit (operation, audit_timestamp, provider_uuids,
            uuid, name, description, source_type, created_timestamp, updated_timestamp,
            rates, markup, distribution, distribution_info, currency)
        SELECT 'DELETE', now(),
            ARRAY(SELECT provider_uuid FROM cost_model_map WHERE cost_model_id = OLD.uuid),
            OLD.uuid, OLD.name, OLD.description, OLD.source_type,
            OLD.created_timestamp, OLD.updated_timestamp,
            OLD.rates, OLD.markup, OLD.distribution, OLD.distribution_info, OLD.currency;
        RETURN OLD;
    ELSIF (TG_OP = 'UPDATE') THEN
        INSERT INTO cost_model_audit (operation, audit_timestamp, provider_uuids,
            uuid, name, description, source_type, created_timestamp, updated_timestamp,
            rates, markup, distribution, distribution_info, currency)
        SELECT 'UPDATE', now(),
            ARRAY(SELECT provider_uuid FROM cost_model_map WHERE cost_model_id = NEW.uuid),
            NEW.uuid, NEW.name, NEW.description, NEW.source_type,
            NEW.created_timestamp, NEW.updated_timestamp,
            NEW.rates, NEW.markup, NEW.distribution, NEW.distribution_info, NEW.currency;
        RETURN NEW;
    ELSIF (TG_OP = 'INSERT') THEN
        INSERT INTO cost_model_audit (operation, audit_timestamp, provider_uuids,
            uuid, name, description, source_type, created_timestamp, updated_timestamp,
            rates, markup, distribution, distribution_info, currency)
        SELECT 'INSERT', now(),
            ARRAY(SELECT provider_uuid FROM cost_model_map WHERE cost_model_id = NEW.uuid),
            NEW.uuid, NEW.name, NEW.description, NEW.source_type,
            NEW.created_timestamp, NEW.updated_timestamp,
            NEW.rates, NEW.markup, NEW.distribution, NEW.distribution_info, NEW.currency;
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("cost_models", "0015_populate_default_contexts"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
