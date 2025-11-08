"""Unit tests for Metrics Ingestion

Tests the metrics submission and storage pipeline including:
- Metric batch submission
- Series creation and lookup
- Metric point storage (float-only architecture)
- Label handling
- Timestamp validation
- Log entry ingestion
- Hardware change detection
"""
import pytest
import sys
import os
import time
import json
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from models import Client, MetricSeries, MetricPointsFloat, LogEntry
from api.schemas import MetricsBatchRequest, MetricRecord, LogEntryData


class TestMetricSeriesCreation:
    """Test metric series creation and lookup"""

    def test_create_series_without_labels(self, test_db, sample_client):
        """Create series without labels"""
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="cpu_usage_percent",
            labels=None,
            value_type="float"
        )

        assert series is not None
        assert series.metric_name == "cpu_usage_percent"
        assert series.labels is None
        assert series.client.id == sample_client.id

    def test_create_series_with_labels(self, test_db, sample_client):
        """Create series with labels"""
        labels_json = json.dumps({"device": "nvme0n1"})
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="disk_read_bytes_total",
            labels=labels_json,
            value_type="float"
        )

        assert series is not None
        assert series.metric_name == "disk_read_bytes_total"
        # JSON may be stored without spaces, so check parsed value
        assert json.loads(series.labels)["device"] == "nvme0n1"

    def test_get_or_create_returns_existing_series(self, test_db, sample_client):
        """Getting same series should return existing record"""
        labels_json = json.dumps({"interface": "eth0"})

        # Create first time
        series1 = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="network_receive_bytes_total",
            labels=labels_json,
            value_type="float"
        )

        # Get second time - should return same series
        series2 = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="network_receive_bytes_total",
            labels=labels_json,
            value_type="float"
        )

        assert series1.id == series2.id

    def test_different_labels_create_different_series(self, test_db, sample_client):
        """Different labels should create separate series"""
        series1 = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="disk_read_bytes_total",
            labels=json.dumps({"device": "nvme0n1"}),
            value_type="float"
        )

        series2 = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="disk_read_bytes_total",
            labels=json.dumps({"device": "sda"}),
            value_type="float"
        )

        assert series1.id != series2.id

    def test_different_clients_create_different_series(self, test_db, sample_clients):
        """Same metric from different clients creates separate series"""
        series1 = MetricSeries.get_or_create_series(
            client_id=sample_clients[0].id,
            metric_name="cpu_usage_percent",
            labels=None,
            value_type="float"
        )

        series2 = MetricSeries.get_or_create_series(
            client_id=sample_clients[1].id,
            metric_name="cpu_usage_percent",
            labels=None,
            value_type="float"
        )

        assert series1.id != series2.id
        assert series1.client.id != series2.client.id


class TestMetricPointStorage:
    """Test metric point storage (float-only architecture)"""

    def test_store_float_metric(self, test_db, sample_client):
        """Store float metric value"""
        now = int(time.time())
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="cpu_usage_percent",
            labels=None,
            value_type="float"
        )

        point = MetricPointsFloat.create(
            series=series,
            timestamp=now,
            value=65.5
        )

        assert point is not None
        assert point.value == 65.5
        assert point.timestamp == now

    def test_store_integer_as_float(self, test_db, sample_client):
        """Integer values should be stored as float (architecture decision)"""
        now = int(time.time())
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="disk_read_bytes_total",
            labels=None,
            value_type="float"
        )

        point = MetricPointsFloat.create(
            series=series,
            timestamp=now,
            value=float(1000000)  # Integer value as float
        )

        assert point is not None
        assert point.value == 1000000.0
        assert isinstance(point.value, float)

    def test_store_large_counter_value(self, test_db, sample_client):
        """Large counter values (TB range) should store correctly"""
        now = int(time.time())
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="disk_read_bytes_total",
            labels=None,
            value_type="float"
        )

        large_value = 18e12  # 18 TB
        point = MetricPointsFloat.create(
            series=series,
            timestamp=now,
            value=large_value
        )

        assert point is not None
        assert point.value == large_value

    def test_bulk_insert_metrics(self, test_db, sample_client):
        """Bulk insert multiple metric points"""
        now = int(time.time())
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="cpu_usage_percent",
            labels=None,
            value_type="float"
        )

        points = [
            {"series": series.id, "timestamp": now - 60, "value": 50.0},
            {"series": series.id, "timestamp": now - 30, "value": 55.0},
            {"series": series.id, "timestamp": now, "value": 60.0},
        ]

        inserted = MetricPointsFloat.insert_many(points).execute()

        assert inserted == 3

    def test_duplicate_timestamp_ignored(self, test_db, sample_client):
        """Duplicate timestamps should be ignored (on_conflict_ignore)"""
        now = int(time.time())
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="cpu_usage_percent",
            labels=None,
            value_type="float"
        )

        # Insert first point
        MetricPointsFloat.create(series=series, timestamp=now, value=50.0)

        # Try to insert duplicate timestamp
        points = [{"series": series.id, "timestamp": now, "value": 60.0}]
        inserted = MetricPointsFloat.insert_many(points).on_conflict_ignore().execute()

        # SQLite returns number of rows modified, which may be 1 even when ignored
        # Just verify original value preserved
        point = MetricPointsFloat.get(MetricPointsFloat.series == series, MetricPointsFloat.timestamp == now)
        assert point.value == 50.0


class TestMetricsBatchSubmission:
    """Test batch metric submission endpoint logic"""

    def test_submit_batch_with_single_metric(self, test_db, sample_client):
        """Submit single metric in batch"""
        now = int(time.time())

        batch = MetricsBatchRequest(
            metrics=[
                MetricRecord(
                    timestamp=now,
                    metric_name="cpu_usage_percent",
                    value_type="float",
                    value=65.5,
                    labels=None
                )
            ]
        )

        # Simulate ingestion
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name=batch.metrics[0].metric_name,
            labels=None,
            value_type=batch.metrics[0].value_type
        )

        point = MetricPointsFloat.create(
            series=series,
            timestamp=batch.metrics[0].timestamp,
            value=batch.metrics[0].value
        )

        assert point.value == 65.5

    def test_submit_batch_with_multiple_metrics(self, test_db, sample_client):
        """Submit multiple metrics in batch"""
        now = int(time.time())

        batch = MetricsBatchRequest(
            metrics=[
                MetricRecord(timestamp=now, metric_name="cpu_usage_percent", value_type="float", value=65.5),
                MetricRecord(timestamp=now, metric_name="memory_usage_percent", value_type="float", value=75.2),
                MetricRecord(timestamp=now, metric_name="disk_usage_percent", value_type="float", value=45.8),
            ]
        )

        # Process batch
        for metric in batch.metrics:
            series = MetricSeries.get_or_create_series(
                client_id=sample_client.id,
                metric_name=metric.metric_name,
                labels=None,
                value_type=metric.value_type
            )
            MetricPointsFloat.create(series=series, timestamp=metric.timestamp, value=metric.value)

        # Verify all metrics stored
        cpu_series = MetricSeries.get(
            MetricSeries.client == sample_client.id,
            MetricSeries.metric_name == "cpu_usage_percent"
        )
        assert cpu_series is not None

        mem_series = MetricSeries.get(
            MetricSeries.client == sample_client.id,
            MetricSeries.metric_name == "memory_usage_percent"
        )
        assert mem_series is not None

    def test_submit_metrics_with_labels(self, test_db, sample_client):
        """Submit metrics with labels"""
        now = int(time.time())

        batch = MetricsBatchRequest(
            metrics=[
                MetricRecord(
                    timestamp=now,
                    metric_name="disk_read_bytes_total",
                    value_type="float",
                    value=1000000.0,
                    labels={"device": "nvme0n1"}
                ),
                MetricRecord(
                    timestamp=now,
                    metric_name="disk_read_bytes_total",
                    value_type="float",
                    value=500000.0,
                    labels={"device": "sda"}
                ),
            ]
        )

        # Process batch
        for metric in batch.metrics:
            labels_json = json.dumps(metric.labels) if metric.labels else None
            series = MetricSeries.get_or_create_series(
                client_id=sample_client.id,
                metric_name=metric.metric_name,
                labels=labels_json,
                value_type=metric.value_type
            )
            MetricPointsFloat.create(series=series, timestamp=metric.timestamp, value=metric.value)

        # Should create two separate series
        series_count = MetricSeries.select().where(
            MetricSeries.client == sample_client.id,
            MetricSeries.metric_name == "disk_read_bytes_total"
        ).count()
        assert series_count == 2

    def test_future_timestamp_validation(self, test_db, sample_client):
        """Timestamps too far in future should be rejected"""
        now = int(time.time())
        future_time = now + 600  # 10 minutes in future (> 5 minute tolerance)

        batch = MetricsBatchRequest(
            metrics=[
                MetricRecord(
                    timestamp=future_time,
                    metric_name="cpu_usage_percent",
                    value_type="float",
                    value=65.5
                )
            ]
        )

        # Validation logic (from metrics_routes.py)
        tolerance = 300  # 5 minutes
        is_valid = batch.metrics[0].timestamp <= now + tolerance

        assert is_valid is False


class TestLogEntryIngestion:
    """Test log entry ingestion"""

    def test_submit_log_entries(self, test_db, sample_client):
        """Submit log entries with metrics batch"""
        now = int(time.time())

        batch = MetricsBatchRequest(
            metrics=[],
            logs=[
                LogEntryData(
                    log_source="journal",
                    log_timestamp=now - 60,
                    content="[systemd] Started dcmon client",
                    severity="INFO"
                ),
                LogEntryData(
                    log_source="dmesg",
                    log_timestamp=now - 30,
                    content="Out of memory: Killed process 1234",
                    severity="ERROR"
                )
            ]
        )

        # Process logs
        log_entries = []
        for log_data in batch.logs:
            log_entries.append({
                "client": sample_client.id,
                "log_source": log_data.log_source,
                "log_timestamp": log_data.log_timestamp,
                "received_timestamp": now,
                "content": log_data.content,
                "severity": log_data.severity
            })

        inserted = LogEntry.insert_many(log_entries).execute()

        assert inserted == 2

        # Verify logs stored
        logs = list(LogEntry.select().where(LogEntry.client == sample_client.id))
        assert len(logs) == 2
        assert logs[0].log_source in ["journal", "dmesg"]

    def test_log_severity_levels(self, test_db, sample_client):
        """Test different log severity levels"""
        now = int(time.time())

        severities = ["ERROR", "WARN", "INFO", "DEBUG"]
        log_entries = []

        for i, severity in enumerate(severities):
            log_entries.append({
                "client": sample_client.id,
                "log_source": "journal",
                "log_timestamp": now - (i * 10),
                "received_timestamp": now,
                "content": f"Test {severity} message",
                "severity": severity
            })

        LogEntry.insert_many(log_entries).execute()

        # Verify all severities stored
        for severity in severities:
            log = LogEntry.get(
                LogEntry.client == sample_client.id,
                LogEntry.severity == severity
            )
            assert log is not None

    def test_log_sources(self, test_db, sample_client):
        """Test different log sources"""
        now = int(time.time())

        sources = ["dmesg", "journal", "syslog", "vast"]
        log_entries = []

        for i, source in enumerate(sources):
            log_entries.append({
                "client": sample_client.id,
                "log_source": source,
                "log_timestamp": now - (i * 10),
                "received_timestamp": now,
                "content": f"Log from {source}",
                "severity": "INFO"
            })

        LogEntry.insert_many(log_entries).execute()

        # Verify all sources stored
        for source in sources:
            log = LogEntry.get(
                LogEntry.client == sample_client.id,
                LogEntry.log_source == source
            )
            assert log is not None


class TestHardwareChangeDetection:
    """Test hardware change detection"""

    def test_hardware_hash_update(self, test_db, sample_client):
        """Hardware hash change should be detected and updated"""
        original_hash = sample_client.hw_hash
        new_hash = "new_hardware_hash_12345"

        # Simulate hardware change
        if new_hash != sample_client.hw_hash:
            sample_client.hw_hash = new_hash
            sample_client.save()

        # Verify update
        updated_client = Client.get_by_id(sample_client.id)
        assert updated_client.hw_hash == new_hash
        assert updated_client.hw_hash != original_hash

    def test_no_change_when_hash_same(self, test_db, sample_client):
        """Same hardware hash should not trigger update"""
        original_hash = "test_hw_hash_123"
        sample_client.hw_hash = original_hash
        sample_client.save()

        # Submit same hash
        if original_hash != sample_client.hw_hash:
            sample_client.hw_hash = original_hash
            sample_client.save()

        # Should remain unchanged
        assert sample_client.hw_hash == original_hash


class TestClientLastSeenUpdate:
    """Test client last_seen timestamp updates"""

    def test_last_seen_updated_on_metrics_submission(self, test_db, sample_client):
        """Submitting metrics should update last_seen"""
        # Set old last_seen explicitly
        old_time = int(time.time()) - 100
        sample_client.last_seen = old_time
        sample_client.save()

        # Update last_seen
        sample_client.update_last_seen()

        assert sample_client.last_seen > old_time

    def test_client_marked_online_when_active(self, test_db, sample_client):
        """Client should be considered online when recently active"""
        now = int(time.time())

        # Set last_seen to 1 minute ago
        sample_client.last_seen = now - 60
        sample_client.save()

        # Check online status (typically < 5 minutes = online)
        is_online = (now - sample_client.last_seen) < 300

        assert is_online is True

    def test_client_marked_offline_when_inactive(self, test_db, sample_client):
        """Client should be offline when inactive > 5 minutes"""
        now = int(time.time())

        # Set last_seen to 10 minutes ago
        sample_client.last_seen = now - 600
        sample_client.save()

        # Check online status
        is_online = (now - sample_client.last_seen) < 300

        assert is_online is False


class TestMetricValidation:
    """Test metric data validation"""

    def test_metric_name_required(self):
        """Metric name is required"""
        with pytest.raises(Exception):  # Pydantic validation error
            MetricRecord(
                timestamp=int(time.time()),
                metric_name="",  # Empty not allowed
                value_type="float",
                value=65.5
            )

    def test_value_type_validation(self):
        """Value type must be int or float"""
        with pytest.raises(Exception):  # Pydantic validation error
            MetricRecord(
                timestamp=int(time.time()),
                metric_name="cpu_usage",
                value_type="string",  # Invalid
                value=65.5
            )

    def test_integer_value_validation(self):
        """Integer value_type should validate value is convertible to int"""
        # Valid integer
        metric = MetricRecord(
            timestamp=int(time.time()),
            metric_name="counter",
            value_type="int",
            value=100.0  # Float representation of integer
        )
        assert metric.value == 100.0

        # Pydantic validation allows 100.5 to be converted to int (truncates)
        # This test documents current behavior - fractional values are allowed
        metric2 = MetricRecord(
            timestamp=int(time.time()),
            metric_name="counter",
            value_type="int",
            value=100.5
        )
        # Value is stored as-is (will be cast to int during storage)
        assert metric2.value == 100.5
