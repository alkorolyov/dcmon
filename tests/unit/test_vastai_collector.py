"""Unit tests for VastAI Metrics Collector

Tests the VastAI collector background task including:
- Metrics collection and storage
- Client matching by hostname
- Rental count calculation
- Database integration
"""
import pytest
import sys
import os
import time
import json
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from tasks.vastai_collector import get_rental_counts, collect_vastai_metrics
from models import Client, MetricSeries, MetricPoints


# Real-world API response mocks
MOCK_MACHINES = [
    {
        "machine_id": 35798,
        "hostname": "srv02",
        "listed": True,
        "reliability2": 0.9986929,
        "current_rentals_running": 0,
        "current_rentals_running_on_demand": 0,
        "current_rentals_resident": 1,
        "current_rentals_on_demand": 1
    },
    {
        "machine_id": 39164,
        "hostname": "kale",
        "listed": True,
        "reliability2": 0.9993259,
        "current_rentals_running": 0,
        "current_rentals_running_on_demand": 0,
        "current_rentals_resident": 0,
        "current_rentals_on_demand": 0
    },
    {
        "machine_id": 5338,
        "hostname": "srv01",
        "listed": False,
        "reliability2": 0.9987982,
        "current_rentals_running": 0,
        "current_rentals_running_on_demand": 0,
        "current_rentals_resident": 0,
        "current_rentals_on_demand": 0
    }
]

MOCK_EARNINGS = {
    "per_machine": [
        {"machine_id": 35798, "gpu_earn": 2.15, "sto_earn": 0.09, "bwu_earn": 0.0, "bwd_earn": 0.0},
        {"machine_id": 39164, "gpu_earn": 0.0, "sto_earn": 0.0, "bwu_earn": 0.0, "bwd_earn": 0.0},
        {"machine_id": 5338, "gpu_earn": 0.0, "sto_earn": 0.0, "bwu_earn": 0.0, "bwd_earn": 0.0}
    ]
}


class TestRentalCounts:
    """Test rental count calculation"""

    def test_no_rentals(self):
        """Test machine with no rentals"""
        machine = {
            "current_rentals_running": 0,
            "current_rentals_running_on_demand": 0
        }
        interruptible, on_demand = get_rental_counts(machine)
        assert interruptible == 0
        assert on_demand == 0

    def test_only_on_demand_rentals(self):
        """Test machine with only on-demand rentals"""
        machine = {
            "current_rentals_running": 2,
            "current_rentals_running_on_demand": 2
        }
        interruptible, on_demand = get_rental_counts(machine)
        assert interruptible == 0
        assert on_demand == 2

    def test_only_interruptible_rentals(self):
        """Test machine with only interruptible rentals"""
        machine = {
            "current_rentals_running": 3,
            "current_rentals_running_on_demand": 0
        }
        interruptible, on_demand = get_rental_counts(machine)
        assert interruptible == 3
        assert on_demand == 0

    def test_mixed_rentals(self):
        """Test machine with both interruptible and on-demand"""
        machine = {
            "current_rentals_running": 5,
            "current_rentals_running_on_demand": 2
        }
        interruptible, on_demand = get_rental_counts(machine)
        assert interruptible == 3  # 5 - 2
        assert on_demand == 2

    def test_missing_fields_defaults_to_zero(self):
        """Test machine with missing rental fields"""
        machine = {}
        interruptible, on_demand = get_rental_counts(machine)
        assert interruptible == 0
        assert on_demand == 0


class TestVastAICollector:
    """Test VastAI metrics collector functionality"""

    @pytest.fixture
    def vastai_clients(self, test_db):
        """Create clients matching VastAI hostnames"""
        now = int(time.time())
        clients = []

        # Create clients matching our mock machines
        for hostname in ["srv02", "kale"]:
            client = Client.create(
                client_token=f"token_{hostname}",
                hostname=hostname,
                machine_id=f"machine_{hostname}",
                vast_machine_id=f"vast_hash_{hostname}",
                status="active",
                last_seen=now,
                created_at=now
            )
            clients.append(client)

        return clients

    @patch('tasks.vastai_collector.VastAIClient')
    def test_collect_metrics_for_matched_clients(self, mock_client_class, test_db, vastai_clients):
        """Test that metrics are collected for clients with matching hostnames"""
        # Setup mock VastAI client
        mock_client = MagicMock()
        mock_client.get_machines.return_value = MOCK_MACHINES
        mock_client.get_earnings.return_value = MOCK_EARNINGS
        mock_client_class.return_value = mock_client

        # Run collector
        collect_vastai_metrics()

        # Verify metrics were stored
        # Should have 8 metrics × 2 matched clients = 16 series
        series_count = MetricSeries.select().where(
            MetricSeries.metric_name.startswith("vast_")
        ).count()
        assert series_count == 16  # 8 metrics for each of 2 clients

        # Verify metric points were created
        points_count = MetricPoints.select().count()
        assert points_count == 16  # One point per series

        # Check specific metrics for srv02
        srv02_client = Client.get(Client.hostname == "srv02")

        # Check vast_listed metric
        listed_series = MetricSeries.get(
            (MetricSeries.client == srv02_client) &
            (MetricSeries.metric_name == "vast_listed")
        )
        listed_point = MetricPoints.get(MetricPoints.series == listed_series)
        assert listed_point.value == 1.0  # srv02 is listed

        # Check vast_reliability metric
        reliability_series = MetricSeries.get(
            (MetricSeries.client == srv02_client) &
            (MetricSeries.metric_name == "vast_reliability")
        )
        reliability_point = MetricPoints.get(MetricPoints.series == reliability_series)
        assert abs(reliability_point.value - 0.9986929) < 0.0001

        # Check earnings
        gpu_earn_series = MetricSeries.get(
            (MetricSeries.client == srv02_client) &
            (MetricSeries.metric_name == "vast_gpu_earn")
        )
        gpu_earn_point = MetricPoints.get(MetricPoints.series == gpu_earn_series)
        assert gpu_earn_point.value == 2.15

        storage_earn_series = MetricSeries.get(
            (MetricSeries.client == srv02_client) &
            (MetricSeries.metric_name == "vast_storage_earn")
        )
        storage_earn_point = MetricPoints.get(MetricPoints.series == storage_earn_series)
        assert storage_earn_point.value == 0.09

    @patch('tasks.vastai_collector.VastAIClient')
    def test_skip_unmatched_machines(self, mock_client_class, test_db, vastai_clients):
        """Test that machines without matching clients are skipped"""
        # Setup mock - includes srv01 which has no matching client
        mock_client = MagicMock()
        mock_client.get_machines.return_value = MOCK_MACHINES
        mock_client.get_earnings.return_value = MOCK_EARNINGS
        mock_client_class.return_value = mock_client

        # Run collector
        collect_vastai_metrics()

        # Should only have metrics for srv02 and kale, not srv01
        series_count = MetricSeries.select().count()
        assert series_count == 16  # 8 metrics × 2 clients (srv01 skipped)

        # Verify srv01 metrics were NOT created
        srv01_series = MetricSeries.select().join(Client).where(
            Client.hostname == "srv01"
        ).count()
        assert srv01_series == 0

    @patch('tasks.vastai_collector.VastAIClient')
    def test_labels_include_machine_id(self, mock_client_class, test_db, vastai_clients):
        """Test that labels include vast_api_machine_id"""
        mock_client = MagicMock()
        mock_client.get_machines.return_value = MOCK_MACHINES
        mock_client.get_earnings.return_value = MOCK_EARNINGS
        mock_client_class.return_value = mock_client

        collect_vastai_metrics()

        # Check labels on a series
        srv02_client = Client.get(Client.hostname == "srv02")
        series = MetricSeries.get(
            (MetricSeries.client == srv02_client) &
            (MetricSeries.metric_name == "vast_listed")
        )

        labels = json.loads(series.labels)
        assert "vast_api_machine_id" in labels
        assert labels["vast_api_machine_id"] == "35798"

    @patch('tasks.vastai_collector.VastAIClient')
    def test_rental_counts_stored_correctly(self, mock_client_class, test_db, vastai_clients):
        """Test that rental counts are calculated and stored correctly"""
        # Create machine with active rentals
        machines_with_rentals = [
            {
                "machine_id": 35798,
                "hostname": "srv02",
                "listed": True,
                "reliability2": 0.999,
                "current_rentals_running": 5,
                "current_rentals_running_on_demand": 2
            }
        ]

        mock_client = MagicMock()
        mock_client.get_machines.return_value = machines_with_rentals
        mock_client.get_earnings.return_value = {"per_machine": [
            {"machine_id": 35798, "gpu_earn": 0, "sto_earn": 0, "bwu_earn": 0, "bwd_earn": 0}
        ]}
        mock_client_class.return_value = mock_client

        collect_vastai_metrics()

        srv02_client = Client.get(Client.hostname == "srv02")

        # Check interruptible count
        interruptible_series = MetricSeries.get(
            (MetricSeries.client == srv02_client) &
            (MetricSeries.metric_name == "vast_rentals_interruptible")
        )
        interruptible_point = MetricPoints.get(MetricPoints.series == interruptible_series)
        assert interruptible_point.value == 3.0  # 5 - 2

        # Check on-demand count
        ondemand_series = MetricSeries.get(
            (MetricSeries.client == srv02_client) &
            (MetricSeries.metric_name == "vast_rentals_ondemand")
        )
        ondemand_point = MetricPoints.get(MetricPoints.series == ondemand_series)
        assert ondemand_point.value == 2.0

    @patch('tasks.vastai_collector.VastAIClient')
    def test_sent_at_timestamp_set(self, mock_client_class, test_db, vastai_clients):
        """Test that sent_at timestamp is set on metric points"""
        mock_client = MagicMock()
        mock_client.get_machines.return_value = MOCK_MACHINES[:1]  # Just srv02
        mock_client.get_earnings.return_value = {"per_machine": [
            {"machine_id": 35798, "gpu_earn": 0, "sto_earn": 0, "bwu_earn": 0, "bwd_earn": 0}
        ]}
        mock_client_class.return_value = mock_client

        before = int(time.time())
        collect_vastai_metrics()
        after = int(time.time())

        # Check that sent_at is set and reasonable
        point = MetricPoints.select().first()
        assert point is not None
        assert before <= point.sent_at <= after
        assert before <= point.timestamp <= after

    @patch('tasks.vastai_collector.VastAIClient')
    def test_api_error_handling(self, mock_client_class, test_db, vastai_clients):
        """Test that API errors are caught and logged"""
        mock_client = MagicMock()
        mock_client.get_machines.side_effect = Exception("API error")
        mock_client_class.return_value = mock_client

        # Should not raise exception
        collect_vastai_metrics()

        # No metrics should be stored
        assert MetricSeries.select().count() == 0
        assert MetricPoints.select().count() == 0

    @patch('tasks.vastai_collector.VastAIClient')
    def test_all_eight_metrics_created(self, mock_client_class, test_db, vastai_clients):
        """Test that all 8 expected metrics are created"""
        mock_client = MagicMock()
        mock_client.get_machines.return_value = MOCK_MACHINES[:1]  # Just srv02
        mock_client.get_earnings.return_value = {"per_machine": [
            {"machine_id": 35798, "gpu_earn": 1.0, "sto_earn": 0.5, "bwu_earn": 0.1, "bwd_earn": 0.2}
        ]}
        mock_client_class.return_value = mock_client

        collect_vastai_metrics()

        srv02_client = Client.get(Client.hostname == "srv02")

        # Expected metrics
        expected_metrics = [
            "vast_listed",
            "vast_reliability",
            "vast_gpu_earn",
            "vast_storage_earn",
            "vast_bw_up_earn",
            "vast_bw_down_earn",
            "vast_rentals_interruptible",
            "vast_rentals_ondemand"
        ]

        for metric_name in expected_metrics:
            series = MetricSeries.select().where(
                (MetricSeries.client == srv02_client) &
                (MetricSeries.metric_name == metric_name)
            )
            assert series.count() == 1, f"Missing metric: {metric_name}"

            # Verify point exists
            point = MetricPoints.select().join(MetricSeries).where(
                (MetricSeries.client == srv02_client) &
                (MetricSeries.metric_name == metric_name)
            )
            assert point.count() == 1, f"Missing point for metric: {metric_name}"
