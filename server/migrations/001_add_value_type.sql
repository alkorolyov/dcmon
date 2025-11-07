-- Migration: Add value_type column to metric_series
-- Date: 2025-11-07
-- Reason: Pre-refactor code expects value_type column to determine int vs float storage

ALTER TABLE metric_series ADD COLUMN value_type VARCHAR(10) DEFAULT 'float';

-- Update existing rows to set value_type based on actual data
-- This query attempts to infer the type by checking which table has data points
UPDATE metric_series
SET value_type = CASE
    WHEN EXISTS (
        SELECT 1 FROM metric_points_int
        WHERE metric_points_int.series_id = metric_series.id
        LIMIT 1
    ) THEN 'int'
    ELSE 'float'
END;
