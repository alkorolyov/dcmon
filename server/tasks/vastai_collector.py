"""VastAI metrics collector background task."""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List

from dotenv import load_dotenv

# Support running as script or as package
try:
    from ..api.vastai_client import VastAIClient
    from ..models import Client, MetricSeries, MetricPoints
except ImportError:
    from api.vastai_client import VastAIClient
    from models import Client, MetricSeries, MetricPoints

load_dotenv()

logger = logging.getLogger("dcmon.server")


def get_rental_counts(machine: dict) -> tuple:
    """
    Calculate interruptible and on-demand rental counts.

    Args:
        machine: Machine data from VastAI API

    Returns:
        Tuple of (interruptible_count, on_demand_count)
    """
    running = machine.get('current_rentals_running', 0)
    running_on_demand = machine.get('current_rentals_running_on_demand', 0)
    interruptible = running - running_on_demand
    return (interruptible, running_on_demand)


def collect_vastai_metrics():
    """
    Collect VastAI metrics and store them in the database.
    This function runs synchronously and is called from async context via executor.
    """
    try:
        # Initialize VastAI client
        client = VastAIClient()
        logger.debug("VastAI collector: starting collection")

        # Get data from VastAI API
        machines = client.get_machines()
        earnings_data = client.get_earnings()
        earnings_map = {e['machine_id']: e for e in earnings_data.get("per_machine", [])}

        logger.debug(f"VastAI collector: found {len(machines)} machines from API")

        # Process each machine
        metrics_stored = 0
        for machine in machines:
            hostname = machine.get('hostname')
            machine_id = machine.get('machine_id')

            if not hostname:
                logger.warning(f"VastAI collector: machine {machine_id} has no hostname, skipping")
                continue

            # Find matching client by hostname
            db_client = Client.get_or_none(Client.hostname == hostname)
            if not db_client:
                logger.debug(f"VastAI collector: no client found for hostname '{hostname}', skipping")
                continue

            # Get earnings for this machine
            earnings = earnings_map.get(machine_id, {})

            # Calculate rental counts
            rentals_interruptible, rentals_ondemand = get_rental_counts(machine)

            # Prepare labels for all metrics
            labels = {"vast_api_machine_id": str(machine_id)}
            labels_json = json.dumps(labels)

            # Current timestamp
            timestamp = int(time.time())

            # Define the 8 metrics to collect (all stored as float)
            metrics_to_store = [
                ('vast_listed', int(machine.get('listed', 0))),
                ('vast_reliability', machine.get('reliability2', 0.0)),
                ('vast_gpu_earn', earnings.get('gpu_earn', 0.0)),
                ('vast_storage_earn', earnings.get('sto_earn', 0.0)),
                ('vast_bw_up_earn', earnings.get('bwu_earn', 0.0)),
                ('vast_bw_down_earn', earnings.get('bwd_earn', 0.0)),
                ('vast_rentals_interruptible', rentals_interruptible),
                ('vast_rentals_ondemand', rentals_ondemand),
            ]

            # Store each metric
            for metric_name, value in metrics_to_store:
                try:
                    # Get or create metric series
                    series = MetricSeries.get_or_create_series(
                        client_id=db_client.id,
                        metric_name=metric_name,
                        labels=labels_json
                    )

                    # Store metric point (all stored as float per architecture)
                    MetricPoints.insert(
                        series=series.id,
                        timestamp=timestamp,
                        sent_at=timestamp,
                        value=float(value)
                    ).on_conflict_ignore().execute()

                    metrics_stored += 1

                except Exception as e:
                    logger.error(f"VastAI collector: failed to store metric {metric_name} for {hostname}: {e}")

            logger.debug(f"VastAI collector: stored metrics for {hostname} (machine_id={machine_id})")

        logger.info(f"VastAI collector: completed, stored {metrics_stored} metric points")

    except Exception as e:
        logger.error(f"VastAI collector: error during collection: {e}")


async def vastai_collector_loop(interval_seconds: int = 300):
    """
    Background task that periodically collects VastAI metrics.

    Args:
        interval_seconds: Seconds between collection runs (default: 300 = 5 minutes)
    """
    # Get interval from environment variable if set
    env_interval = os.getenv("VAST_REFRESH_INTERVAL")
    if env_interval:
        try:
            interval_seconds = int(env_interval)
            logger.info(f"VastAI collector: using refresh interval from env: {interval_seconds}s")
        except ValueError:
            logger.warning(f"VastAI collector: invalid VAST_REFRESH_INTERVAL '{env_interval}', using default {interval_seconds}s")
    else:
        logger.info(f"VastAI collector: using default refresh interval: {interval_seconds}s")

    loop = asyncio.get_running_loop()

    while True:
        try:
            # Run blocking collection in executor to avoid blocking event loop
            await loop.run_in_executor(None, collect_vastai_metrics)
        except Exception as e:
            logger.error(f"VastAI collector: loop error: {e}")

        # Sleep until next collection
        await asyncio.sleep(interval_seconds)
