"""APT package updates metrics exporter.

Collects information about pending package updates and system reboot requirements.
"""

import asyncio
import logging
from pathlib import Path
from typing import List

from .base import MetricsExporter, MetricPoint


class AptExporter(MetricsExporter):
    """APT updates exporter (Python-only)
    Emits:
      - apt_upgrades_pending_total (count of upgradable packages)
      - apt_reboot_required (0/1 based on /var/run/reboot-required)
    """
    def __init__(self):
        super().__init__("apt", logging.getLogger())

    async def collect(self) -> List[MetricPoint]:
        # Count upgradable packages without shell pipelines
        proc = await asyncio.create_subprocess_exec(
            "apt", "list", "--upgradable",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            # If apt is not available or returns error, emit nothing
            return []

        # Filter out the "Listing..." header and empty lines
        lines = [ln.strip() for ln in out.decode().splitlines() if ln.strip()]
        upgradable_count = sum(1 for ln in lines if not ln.startswith("Listing..."))

        reboot_required = 1 if Path("/var/run/reboot-required").exists() else 0

        return [
            MetricPoint("apt_upgrades_pending", int(upgradable_count), {}),
            MetricPoint("apt_reboot_required", int(reboot_required), {}),
        ]
