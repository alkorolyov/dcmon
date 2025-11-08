"""NVIDIA GPU metrics exporter.

Collects GPU metrics using nvidia-smi including temperature, utilization,
power draw, memory usage, and clock speeds.
"""

import asyncio
import logging
from typing import List

from .base import MetricsExporter, MetricPoint


class NvsmiExporter(MetricsExporter):
    """
    Optimized NVIDIA GPU collector:
    - Only emits essential metrics: temp, power_draw, util_{gpu,mem}, fan, clocks_{sm,mem},
      pcie_{gen,width}, memory_usage (%)
    - Removed: power_limit, pstate, ecc_mode (not essential for monitoring)
    - Labels: model, bus_id
    """
    def __init__(self):
        super().__init__("nvslim")

    async def collect(self) -> List[MetricPoint]:
        # Ask nvidia-smi just for essential fields (no units to simplify parsing)
        fields = [
            "gpu_bus_id",
            "pcie.link.gen.current",
            "pcie.link.width.current",
            "fan.speed",
            "utilization.gpu",
            "utilization.memory",
            "temperature.gpu",
            "power.draw",
            "power.limit",
            "clocks.sm",
            "clocks.mem",
            "memory.total",
            "memory.reserved",
            "memory.used",
            "name",
        ]
        cmd = [
            "nvidia-smi",
            f"--query-gpu={','.join(fields)}",
            "--format=csv,noheader,nounits"
        ]

        # Run once; supports multi-GPU (one CSV line per GPU)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"nvidia-smi failed: {err.decode().strip()}")

        metrics: List[MetricPoint] = []
        for line in out.decode().strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            (bus_id, pcie_gen, pcie_width, fan, util_gpu, util_mem,
             temp, pwr_draw, pwr_limit, clk_sm, clk_mem,
             mem_total, mem_reserved, mem_used, name) = parts

            # Tidy labels (match your bash exporter semantics)
            # bus_id like "00000000:01:00.0" -> "01:00.0"
            bus_id_short = ":".join(bus_id.split(":")[-2:])
            model = " ".join(name.split()[-2:])  # keep the short "RTX 5090" style

            labels = {"model": model, "bus_id": bus_id_short}

            # Parse numerics
            pcie_gen = int(pcie_gen); pcie_width = int(pcie_width)
            fan = int(fan); util_gpu = float(util_gpu); util_mem = float(util_mem)
            temp = int(temp); pwr_draw = int(float(pwr_draw)); pwr_limit = int(float(pwr_limit))
            clk_sm = int(float(clk_sm)); clk_mem = int(float(clk_mem))
            mem_total = float(mem_total); mem_reserved = float(mem_reserved); mem_used = float(mem_used)

            mem_usage_pct = int((mem_reserved + mem_used) / mem_total * 100.0) if mem_total > 0 else 0.0

            # Emit only essential metrics (optimized for monitoring)
            metrics.extend([
                MetricPoint("gpu_temperature", temp, labels),
                MetricPoint("gpu_power_draw", pwr_draw, labels),
                MetricPoint("gpu_power_limit", pwr_limit, labels),
                MetricPoint("gpu_utilization_gpu", util_gpu, labels),
                MetricPoint("gpu_utilization_memory", util_mem, labels),
                MetricPoint("gpu_fan_speed", fan, labels),
                MetricPoint("gpu_clock_sm", clk_sm, labels),
                MetricPoint("gpu_clock_mem", clk_mem, labels),
                MetricPoint("gpu_pcie_gen", pcie_gen, labels),
                MetricPoint("gpu_pcie_width", pcie_width, labels),
                MetricPoint("gpu_memory_usage", round(mem_usage_pct, 2), labels),
            ])

        return metrics
