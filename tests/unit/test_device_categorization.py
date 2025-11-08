"""
Tests for device categorization logic.

Tests the table-driven device categorization rules in dashboard/device_rules.py
"""

import pytest
from server.dashboard.device_rules import categorize_by_device


class TestGPUDeviceCategorization:
    """Test GPU device categorization."""

    def test_gpu_temperature(self):
        device_id, metric_type = categorize_by_device('GPU1', 'gpu_temperature')
        assert device_id == 'GPU1'
        assert metric_type == 'Temperature'

    def test_gpu_fan_speed(self):
        device_id, metric_type = categorize_by_device('GPU2', 'gpu_fan_speed')
        assert device_id == 'GPU2'
        assert metric_type == 'Fan Speed'

    def test_gpu_power_draw(self):
        device_id, metric_type = categorize_by_device('GPU1', 'gpu_power_draw')
        assert device_id == 'GPU1'
        assert metric_type == 'Power Draw'

    def test_gpu_utilization(self):
        device_id, metric_type = categorize_by_device('GPU3', 'gpu_utilization_percent')
        assert device_id == 'GPU3'
        assert metric_type == 'Utilization'

    def test_gpu_memory(self):
        device_id, metric_type = categorize_by_device('GPU1', 'gpu_memory_used')
        assert device_id == 'GPU1'
        assert metric_type == 'Memory'

    def test_gpu_clock_speed(self):
        device_id, metric_type = categorize_by_device('GPU2', 'gpu_clock_speed')
        assert device_id == 'GPU2'
        assert metric_type == 'Clock Speed'

    def test_gpu_unknown_metric(self):
        """Test GPU with unknown metric falls back to title case."""
        device_id, metric_type = categorize_by_device('GPU1', 'gpu_some_new_metric')
        assert device_id == 'GPU1'
        assert metric_type == 'Some New Metric'


class TestPSUDeviceCategorization:
    """Test PSU device categorization."""

    def test_psu_power_input(self):
        device_id, metric_type = categorize_by_device('PSU1', 'psu_input_power_watts')
        assert device_id == 'PSU1'
        assert metric_type == 'Power Input'

    def test_psu_power_with_watts_keyword(self):
        device_id, metric_type = categorize_by_device('PSU2', 'psu_output_watts')
        assert device_id == 'PSU2'
        assert metric_type == 'Power Input'

    def test_psu_fan_speed(self):
        device_id, metric_type = categorize_by_device('PSU1', 'psu_fan1_rpm')
        assert device_id == 'PSU1'
        assert metric_type == 'Fan Speed'

    def test_psu_temperature(self):
        device_id, metric_type = categorize_by_device('PSU2', 'psu_temp1_celsius')
        assert device_id == 'PSU2'
        assert metric_type == 'Temperature'

    def test_psu_voltage(self):
        device_id, metric_type = categorize_by_device('PSU1', 'psu_voltage_12v')
        assert device_id == 'PSU1'
        assert metric_type == 'Voltage'

    def test_psu_unknown_metric(self):
        """Test PSU with unknown metric falls back to title case."""
        device_id, metric_type = categorize_by_device('PSU3', 'psu_status_code')
        assert device_id == 'PSU3'
        assert metric_type == 'Status Code'


class TestNetworkDeviceCategorization:
    """Test network device categorization."""

    def test_ethernet_transmit(self):
        device_id, metric_type = categorize_by_device('eth0', 'network_transmit_bytes')
        assert device_id == 'eth0'
        assert metric_type == 'Transmit'

    def test_ethernet_receive(self):
        device_id, metric_type = categorize_by_device('eth1', 'network_receive_bytes')
        assert device_id == 'eth1'
        assert metric_type == 'Receive'

    def test_eno_interface_tx(self):
        device_id, metric_type = categorize_by_device('eno1', 'network_tx_packets')
        assert device_id == 'eno1'
        assert metric_type == 'Transmit'

    def test_eno_interface_rx(self):
        device_id, metric_type = categorize_by_device('eno1', 'network_rx_packets')
        assert device_id == 'eno1'
        assert metric_type == 'Receive'

    def test_wlan_interface(self):
        device_id, metric_type = categorize_by_device('wlan0', 'network_receive_bytes')
        assert device_id == 'wlan0'
        assert metric_type == 'Receive'

    def test_network_unknown_metric(self):
        device_id, metric_type = categorize_by_device('eth0', 'network_errors_total')
        assert device_id == 'eth0'
        assert metric_type == 'Errors Total'


class TestStorageDeviceCategorization:
    """Test storage device categorization."""

    def test_filesystem_used_space(self):
        device_id, metric_type = categorize_by_device('/', 'fs_used_bytes')
        assert device_id == '/'
        assert metric_type == 'Used Space'

    def test_filesystem_free_space(self):
        device_id, metric_type = categorize_by_device('/home', 'fs_free_bytes')
        assert device_id == '/home'
        assert metric_type == 'Free Space'

    def test_filesystem_available_space(self):
        device_id, metric_type = categorize_by_device('root', 'fs_avail_bytes')
        assert device_id == 'root'
        assert metric_type == 'Free Space'

    def test_filesystem_total_size(self):
        device_id, metric_type = categorize_by_device('/var', 'fs_size_bytes')
        assert device_id == '/var'
        assert metric_type == 'Total Size'

    def test_nvme_wear_level(self):
        device_id, metric_type = categorize_by_device('nvme0n1', 'nvme_wear_percentage')
        assert device_id == 'nvme0n1'
        assert metric_type == 'Wear Level'

    def test_nvme_temperature(self):
        device_id, metric_type = categorize_by_device('nvme1n1', 'nvme_temperature_celsius')
        assert device_id == 'nvme1n1'
        assert metric_type == 'Temperature'

    def test_sda_disk_metric(self):
        device_id, metric_type = categorize_by_device('sda1', 'disk_read_bytes')
        assert device_id == 'sda1'
        assert metric_type == 'Read Bytes'


class TestFallbackCategorization:
    """Test fallback behavior for unknown devices."""

    def test_unknown_device_unknown_metric(self):
        """Unknown device should return label and formatted metric name."""
        device_id, metric_type = categorize_by_device('unknown_device', 'some_metric_name')
        assert device_id == 'unknown_device'
        assert metric_type == 'Some Metric Name'

    def test_cpu_sensor_metric(self):
        """CPU sensor should use fallback."""
        device_id, metric_type = categorize_by_device('CPU Temp', 'ipmi_temp_celsius')
        assert device_id == 'CPU Temp'
        assert metric_type == 'Ipmi Temp Celsius'


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_label(self):
        device_id, metric_type = categorize_by_device('', 'some_metric')
        assert device_id == ''
        assert metric_type == 'Some Metric'

    def test_label_with_spaces(self):
        device_id, metric_type = categorize_by_device('GPU 1', 'gpu_temperature')
        assert device_id == 'GPU 1'
        assert metric_type == 'Temperature'

    def test_case_sensitivity(self):
        """Test that categorization handles case variations."""
        # Lowercase GPU (should still work via fallback)
        device_id, metric_type = categorize_by_device('gpu1', 'gpu_temperature')
        # Won't match prefix rule, but should get fallback
        assert device_id == 'gpu1'

    def test_multiple_keywords_in_metric(self):
        """Test metric with multiple keywords."""
        device_id, metric_type = categorize_by_device('PSU1', 'psu_fan_temp_sensor')
        # Should match 'fan' first in the rules
        assert device_id == 'PSU1'
        assert metric_type == 'Fan Speed'


class TestRealWorldExamples:
    """Test with real-world metric examples from the system."""

    def test_nvidia_smi_metrics(self):
        """Test NVIDIA GPU metrics."""
        test_cases = [
            ('GPU1', 'gpu_temperature', 'GPU1', 'Temperature'),
            ('GPU2', 'gpu_power_draw', 'GPU2', 'Power Draw'),
            ('GPU1', 'gpu_fan_speed', 'GPU1', 'Fan Speed'),
        ]

        for label, metric, expected_device, expected_type in test_cases:
            device_id, metric_type = categorize_by_device(label, metric)
            assert device_id == expected_device
            assert metric_type == expected_type

    def test_ipmi_psu_metrics(self):
        """Test IPMI PSU metrics."""
        test_cases = [
            ('PSU1', 'psu_input_power_watts', 'PSU1', 'Power Input'),
            ('PSU2', 'psu_fan1_rpm', 'PSU2', 'Fan Speed'),
            ('PSU1', 'psu_temp1_celsius', 'PSU1', 'Temperature'),
        ]

        for label, metric, expected_device, expected_type in test_cases:
            device_id, metric_type = categorize_by_device(label, metric)
            assert device_id == expected_device
            assert metric_type == expected_type

    def test_filesystem_metrics(self):
        """Test filesystem metrics."""
        test_cases = [
            ('/', 'fs_used_bytes', '/', 'Used Space'),
            ('/home', 'fs_free_bytes', '/home', 'Free Space'),
            ('root', 'fs_size_bytes', 'root', 'Total Size'),
        ]

        for label, metric, expected_device, expected_type in test_cases:
            device_id, metric_type = categorize_by_device(label, metric)
            assert device_id == expected_device
            assert metric_type == expected_type
