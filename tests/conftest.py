"""Pytest configuration and shared fixtures"""
import pytest
import tempfile
import os
import time
from peewee import SqliteDatabase

# Import models
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from models import Client, MetricSeries, MetricPoints, LogEntry


@pytest.fixture
def test_db():
    """Create an in-memory test database"""
    # Use in-memory SQLite for fast tests
    test_database = SqliteDatabase(':memory:')

    # Bind all models to test database
    models = [Client, MetricSeries, MetricPoints, LogEntry]
    test_database.bind(models, bind_refs=False, bind_backrefs=False)
    test_database.connect()
    test_database.create_tables(models)

    yield test_database

    # Cleanup
    test_database.drop_tables(models)
    test_database.close()


@pytest.fixture
def sample_client(test_db):
    """Create a sample client for testing"""
    now = int(time.time())
    client = Client.create(
        client_token="test_token_12345",
        hostname="test-server-01",
        machine_id="machine-test-12345",
        public_key="-----BEGIN PUBLIC KEY-----\ntest_key\n-----END PUBLIC KEY-----",
        status="online",
        last_seen=now,
        created_at=now
    )
    return client


@pytest.fixture
def sample_clients(test_db):
    """Create multiple sample clients"""
    now = int(time.time())
    clients = []

    for i in range(3):
        client = Client.create(
            client_token=f"test_token_{i:03d}",
            hostname=f"test-server-{i:02d}",
            machine_id=f"machine-{i:03d}",
            public_key=f"test-key-{i}",
            status="online" if i < 2 else "offline",
            last_seen=now - (i * 100),  # Stagger last_seen times
            created_at=now - (i * 1000)
        )
        clients.append(client)

    return clients


@pytest.fixture
def sample_metrics(test_db, sample_client):
    """Create sample metrics data for testing"""
    now = int(time.time())

    # Use the actual get_or_create_series method from the model
    cpu_series = MetricSeries.get_or_create_series(
        client_id=sample_client.id,
        metric_name="cpu_usage_percent",
        labels=None,
        value_type="float"
    )

    temp_series = MetricSeries.get_or_create_series(
        client_id=sample_client.id,
        metric_name="ipmi_temp_celsius",
        labels='{"sensor": "CPU Temp"}',
        value_type="int"
    )

    vrm_series = MetricSeries.get_or_create_series(
        client_id=sample_client.id,
        metric_name="ipmi_temp_celsius",
        labels='{"sensor": "VRM Temp"}',
        value_type="int"
    )

    # Create metric points (10 data points spanning 5 minutes)
    cpu_points = []
    temp_points = []
    vrm_points = []

    for i in range(10):
        timestamp = now - ((9 - i) * 30)  # Every 30 seconds, oldest first
        sent_at = timestamp

        # CPU usage varies between 40-60%
        MetricPoints.create(
            series=cpu_series,
            timestamp=timestamp,
            sent_at=sent_at,
            value=45.0 + (i * 1.5)
        )

        # CPU temp varies between 60-70°C
        MetricPoints.create(
            series=temp_series,
            timestamp=timestamp,
            sent_at=sent_at,
            value=float(62 + i)
        )

        # VRM temp varies between 50-58°C
        MetricPoints.create(
            series=vrm_series,
            timestamp=timestamp,
            sent_at=sent_at,
            value=float(50 + i)
        )

    return {
        'client': sample_client,
        'series': {
            'cpu': cpu_series,
            'temp': temp_series,
            'vrm': vrm_series
        },
        'timestamp_range': (now - 270, now),  # 4.5 minutes of data
        'latest_timestamp': now
    }


@pytest.fixture
def sample_counter_metrics(test_db, sample_client):
    """Create counter metrics for rate calculation testing"""
    now = int(time.time())

    # Use the actual get_or_create_series method
    rx_series = MetricSeries.get_or_create_series(
        client_id=sample_client.id,
        metric_name="network_receive_bytes_total",
        labels='{"interface": "eth0"}',
        value_type="int"
    )

    tx_series = MetricSeries.get_or_create_series(
        client_id=sample_client.id,
        metric_name="network_transmit_bytes_total",
        labels='{"interface": "eth0"}',
        value_type="int"
    )

    # Create increasing counter values (simulating network traffic)
    base_rx = 1000000  # 1MB baseline
    base_tx = 500000   # 500KB baseline
    rate_rx = 10000    # 10KB/s increase
    rate_tx = 5000     # 5KB/s increase

    for i in range(10):
        timestamp = now - ((9 - i) * 30)  # Every 30 seconds

        # All metrics stored as float in unified table
        MetricPoints.create(
            series=rx_series,
            timestamp=timestamp,
            sent_at=timestamp,
            value=float(base_rx + (i * 30 * rate_rx))  # Monotonically increasing
        )

        MetricPoints.create(
            series=tx_series,
            timestamp=timestamp,
            sent_at=timestamp,
            value=float(base_tx + (i * 30 * rate_tx))
        )

    return {
        'client': sample_client,
        'series': {'rx': rx_series, 'tx': tx_series},
        'expected_rate_rx': rate_rx,  # bytes/second
        'expected_rate_tx': rate_tx
    }


@pytest.fixture
def sample_disk_metrics(test_db, sample_client):
    """Create disk metrics for fraction calculation testing"""
    now = int(time.time())

    # Use the actual get_or_create_series method
    used_series = MetricSeries.get_or_create_series(
        client_id=sample_client.id,
        metric_name="fs_used_bytes",
        labels='{"mountpoint": "/"}',
        value_type="int"
    )

    total_series = MetricSeries.get_or_create_series(
        client_id=sample_client.id,
        metric_name="fs_total_bytes",
        labels='{"mountpoint": "/"}',
        value_type="int"
    )

    # Create points: 75% disk usage
    total_bytes = 100 * 1024**3  # 100 GB
    used_bytes = 75 * 1024**3    # 75 GB

    MetricPoints.create(
        series=used_series,
        timestamp=now,
        sent_at=now,
        value=float(used_bytes)
    )

    MetricPoints.create(
        series=total_series,
        timestamp=now,
        sent_at=now,
        value=float(total_bytes)
    )

    return {
        'client': sample_client,
        'series': {'used': used_series, 'total': total_series},
        'expected_percentage': 75.0
    }
