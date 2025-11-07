-- Migration: Migrate all metrics to float-only storage
-- Date: 2025-11-07
-- Reason: Architecture decision - all metrics should be stored as float in DB,
--         with conversion to int happening on UI/dashboard if needed.
--         This reverts the incorrect migration 002.

-- First, migrate all data from metric_points_int to metric_points_float
INSERT INTO metric_points_float (series_id, timestamp, value)
SELECT series_id, timestamp, CAST(value AS REAL)
FROM metric_points_int
WHERE NOT EXISTS (
    SELECT 1 FROM metric_points_float mpf
    WHERE mpf.series_id = metric_points_int.series_id
    AND mpf.timestamp = metric_points_int.timestamp
);

-- Now update all value_types to 'float'
UPDATE metric_series SET value_type = 'float';

-- Verify the migration
SELECT 'After migration:' as status;
SELECT
    value_type,
    COUNT(*) as series_count
FROM metric_series
GROUP BY value_type;

SELECT 'Data points in float table:' as info, COUNT(*) as count FROM metric_points_float;
SELECT 'Data points in int table (should be cleared):' as info, COUNT(*) as count FROM metric_points_int;
