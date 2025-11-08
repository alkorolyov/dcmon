"""Unit tests for MetricQueryBuilder

Tests the data access layer in isolation.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from api.metric_queries import MetricQueryBuilder, CPU_SENSORS, VRM_SENSORS
from models import MetricSeries, Client, MetricPoints


class TestFilterSeriesByLabels:
    """Test label filtering functionality"""

    def test_filter_with_no_labels_returns_all(self, test_db, sample_metrics):
        """When no label filter is provided, all series should be returned"""
        base_query = MetricSeries.select()
        filtered = MetricQueryBuilder.filter_series_by_labels(base_query, None)

        result = list(filtered)
        assert len(result) == 3  # cpu, temp, vrm series

    def test_filter_with_single_label(self, test_db, sample_metrics):
        """Filter by single label should return matching series only"""
        base_query = MetricSeries.select()
        filtered = MetricQueryBuilder.filter_series_by_labels(
            base_query,
            [{"sensor": "CPU Temp"}]
        )

        result = list(filtered)
        assert len(result) == 1
        assert result[0].metric_name == "ipmi_temp_celsius"
        assert '"sensor":"CPU Temp"' in result[0].labels

    def test_filter_with_multiple_labels_uses_or_logic(self, test_db, sample_metrics):
        """Multiple label filters should use OR logic"""
        base_query = MetricSeries.select()
        filtered = MetricQueryBuilder.filter_series_by_labels(
            base_query,
            [{"sensor": "CPU Temp"}, {"sensor": "VRM Temp"}]
        )

        result = list(filtered)
        assert len(result) == 2
        sensors = ['"sensor":"CPU Temp"' in s.labels or '"sensor":"VRM Temp"' in s.labels
                   for s in result]
        assert all(sensors)

    def test_filter_with_nonexistent_label(self, test_db, sample_metrics):
        """Filtering by nonexistent label returns empty result"""
        base_query = MetricSeries.select()
        filtered = MetricQueryBuilder.filter_series_by_labels(
            base_query,
            [{"sensor": "Nonexistent"}]
        )

        result = list(filtered)
        assert len(result) == 0


class TestGetLatestMetricValue:
    """Test latest metric value retrieval"""

    def test_get_latest_without_aggregation(self, test_db, sample_metrics):
        """Get latest single value without aggregation"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="cpu_usage_percent",
            label_filters=None,
            aggregation=None
        )

        assert value is not None
        assert isinstance(value, float)
        # Should be the latest value (last point created)
        assert 55.0 <= value <= 60.0  # Last few values are in this range

    def test_get_latest_with_max_aggregation(self, test_db, sample_metrics):
        """Aggregate multiple series with max"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="ipmi_temp_celsius",
            label_filters=None,
            aggregation="max"
        )

        assert value is not None
        # Should be max of CPU temp and VRM temp at latest timestamp
        # CPU temp latest: 71, VRM temp latest: 59
        assert value == 71.0

    def test_get_latest_with_min_aggregation(self, test_db, sample_metrics):
        """Aggregate multiple series with min"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="ipmi_temp_celsius",
            label_filters=None,
            aggregation="min"
        )

        assert value is not None
        # Should be min of CPU temp and VRM temp
        assert value == 59.0  # VRM is cooler

    def test_get_latest_with_avg_aggregation(self, test_db, sample_metrics):
        """Aggregate multiple series with average"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="ipmi_temp_celsius",
            label_filters=None,
            aggregation="avg"
        )

        assert value is not None
        # Average of 71 and 59
        assert 64.0 <= value <= 66.0

    def test_get_latest_with_sum_aggregation(self, test_db, sample_metrics):
        """Aggregate multiple series with sum"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="ipmi_temp_celsius",
            label_filters=None,
            aggregation="sum"
        )

        assert value is not None
        # Sum of 71 + 59
        assert value == 130.0

    def test_get_latest_with_label_filter(self, test_db, sample_metrics):
        """Filter by label before getting value"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="ipmi_temp_celsius",
            label_filters=[{"sensor": "VRM Temp"}],
            aggregation=None
        )

        assert value is not None
        assert value == 59.0  # Only VRM temp

    def test_get_latest_nonexistent_metric_returns_none(self, test_db, sample_metrics):
        """Nonexistent metric should return None"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="nonexistent_metric",
            label_filters=None,
            aggregation=None
        )

        assert value is None

    def test_get_latest_nonexistent_client_returns_none(self, test_db, sample_metrics):
        """Nonexistent client should return None"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=99999,
            metric_name="cpu_usage_percent",
            label_filters=None,
            aggregation=None
        )

        assert value is None

    def test_get_latest_with_multiple_metric_names(self, test_db, sample_metrics):
        """Support list of metric names"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name=["cpu_usage_percent", "ipmi_temp_celsius"],
            label_filters=None,
            aggregation="max"
        )

        assert value is not None
        # Should aggregate across both metrics
        assert value == 71.0  # Max temp is highest


class TestGetRawTimeseries:
    """Test raw timeseries data retrieval"""

    def test_get_raw_timeseries_basic(self, test_db, sample_metrics):
        """Get raw timeseries without filtering"""
        start_time, end_time = sample_metrics['timestamp_range']

        df = MetricQueryBuilder.get_raw_timeseries(
            metric_name="cpu_usage_percent",
            start_time=start_time,
            end_time=end_time + 100,  # Extra buffer
            client_ids=[sample_metrics['client'].id],
            label_filters=None,
            active_only=False
        )

        assert not df.empty
        assert len(df) == 10  # We created 10 points
        # Check that required columns are present
        required_cols = ['timestamp', 'value', 'client_id', 'client_name']
        assert all(col in df.columns for col in required_cols)
        assert df['client_name'].iloc[0] == "test-server-01"

    def test_get_raw_timeseries_sorted_by_timestamp(self, test_db, sample_metrics):
        """Results should be sorted by timestamp"""
        start_time, end_time = sample_metrics['timestamp_range']

        df = MetricQueryBuilder.get_raw_timeseries(
            metric_name="cpu_usage_percent",
            start_time=start_time,
            end_time=end_time + 100,
            client_ids=[sample_metrics['client'].id],
            active_only=False
        )

        timestamps = df['timestamp'].tolist()
        assert timestamps == sorted(timestamps)  # Should be ascending

    def test_get_raw_timeseries_with_label_filter(self, test_db, sample_metrics):
        """Filter timeseries by labels"""
        start_time, end_time = sample_metrics['timestamp_range']

        df = MetricQueryBuilder.get_raw_timeseries(
            metric_name="ipmi_temp_celsius",
            start_time=start_time,
            end_time=end_time + 100,
            client_ids=[sample_metrics['client'].id],
            label_filters=[{"sensor": "CPU Temp"}],
            active_only=False
        )

        assert not df.empty
        assert len(df) == 10  # Only CPU temp points
        # All values should be from CPU temp series
        assert all(df['value'] >= 62)  # CPU temp starts at 62

    def test_get_raw_timeseries_multiple_metrics(self, test_db, sample_metrics):
        """Get raw data for multiple metric names"""
        start_time, end_time = sample_metrics['timestamp_range']

        df = MetricQueryBuilder.get_raw_timeseries(
            metric_name=["cpu_usage_percent", "ipmi_temp_celsius"],
            start_time=start_time,
            end_time=end_time + 100,
            client_ids=[sample_metrics['client'].id],
            active_only=False
        )

        assert not df.empty
        # Should have cpu (10) + temp (10) + vrm (10) = 30 points
        assert len(df) == 30

    def test_get_raw_timeseries_empty_result(self, test_db, sample_metrics):
        """Query with no matching data returns empty DataFrame"""
        df = MetricQueryBuilder.get_raw_timeseries(
            metric_name="nonexistent_metric",
            start_time=0,
            end_time=999999999,
            client_ids=[sample_metrics['client'].id],
            active_only=False
        )

        assert df.empty


class TestGetTimeseriesData:
    """Test aggregated timeseries data"""

    def test_get_timeseries_with_max_aggregation(self, test_db, sample_metrics):
        """Aggregate timeseries with max"""
        start_time, end_time = sample_metrics['timestamp_range']

        df = MetricQueryBuilder.get_timeseries_data(
            metric_name="ipmi_temp_celsius",
            start_time=start_time,
            end_time=end_time + 100,
            client_ids=[sample_metrics['client'].id],
            aggregation="max",
            label_filters=None
        )

        assert not df.empty
        # Each timestamp should have max of CPU and VRM temps
        assert len(df) == 10
        # Latest value should be max(71, 59) = 71
        assert df['value'].iloc[-1] == 71.0

    def test_get_timeseries_with_min_aggregation(self, test_db, sample_metrics):
        """Aggregate timeseries with min"""
        start_time, end_time = sample_metrics['timestamp_range']

        df = MetricQueryBuilder.get_timeseries_data(
            metric_name="ipmi_temp_celsius",
            start_time=start_time,
            end_time=end_time + 100,
            client_ids=[sample_metrics['client'].id],
            aggregation="min"
        )

        assert not df.empty
        # Each timestamp should have min of CPU and VRM temps
        # Latest value should be min(71, 59) = 59
        assert df['value'].iloc[-1] == 59.0

    def test_get_timeseries_with_avg_aggregation(self, test_db, sample_metrics):
        """Aggregate timeseries with average"""
        start_time, end_time = sample_metrics['timestamp_range']

        df = MetricQueryBuilder.get_timeseries_data(
            metric_name="ipmi_temp_celsius",
            start_time=start_time,
            end_time=end_time + 100,
            client_ids=[sample_metrics['client'].id],
            aggregation="avg"
        )

        assert not df.empty
        # Average of CPU and VRM temps
        last_avg = df['value'].iloc[-1]
        assert 64.0 <= last_avg <= 66.0  # avg(71, 59) = 65


class TestCalculateRatesFromRawData:
    """Test rate calculation for counter metrics"""

    def test_calculate_rates_basic(self, test_db, sample_counter_metrics):
        """Calculate rates from counter data"""
        import time
        now = int(time.time())

        # Get raw data
        df = MetricQueryBuilder.get_raw_timeseries(
            metric_name="network_receive_bytes_total",
            start_time=now - 300,
            end_time=now,
            client_ids=[sample_counter_metrics['client'].id],
            active_only=False
        )

        # Calculate rates
        rate_df = MetricQueryBuilder.calculate_rates_from_raw_data(df, rate_window_minutes=1)

        assert not rate_df.empty
        # Should have rates calculated
        assert 'value' in rate_df.columns
        # Rates should be positive (monotonically increasing counter)
        assert all(rate_df['value'] >= 0)

    def test_calculate_rates_returns_bytes_per_second(self, test_db, sample_counter_metrics):
        """Rates should be in bytes/second"""
        import time
        now = int(time.time())

        df = MetricQueryBuilder.get_raw_timeseries(
            metric_name="network_receive_bytes_total",
            start_time=now - 300,
            end_time=now,
            client_ids=[sample_counter_metrics['client'].id],
            active_only=False
        )

        rate_df = MetricQueryBuilder.calculate_rates_from_raw_data(df)

        # Expected rate is 10000 bytes/second
        expected_rate = sample_counter_metrics['expected_rate_rx']

        # Check that calculated rates are close to expected (within 20%)
        mean_rate = rate_df['value'].mean()
        assert 0.8 * expected_rate <= mean_rate <= 1.2 * expected_rate


class TestGetRateTimeseries:
    """Test end-to-end rate timeseries"""

    def test_get_rate_timeseries_with_aggregation(self, test_db, sample_counter_metrics):
        """Get rate timeseries with aggregation across multiple metrics"""
        import time
        now = int(time.time())

        # Get rates for both RX and TX, summed
        df = MetricQueryBuilder.get_rate_timeseries(
            metric_name=["network_receive_bytes_total", "network_transmit_bytes_total"],
            start_time=now - 300,
            end_time=now,
            client_ids=[sample_counter_metrics['client'].id],
            aggregation="sum",
            rate_window_minutes=1,
            active_only=False
        )

        assert not df.empty
        # Should have positive rates (no negative rates from mixing counters)
        assert all(df['value'] >= 0), f"Found negative rates: {df[df['value'] < 0]['value'].tolist()}"

        # Expected combined rate should be roughly sum of individual rates
        expected_combined = sample_counter_metrics['expected_rate_rx'] + sample_counter_metrics['expected_rate_tx']
        mean_rate = df['value'].mean()
        # Within 30% tolerance (rolling window and timing variations)
        assert 0.7 * expected_combined <= mean_rate <= 1.3 * expected_combined

    def test_rate_calculation_keeps_series_separate(self, test_db, sample_counter_metrics):
        """Ensure rate calculation doesn't mix different counter series.

        This tests the fix for the bug where different metrics (with vastly different
        counter values like disk_read=18TB and disk_write=9TB) were grouped together,
        causing the rolling window to see alternating high/low values and produce
        massive negative rates.
        """
        import time
        now = int(time.time())

        # Get raw rates (before aggregation) to verify each series calculated separately
        df = MetricQueryBuilder.get_rate_timeseries(
            metric_name=["network_receive_bytes_total", "network_transmit_bytes_total"],
            start_time=now - 300,
            end_time=now,
            client_ids=[sample_counter_metrics['client'].id],
            aggregation="raw",  # No aggregation - keep series separate
            rate_window_minutes=1,
            active_only=False
        )

        assert not df.empty
        # All rates should be non-negative (counters are monotonically increasing)
        negative_rates = df[df['value'] < 0]
        assert len(negative_rates) == 0, f"Found {len(negative_rates)} negative rates, should be 0"

    def test_rate_with_large_counter_values(self, test_db, sample_client):
        """Test rate calculation with large counter values (TB range) like disk I/O.

        Ensures that large counter values don't cause overflow or mixing issues.
        """
        import time
        now = int(time.time())

        # Create metrics with large counter values (simulating disk I/O)
        read_series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="disk_read_bytes_total",
            labels='{"device": "nvme0n1"}',
        )

        write_series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="disk_write_bytes_total",
            labels='{"device": "nvme0n1"}',
        )

        # Create data with large values (18TB read, 9TB write)
        base_read = 18e12  # 18 TB
        base_write = 9e12  # 9 TB
        rate_read = 100e6  # 100 MB/s
        rate_write = 50e6  # 50 MB/s

        for i in range(10):
            timestamp = now - ((9 - i) * 30)

            MetricPoints.create(
                series=read_series,
                timestamp=timestamp,
                sent_at=timestamp,
                value=base_read + (i * 30 * rate_read)
            )

            MetricPoints.create(
                series=write_series,
                timestamp=timestamp,
                sent_at=timestamp,
                value=base_write + (i * 30 * rate_write)
            )

        # Calculate aggregated rate
        df = MetricQueryBuilder.get_rate_timeseries(
            metric_name=["disk_read_bytes_total", "disk_write_bytes_total"],
            start_time=now - 300,
            end_time=now,
            client_ids=[sample_client.id],
            aggregation="sum",
            rate_window_minutes=1,
            active_only=False
        )

        assert not df.empty
        # Should have no negative rates
        assert all(df['value'] >= 0), f"Found negative rates with large counters: {df[df['value'] < 0]['value'].tolist()}"

        # Combined rate should be approximately read + write rate
        expected_combined = rate_read + rate_write
        mean_rate = df['value'].mean()
        assert 0.7 * expected_combined <= mean_rate <= 1.3 * expected_combined
