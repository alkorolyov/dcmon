"""Unit tests for MetricQueryBuilder

Tests the data access layer in isolation.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from api.metric_queries import MetricQueryBuilder, CPU_SENSORS, VRM_SENSORS
from models import MetricSeries, Client


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

    @pytest.mark.skip(reason="Rate aggregation across metrics needs investigation")
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
        # Should have positive rates
        assert all(df['value'] >= 0)
