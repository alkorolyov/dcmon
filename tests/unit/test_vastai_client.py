"""Unit tests for VastAI API Client

Tests the VastAI API client functionality including:
- API endpoint querying
- Response parsing
- Error handling
"""
import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from api.vastai_client import VastAIClient


# Real-world API response mocks from actual VastAI API
MOCK_MACHINES_RESPONSE = {
    "machines": [
        {
            "id": 5338,
            "machine_id": 5338,
            "hostname": "srv01",
            "geolocation": ", RU",
            "num_gpus": 4,
            "total_flops": 410.91071999999997,
            "gpu_name": "RTX 4090",
            "gpu_ram": 24564,
            "gpu_max_cur_temp": 24.0,
            "cpu_name": "AMD EPYC 7532 32-Core Processor",
            "cpu_ram": 257584,
            "cpu_cores": 64,
            "listed": False,
            "current_rentals_running": 0,
            "current_rentals_running_on_demand": 0,
            "current_rentals_resident": 0,
            "current_rentals_on_demand": 0,
            "reliability2": 0.9987982,
            "earn_hour": 8.088995e-55,
            "earn_day": 0.0008247081,
            "verification": "verified",
            "clients": []
        },
        {
            "id": 35798,
            "machine_id": 35798,
            "hostname": "srv02",
            "geolocation": ", RU",
            "num_gpus": 4,
            "total_flops": 410.4192,
            "gpu_name": "RTX 4090",
            "gpu_ram": 24564,
            "gpu_max_cur_temp": 28.0,
            "cpu_name": "AMD EPYC 7763 64-Core Processor",
            "cpu_ram": 257550,
            "cpu_cores": 128,
            "listed": True,
            "current_rentals_running": 0,
            "current_rentals_running_on_demand": 0,
            "current_rentals_resident": 1,
            "current_rentals_on_demand": 1,
            "reliability2": 0.9986929,
            "earn_hour": 0.002777836,
            "earn_day": 7.41056,
            "verification": "unverified",
            "clients": []
        },
        {
            "id": 39164,
            "machine_id": 39164,
            "hostname": "kale",
            "geolocation": "Poland, PL",
            "num_gpus": 1,
            "total_flops": 134.4768,
            "gpu_name": "RTX 5090",
            "gpu_ram": 32607,
            "cpu_name": "AMD Ryzen 9 9950X 16-Core Processor",
            "cpu_ram": 94142,
            "cpu_cores": 32,
            "listed": True,
            "current_rentals_running": 0,
            "current_rentals_running_on_demand": 0,
            "current_rentals_resident": 0,
            "current_rentals_on_demand": 0,
            "reliability2": 0.9993259,
            "earn_hour": 0.0,
            "earn_day": 0.0,
            "verification": "unverified",
            "clients": []
        }
    ]
}

MOCK_EARNINGS_RESPONSE = {
    "sday": 20399,
    "eday": 20399,
    "summary": {
        "total_gpu": 2.15,
        "total_stor": 0.09,
        "total_bwu": 0.0,
        "total_bwd": 0.0
    },
    "username": "test@example.com",
    "email": "test@example.com",
    "current": {
        "balance": 0.04,
        "service_fee": 0.0,
        "total": 0.04,
        "credit": 0.0
    },
    "per_machine": [
        {"machine_id": 5338, "gpu_earn": 0.0, "sto_earn": 0.0, "bwu_earn": 0.0, "bwd_earn": 0.0},
        {"machine_id": 35798, "gpu_earn": 2.15, "sto_earn": 0.09, "bwu_earn": 0.0, "bwd_earn": 0.0},
        {"machine_id": 39164, "gpu_earn": 0.0, "sto_earn": 0.0, "bwu_earn": 0.0, "bwd_earn": 0.0}
    ],
    "per_day": [
        {"day": 20399, "gpu_earn": 2.15, "sto_earn": 0.09, "bwu_earn": 0.0, "bwd_earn": 0.0}
    ]
}


class TestVastAIClient:
    """Test VastAI API client functionality"""

    def test_init_with_api_key(self):
        """Test client initialization with API key"""
        client = VastAIClient(api_key="test_key_123")
        assert client.api_key == "test_key_123"
        assert client.base_url == "https://console.vast.ai/api/v0"

    def test_init_from_environment(self):
        """Test client initialization from environment variable"""
        with patch.dict(os.environ, {'VAST_API_KEY': 'env_key_456'}):
            client = VastAIClient()
            assert client.api_key == "env_key_456"

    def test_init_without_api_key_raises_error(self):
        """Test that missing API key raises ValueError"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="VAST_API_KEY not found"):
                VastAIClient()

    @patch('urllib.request.urlopen')
    def test_get_machines(self, mock_urlopen):
        """Test fetching machines list"""
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(MOCK_MACHINES_RESPONSE).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = VastAIClient(api_key="test_key")
        machines = client.get_machines()

        # Verify results
        assert len(machines) == 3
        assert machines[0]['machine_id'] == 5338
        assert machines[0]['hostname'] == "srv01"
        assert machines[0]['listed'] is False
        assert machines[1]['machine_id'] == 35798
        assert machines[1]['hostname'] == "srv02"
        assert machines[1]['listed'] is True
        assert machines[2]['machine_id'] == 39164
        assert machines[2]['hostname'] == "kale"

        # Verify API call was made correctly
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "https://console.vast.ai/api/v0/machines/"
        assert request.get_header('Authorization') == "Bearer test_key"

    @patch('urllib.request.urlopen')
    def test_get_earnings(self, mock_urlopen):
        """Test fetching earnings data"""
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(MOCK_EARNINGS_RESPONSE).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = VastAIClient(api_key="test_key")
        earnings = client.get_earnings()

        # Verify results
        assert earnings['summary']['total_gpu'] == 2.15
        assert earnings['summary']['total_stor'] == 0.09
        assert len(earnings['per_machine']) == 3

        # Check specific machine earnings
        srv02_earnings = next(e for e in earnings['per_machine'] if e['machine_id'] == 35798)
        assert srv02_earnings['gpu_earn'] == 2.15
        assert srv02_earnings['sto_earn'] == 0.09

        # Verify API call
        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "https://console.vast.ai/api/v0/users/current/machine-earnings/"
        assert request.get_header('Authorization') == "Bearer test_key"

    @patch('urllib.request.urlopen')
    def test_api_error_handling(self, mock_urlopen):
        """Test that API errors are propagated"""
        import urllib.error

        # Simulate HTTP error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://console.vast.ai/api/v0/machines/",
            401,
            "Unauthorized",
            {},
            None
        )

        client = VastAIClient(api_key="invalid_key")

        with pytest.raises(urllib.error.HTTPError):
            client.get_machines()

    @patch('urllib.request.urlopen')
    def test_malformed_json_response(self, mock_urlopen):
        """Test handling of malformed JSON response"""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not valid json {{"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = VastAIClient(api_key="test_key")

        with pytest.raises(json.JSONDecodeError):
            client.get_machines()
