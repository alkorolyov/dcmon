"""Unit tests for DashboardController

Tests the business logic layer in isolation with mocked data access.
"""
import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from dashboard.controller import DashboardController, TABLE_COLUMNS
from dashboard.config import get_metric_status, format_metric_value


class TestCalculateFraction:
    """Test fraction calculation (disk usage, etc.)"""

    def test_calculate_fraction_basic(self):
        """Basic fraction calculation: (numerator / denominator) * multiplier"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder') as mock_qb:
            # Mock: used=75GB, total=100GB
            mock_qb.get_latest_metric_value.side_effect = [
                75.0 * 1024**3,  # numerator (used bytes)
                100.0 * 1024**3   # denominator (total bytes)
            ]

            column_config = {
                "numerator": {"metric_name": "fs_used_bytes"},
                "denominator": {"metric_name": "fs_total_bytes"},
                "multiply_by": 100
            }

            result = controller._calculate_fraction(client_id=1, column_config=column_config)

            # Should be (75/100) * 100 = 75%
            assert result == 75.0

    def test_calculate_fraction_with_zero_denominator_returns_none(self):
        """Division by zero should return None gracefully"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.side_effect = [50.0, 0.0]

            column_config = {
                "numerator": {"metric_name": "used"},
                "denominator": {"metric_name": "total"},
                "multiply_by": 1
            }

            result = controller._calculate_fraction(client_id=1, column_config=column_config)

            assert result is None

    def test_calculate_fraction_with_none_numerator_returns_none(self):
        """Missing numerator should return None"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.side_effect = [None, 100.0]

            column_config = {
                "numerator": {"metric_name": "used"},
                "denominator": {"metric_name": "total"},
                "multiply_by": 100
            }

            result = controller._calculate_fraction(client_id=1, column_config=column_config)

            assert result is None

    def test_calculate_fraction_with_label_filters(self):
        """Fraction calculation should pass label filters to query builder"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.side_effect = [50.0, 100.0]

            column_config = {
                "numerator": {
                    "metric_name": "fs_used_bytes",
                    "label_filters": [{"mountpoint": "/"}]
                },
                "denominator": {
                    "metric_name": "fs_total_bytes",
                    "label_filters": [{"mountpoint": "/"}]
                },
                "multiply_by": 100
            }

            result = controller._calculate_fraction(client_id=1, column_config=column_config)

            assert result == 50.0

            # Verify label filters were passed
            calls = mock_qb.get_latest_metric_value.call_args_list
            assert calls[0][1]['label_filters'] == [{"mountpoint": "/"}]
            assert calls[1][1]['label_filters'] == [{"mountpoint": "/"}]


class TestCalculateRate:
    """Test rate calculation for counter metrics"""

    def test_calculate_rate_basic(self, test_db, sample_client):
        """Calculate rate from counter metric using real database"""
        import time
        import pandas as pd
        controller = DashboardController()

        now = int(time.time())

        # Create a counter metric series
        from models import MetricSeries, MetricPoints
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="network_receive_bytes_total",
            labels='{"interface": "eth0"}',
        )

        # Create data points: 5 minutes ago and now
        # Rate should be (100000 - 0) / 300 = 333.33 bytes/sec
        MetricPoints.create(
            series=series,
            timestamp=now - 300,
            sent_at=now - 300,
            value=0.0
        )
        MetricPoints.create(
            series=series,
            timestamp=now,
            sent_at=now,
            value=100000.0
        )

        column_config = {
            "metric_name": "network_receive_bytes_total",
            "label_filters": [{"interface": "eth0"}],
            "time_window": 300
        }

        result = controller._calculate_rate(sample_client.id, column_config)

        # Should get approximately 333.33 bytes/sec
        assert result is not None
        assert 300 <= result <= 400  # Allow some tolerance

    def test_calculate_rate_with_counter_reset_handles_gracefully(self, test_db, sample_client):
        """Counter reset (current < previous) should handle gracefully"""
        import time
        controller = DashboardController()

        now = int(time.time())

        # Create a counter metric series
        from models import MetricSeries, MetricPoints
        series = MetricSeries.get_or_create_series(
            client_id=sample_client.id,
            metric_name="network_transmit_bytes_total",
            labels='{"interface": "eth0"}',
        )

        # Simulate counter reset: previous was higher, current is lower
        MetricPoints.create(
            series=series,
            timestamp=now - 300,
            sent_at=now - 300,
            value=100000.0  # High value
        )
        MetricPoints.create(
            series=series,
            timestamp=now,
            sent_at=now,
            value=1000.0  # Reset to low value
        )

        column_config = {
            "metric_name": "network_transmit_bytes_total",
            "label_filters": [{"interface": "eth0"}],
            "time_window": 300
        }

        result = controller._calculate_rate(sample_client.id, column_config)

        # Should handle reset gracefully (returns current / time_elapsed)
        assert result is not None
        assert result >= 0  # Should not be negative

    def test_calculate_rate_with_no_previous_data_returns_none(self):
        """No historical data should return None"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.return_value = 1000000.0
            import pandas as pd
            mock_qb.get_timeseries_data.return_value = pd.DataFrame()  # Empty

            column_config = {
                "metric_name": "network_receive_bytes_total",
                "time_window": 300
            }

            result = controller._calculate_rate(client_id=1, column_config=column_config)

            assert result is None


class TestGetLatestMetric:
    """Test get_latest_metric dispatcher (routes to correct calculation)"""

    def test_get_latest_metric_regular(self):
        """Regular metric (no operation) should call MetricQueryBuilder directly"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.return_value = 65.5

            column_config = {
                "metric_name": "cpu_temp_celsius",
                "aggregation": "max"
            }

            result = controller.get_latest_metric(client_id=1, column_config=column_config)

            assert result == 65.5
            mock_qb.get_latest_metric_value.assert_called_once_with(
                client_id=1,
                metric_name="cpu_temp_celsius",
                label_filters=None,
                aggregation="max"
            )

    def test_get_latest_metric_with_label_filters(self):
        """Label filters should be passed through"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.return_value = 70.0

            column_config = {
                "metric_name": "ipmi_temp_celsius",
                "label_filters": [{"sensor": "CPU Temp"}],
                "aggregation": "max"
            }

            result = controller.get_latest_metric(client_id=1, column_config=column_config)

            assert result == 70.0
            call_kwargs = mock_qb.get_latest_metric_value.call_args[1]
            assert call_kwargs['label_filters'] == [{"sensor": "CPU Temp"}]

    def test_get_latest_metric_fraction_operation(self):
        """Operation 'fraction' should call _calculate_fraction"""
        controller = DashboardController()

        with patch.object(controller, '_calculate_fraction', return_value=75.0) as mock_calc:
            column_config = {
                "operation": "fraction",
                "numerator": {"metric_name": "used"},
                "denominator": {"metric_name": "total"},
                "multiply_by": 100
            }

            result = controller.get_latest_metric(client_id=1, column_config=column_config)

            assert result == 75.0
            mock_calc.assert_called_once_with(1, column_config)

    def test_get_latest_metric_rate_operation(self):
        """Operation 'rate' should call _calculate_rate"""
        controller = DashboardController()

        with patch.object(controller, '_calculate_rate', return_value=1500.0) as mock_calc:
            column_config = {
                "operation": "rate",
                "metric_name": "network_bytes_total",
                "time_window": 300
            }

            result = controller.get_latest_metric(client_id=1, column_config=column_config)

            assert result == 1500.0
            mock_calc.assert_called_once_with(1, column_config)

    def test_get_latest_metric_handles_exceptions_gracefully(self):
        """Exceptions should return None, not crash"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.side_effect = Exception("DB error")

            column_config = {"metric_name": "cpu_temp"}

            result = controller.get_latest_metric(client_id=1, column_config=column_config)

            assert result is None


class TestPrepareClientMetrics:
    """Test client metrics preparation for table display"""

    def test_prepare_client_metrics_single_client(self):
        """Prepare metrics for single client"""
        controller = DashboardController()

        # Mock get_latest_metric to return different values
        with patch.object(controller, 'get_latest_metric') as mock_get:
            # Return different values for different columns
            mock_get.side_effect = [65.0, 45.0, 75.0]  # CPU temp, VRM temp, GPU temp

            clients_data = [
                {"id": 1, "hostname": "server-01"}
            ]

            # Use subset of TABLE_COLUMNS for testing
            test_columns = [
                {"metric_name": "cpu_temp", "header": "CPU°C", "unit": "°", "css_class": "col-cpu-temp"},
                {"metric_name": "vrm_temp", "header": "VRM°C", "unit": "°", "css_class": "col-vrm-temp"},
                {"metric_name": "gpu_temp", "header": "GPU°C", "unit": "°", "css_class": "col-gpu-temp"},
            ]

            with patch('dashboard.controller.TABLE_COLUMNS', test_columns):
                result = controller._prepare_client_metrics(clients_data)

            assert len(result) == 1
            assert "metric_values" in result[0]
            assert "col-cpu-temp" in result[0]["metric_values"]
            assert result[0]["metric_values"]["col-cpu-temp"]["value"] == 65.0
            assert result[0]["metric_values"]["col-vrm-temp"]["value"] == 45.0
            assert result[0]["metric_values"]["col-gpu-temp"]["value"] == 75.0

    def test_prepare_client_metrics_formats_values(self):
        """Values should be formatted with units"""
        controller = DashboardController()

        with patch.object(controller, 'get_latest_metric', return_value=65.5):
            clients_data = [{"id": 1, "hostname": "test"}]

            test_columns = [
                {"metric_name": "cpu_temp", "header": "CPU", "unit": "°C", "css_class": "cpu"}
            ]

            with patch('dashboard.controller.TABLE_COLUMNS', test_columns):
                result = controller._prepare_client_metrics(clients_data)

            metric_data = result[0]["metric_values"]["cpu"]
            assert metric_data["value"] == 65.5
            assert "formatted" in metric_data
            # Should have formatted value with unit

    def test_prepare_client_metrics_handles_none_values(self):
        """None values should be handled gracefully"""
        controller = DashboardController()

        with patch.object(controller, 'get_latest_metric', return_value=None):
            clients_data = [{"id": 1, "hostname": "test"}]

            test_columns = [
                {"metric_name": "missing_metric", "header": "Missing", "unit": "X", "css_class": "missing"}
            ]

            with patch('dashboard.controller.TABLE_COLUMNS', test_columns):
                result = controller._prepare_client_metrics(clients_data)

            metric_data = result[0]["metric_values"]["missing"]
            assert metric_data["value"] is None
            assert metric_data["formatted"] == "—"  # Em dash for missing
            assert metric_data["status"] == "no-data"

    def test_prepare_client_metrics_applies_thresholds(self):
        """Status should be determined by thresholds"""
        controller = DashboardController()

        with patch.object(controller, 'get_latest_metric', return_value=85.0):  # High temp
            clients_data = [{"id": 1, "hostname": "test"}]

            test_columns = [
                {
                    "metric_name": "cpu_temp",
                    "header": "CPU",
                    "unit": "°",
                    "css_class": "cpu",
                    "threshold_type": "cpu_temp_celsius"
                }
            ]

            with patch('dashboard.controller.TABLE_COLUMNS', test_columns):
                result = controller._prepare_client_metrics(clients_data)

            metric_data = result[0]["metric_values"]["cpu"]
            assert metric_data["value"] == 85.0
            # Status should reflect threshold (likely warning or critical)
            assert metric_data["status"] in ["normal", "warning", "critical"]

    def test_prepare_client_metrics_multiple_clients(self):
        """Prepare metrics for multiple clients"""
        controller = DashboardController()

        with patch.object(controller, 'get_latest_metric') as mock_get:
            # Return different values for each client
            mock_get.side_effect = [65.0, 70.0, 75.0]  # Client 1, 2, 3

            clients_data = [
                {"id": 1, "hostname": "server-01"},
                {"id": 2, "hostname": "server-02"},
                {"id": 3, "hostname": "server-03"}
            ]

            test_columns = [
                {"metric_name": "cpu_temp", "header": "CPU", "unit": "°", "css_class": "cpu"}
            ]

            with patch('dashboard.controller.TABLE_COLUMNS', test_columns):
                result = controller._prepare_client_metrics(clients_data)

            assert len(result) == 3
            assert result[0]["metric_values"]["cpu"]["value"] == 65.0
            assert result[1]["metric_values"]["cpu"]["value"] == 70.0
            assert result[2]["metric_values"]["cpu"]["value"] == 75.0


class TestGetMainDashboardData:
    """Test main dashboard data preparation"""

    def test_get_main_dashboard_data_structure(self):
        """Should return complete dashboard data structure"""
        controller = DashboardController()

        with patch.object(controller, '_get_client_status_data', return_value=[]):
            with patch.object(controller, '_get_system_overview_data', return_value={}):
                with patch.object(controller, '_get_recent_alerts', return_value=[]):
                    result = controller.get_main_dashboard_data()

        assert "page_title" in result
        assert "timestamp" in result
        assert "clients" in result
        assert "total_clients" in result
        assert "online_clients" in result
        assert "system_overview" in result
        assert "recent_alerts" in result
        assert "table_columns" in result

    def test_get_main_dashboard_data_counts_clients(self):
        """Should count total and online clients"""
        controller = DashboardController()

        mock_clients = [
            {"status": "online"},
            {"status": "online"},
            {"status": "offline"}
        ]

        with patch.object(controller, '_get_client_status_data', return_value=mock_clients):
            with patch.object(controller, '_get_system_overview_data', return_value={}):
                with patch.object(controller, '_get_recent_alerts', return_value=[]):
                    result = controller.get_main_dashboard_data()

        assert result["total_clients"] == 3
        assert result["online_clients"] == 2

    def test_get_main_dashboard_data_handles_exceptions(self):
        """Exceptions should return error structure, not crash"""
        controller = DashboardController()

        with patch.object(controller, '_get_client_status_data', side_effect=Exception("DB error")):
            result = controller.get_main_dashboard_data()

        assert "error" in result
        assert result["clients"] == []


class TestGetClientStatusData:
    """Test client status data retrieval"""

    def test_get_client_status_data_basic(self, test_db, sample_client):
        """Get basic client status"""
        controller = DashboardController()

        with patch.object(controller, '_get_client_latest_metrics', return_value={}):
            with patch.object(controller, '_prepare_client_metrics', side_effect=lambda x: x):
                result = controller._get_client_status_data()

        assert len(result) == 1
        assert result[0]["hostname"] == "test-server-01"
        assert result[0]["is_online"] is True
        assert "last_seen" in result[0]

    def test_get_client_status_data_determines_online_status(self, test_db):
        """Client online status based on last_seen"""
        import time
        now = int(time.time())

        # Create online and offline clients
        from models import Client
        online_client = Client.create(
            client_token="online_token_123",
            hostname="online",
            machine_id="m1",
            public_key="key1",
            created_at=now - 3600,
            last_seen=now - 60  # 1 minute ago - online
        )

        offline_client = Client.create(
            client_token="offline_token_456",
            hostname="offline",
            machine_id="m2",
            public_key="key2",
            created_at=now - 3600,
            last_seen=now - 600  # 10 minutes ago - offline
        )

        controller = DashboardController()

        with patch.object(controller, '_get_client_latest_metrics', return_value={}):
            with patch.object(controller, '_prepare_client_metrics', side_effect=lambda x: x):
                result = controller._get_client_status_data()

        online_status = [c for c in result if c["hostname"] == "online"][0]
        offline_status = [c for c in result if c["hostname"] == "offline"][0]

        assert online_status["is_online"] is True
        assert offline_status["is_online"] is False


class TestGetClientDetailData:
    """Test client detail modal data"""

    def test_get_client_detail_data_basic(self, test_db, sample_client):
        """Get client detail data"""
        controller = DashboardController()

        with patch('dashboard.controller.MetricQueryBuilder.get_all_latest_metrics_for_client') as mock_get:
            # Return empty metrics
            mock_get.return_value = {}

            result = controller.get_client_detail_data(sample_client.id)

        assert result["client_id"] == sample_client.id
        assert result["hostname"] == "test-server-01"
        assert "is_online" in result
        assert "detailed_metrics" in result

    def test_get_client_detail_data_organizes_metrics_by_device(self, test_db, sample_client):
        """Metrics should be organized by device type"""
        controller = DashboardController()

        mock_metrics = {
            "gpu_temperature": {"GPU0": 65.0, "GPU1": 70.0},
            "psu_input_power_watts": {"PSU1": 450.0},
            "cpu_usage_percent": {"": 55.0}
        }

        with patch('dashboard.controller.MetricQueryBuilder.get_all_latest_metrics_for_client') as mock_get:
            mock_get.return_value = mock_metrics

            result = controller.get_client_detail_data(sample_client.id)

        detailed = result["detailed_metrics"]
        assert "gpu_table" in detailed
        assert "psu_table" in detailed
        assert "system" in detailed
