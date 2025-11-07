-- Migration: Fix value_type mismatches in metric_series
-- Date: 2025-11-07
-- Reason: When value_type column was added, default was 'float', but some metrics
--         are actually stored as integers. This causes queries to fail.

-- Fix all series where value_type doesn't match actual data storage
UPDATE metric_series
SET value_type = 'int'
WHERE id IN (
  SELECT DISTINCT series_id
  FROM metric_points_int
) AND value_type != 'int';

UPDATE metric_series
SET value_type = 'float'
WHERE id IN (
  SELECT DISTINCT series_id
  FROM metric_points_float
) AND value_type != 'float';

-- Verify the fix
SELECT 'After migration:' as status;
SELECT
  value_type,
  COUNT(*) as series_count,
  SUM(CASE
    WHEN value_type = 'int' THEN (SELECT COUNT(*) FROM metric_points_int mpi WHERE mpi.series_id = metric_series.id)
    WHEN value_type = 'float' THEN (SELECT COUNT(*) FROM metric_points_float mpf WHERE mpf.series_id = metric_series.id)
  END) as total_data_points
FROM metric_series
GROUP BY value_type;
