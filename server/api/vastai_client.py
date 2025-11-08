"""VastAI API client for querying machine and earnings data."""

import os
import json
import urllib.request
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()

class VastAIClient:
    """Client for VastAI API."""

    def __init__(self, api_key: str = None):
        """
        Initialize VastAI client.

        Args:
            api_key: VastAI API key. If None, reads from VAST_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("VAST_API_KEY")
        if not self.api_key:
            raise ValueError("VAST_API_KEY not found in environment variables")

        self.base_url = "https://console.vast.ai/api/v0"

    def _query_api(self, endpoint: str) -> dict:
        """
        Query VastAI API endpoint.

        Args:
            endpoint: API endpoint path (e.g., "/machines/")

        Returns:
            Parsed JSON response

        Raises:
            urllib.error.HTTPError: If API request fails
        """
        url = f"{self.base_url}{endpoint}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self.api_key}")

        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())

    def get_machines(self) -> List[Dict]:
        """
        Get list of all owned machines.

        Returns:
            List of machine dictionaries with fields like:
            - machine_id, hostname, listed, reliability2
            - current_rentals_running, current_rentals_running_on_demand
            - num_gpus, gpu_name, etc.
        """
        data = self._query_api("/machines/")
        return data.get("machines", [])

    def get_earnings(self) -> Dict:
        """
        Get earnings data for all machines.

        Returns:
            Dictionary with:
            - summary: {total_gpu, total_stor, total_bwu, total_bwd}
            - per_machine: [{machine_id, gpu_earn, sto_earn, bwu_earn, bwd_earn}, ...]
            - per_day: [{day, gpu_earn, sto_earn, bwu_earn, bwd_earn}, ...]
        """
        return self._query_api("/users/current/machine-earnings/")
