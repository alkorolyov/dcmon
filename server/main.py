#!/usr/bin/env python3
"""
Lightweight monitoring server using FastAPI and SQLite
Replaces Prometheus for collecting and storing metrics from node_exporter
"""

import asyncio
import aiohttp
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path
import re
import json
import threading
import time

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    timestamp: datetime
    hostname: str
    metric_name: str
    labels: Dict[str, str]
    value: float


class MetricsDB:
    def __init__(self, db_path: str = "metrics.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Main metrics table
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS metrics
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           timestamp
                           DATETIME,
                           hostname
                           TEXT,
                           metric_name
                           TEXT,
                           labels
                           TEXT, -- JSON string of labels
                           value
                           REAL,
                           created_at
                           DATETIME
                           DEFAULT
                           CURRENT_TIMESTAMP
                       )
                       """)

        # Index for faster queries
        cursor.execute("""
                       CREATE INDEX IF NOT EXISTS idx_metrics_lookup
                           ON metrics(hostname, metric_name, timestamp)
                       """)

        # Hosts table to track active nodes
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS hosts
                       (
                           hostname
                           TEXT
                           PRIMARY
                           KEY,
                           port
                           INTEGER,
                           last_seen
                           DATETIME,
                           status
                           TEXT
                           DEFAULT
                           'active'
                       )
                       """)

        conn.commit()
        conn.close()

    def insert_metrics(self, metrics: List[MetricPoint]):
        """Insert multiple metrics into the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        data = [
            (
                metric.timestamp.isoformat(),
                metric.hostname,
                metric.metric_name,
                json.dumps(metric.labels),
                metric.value
            )
            for metric in metrics
        ]

        cursor.executemany("""
                           INSERT INTO metrics (timestamp, hostname, metric_name, labels, value)
                           VALUES (?, ?, ?, ?, ?)
                           """, data)

        conn.commit()
        conn.close()

    def get_latest_metrics(self, hostname: str, hours: int = 1) -> List[Dict]:
        """Get latest metrics for a hostname"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        since = datetime.now() - timedelta(hours=hours)

        cursor.execute("""
                       SELECT timestamp, metric_name, labels, value
                       FROM metrics
                       WHERE hostname = ? AND timestamp > ?
                       ORDER BY timestamp DESC
                       """, (hostname, since.isoformat()))

        results = []
        for row in cursor.fetchall():
            results.append({
                'timestamp': row[0],
                'metric_name': row[1],
                'labels': json.loads(row[2]),
                'value': row[3]
            })

        conn.close()
        return results

    def get_metric_history(self, hostname: str, metric_name: str, hours: int = 24) -> List[Dict]:
        """Get time series data for a specific metric"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        since = datetime.now() - timedelta(hours=hours)

        cursor.execute("""
                       SELECT timestamp, labels, value
                       FROM metrics
                       WHERE hostname = ? AND metric_name = ? AND timestamp > ?
                       ORDER BY timestamp ASC
                       """, (hostname, metric_name, since.isoformat()))

        results = []
        for row in cursor.fetchall():
            results.append({
                'timestamp': row[0],
                'labels': json.loads(row[1]),
                'value': row[2]
            })

        conn.close()
        return results

    def update_host_status(self, hostname: str, port: int, status: str = 'active'):
        """Update host status and last seen timestamp"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO hosts (hostname, port, last_seen, status)
            VALUES (?, ?, ?, ?)
        """, (hostname, port, datetime.now().isoformat(), status))

        conn.commit()
        conn.close()

    def get_active_hosts(self) -> List[Dict]:
        """Get list of active hosts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Consider hosts active if seen in last 5 minutes
        threshold = datetime.now() - timedelta(minutes=5)

        cursor.execute("""
                       SELECT hostname, port, last_seen, status
                       FROM hosts
                       WHERE last_seen > ?
                       ORDER BY hostname
                       """, (threshold.isoformat(),))

        results = []
        for row in cursor.fetchall():
            results.append({
                'hostname': row[0],
                'port': row[1],
                'last_seen': row[2],
                'status': row[3]
            })

        conn.close()
        return results

    def cleanup_old_data(self, days: int = 7):
        """Remove metrics older than specified days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        threshold = datetime.now() - timedelta(days=days)

        cursor.execute("""
                       DELETE
                       FROM metrics
                       WHERE timestamp < ?
                       """, (threshold.isoformat(),))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(f"Cleaned up {deleted} old metric records")
        return deleted


class MetricsCollector:
    def __init__(self, db: MetricsDB):
        self.db = db
        self.session = None
        self.collection_interval = 15  # seconds
        self.running = False

    async def start(self):
        """Start the metrics collection loop"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        self.running = True

        # Start collection loop in background
        asyncio.create_task(self.collection_loop())

    async def stop(self):
        """Stop the metrics collection"""
        self.running = False
        if self.session:
            await self.session.close()

    async def collection_loop(self):
        """Main collection loop"""
        while self.running:
            try:
                hosts = self.db.get_active_hosts()
                if hosts:
                    await self.collect_from_hosts(hosts)
                await asyncio.sleep(self.collection_interval)
            except Exception as e:
                logger.error(f"Error in collection loop: {e}")
                await asyncio.sleep(5)

    async def collect_from_hosts(self, hosts: List[Dict]):
        """Collect metrics from all active hosts"""
        tasks = []
        for host in hosts:
            task = asyncio.create_task(
                self.collect_from_host(host['hostname'], host['port'])
            )
            tasks.append(task)

        # Wait for all collections to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def collect_from_host(self, hostname: str, port: int):
        """Collect metrics from a single host"""
        try:
            url = f"http://localhost:{port}/metrics"
            async with self.session.get(url) as response:
                if response.status == 200:
                    text = await response.text()
                    metrics = self.parse_prometheus_metrics(text, hostname)
                    if metrics:
                        self.db.insert_metrics(metrics)
                        self.db.update_host_status(hostname, port, 'active')
                        logger.debug(f"Collected {len(metrics)} metrics from {hostname}")
                else:
                    logger.warning(f"Failed to collect from {hostname}:{port} - HTTP {response.status}")
                    self.db.update_host_status(hostname, port, 'error')
        except Exception as e:
            logger.error(f"Error collecting from {hostname}:{port}: {e}")
            self.db.update_host_status(hostname, port, 'error')

    def parse_prometheus_metrics(self, text: str, hostname: str) -> List[MetricPoint]:
        """Parse Prometheus format metrics"""
        metrics = []
        timestamp = datetime.now()

        for line in text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            try:
                # Parse metric line: metric_name{label1="value1",label2="value2"} value
                if '{' in line:
                    # Metric with labels
                    match = re.match(r'([^{]+)\{([^}]*)\}\s+(.+)', line)
                    if match:
                        metric_name = match.group(1)
                        labels_str = match.group(2)
                        value = float(match.group(3))

                        # Parse labels
                        labels = {}
                        for label_pair in labels_str.split(','):
                            if '=' in label_pair:
                                key, val = label_pair.split('=', 1)
                                labels[key.strip()] = val.strip().strip('"')
                else:
                    # Metric without labels
                    parts = line.split()
                    if len(parts) >= 2:
                        metric_name = parts[0]
                        value = float(parts[1])
                        labels = {}

                metrics.append(MetricPoint(
                    timestamp=timestamp,
                    hostname=hostname,
                    metric_name=metric_name,
                    labels=labels,
                    value=value
                ))
            except (ValueError, AttributeError) as e:
                logger.debug(f"Failed to parse metric line: {line} - {e}")
                continue

        return metrics


# FastAPI application
db = MetricsDB()
collector = MetricsCollector(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await collector.start()

    # Start cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())

    yield

    # Shutdown
    await collector.stop()
    cleanup_task.cancel()


app = FastAPI(title="Lightweight Monitoring Server", lifespan=lifespan)


async def periodic_cleanup():
    """Periodic cleanup of old data"""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            db.cleanup_old_data(days=7)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")


# API Routes
@app.get("/")
async def root():
    """Root endpoint with basic info"""
    hosts = db.get_active_hosts()
    return {
        "service": "Lightweight Monitoring Server",
        "active_hosts": len(hosts),
        "hosts": hosts
    }


@app.post("/register/{hostname}")
async def register_host(hostname: str, port: int = Query(..., description="Port number for metrics endpoint")):
    """Register a new host for monitoring"""
    db.update_host_status(hostname, port, 'active')
    return {"message": f"Host {hostname} registered successfully on port {port}"}


@app.get("/hosts")
async def list_hosts():
    """List all active hosts"""
    return {"hosts": db.get_active_hosts()}


@app.get("/metrics/{hostname}")
async def get_host_metrics(hostname: str, hours: int = Query(1, description="Hours of data to retrieve")):
    """Get latest metrics for a specific host"""
    metrics = db.get_latest_metrics(hostname, hours)
    return {"hostname": hostname, "metrics": metrics, "count": len(metrics)}


@app.get("/metrics/{hostname}/{metric_name}")
async def get_metric_history(
        hostname: str,
        metric_name: str,
        hours: int = Query(24, description="Hours of historical data")
):
    """Get time series data for a specific metric"""
    data = db.get_metric_history(hostname, metric_name, hours)
    return {
        "hostname": hostname,
        "metric_name": metric_name,
        "data": data,
        "count": len(data)
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Simple web dashboard"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Monitoring Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .host { border: 1px solid #ddd; margin: 10px 0; padding: 10px; border-radius: 5px; }
            .active { background-color: #d4edda; }
            .error { background-color: #f8d7da; }
            .metric { margin: 5px 0; padding: 5px; background-color: #f8f9fa; border-radius: 3px; }
        </style>
        <script>
            async function loadDashboard() {
                const response = await fetch('/hosts');
                const data = await response.json();
                const container = document.getElementById('hosts');

                container.innerHTML = '';
                for (const host of data.hosts) {
                    const hostDiv = document.createElement('div');
                    hostDiv.className = `host ${host.status}`;
                    hostDiv.innerHTML = `
                        <h3>${host.hostname}</h3>
                        <p>Port: ${host.port} | Status: ${host.status} | Last seen: ${host.last_seen}</p>
                        <button onclick="loadMetrics('${host.hostname}')">View Metrics</button>
                    `;
                    container.appendChild(hostDiv);
                }
            }

            async function loadMetrics(hostname) {
                const response = await fetch(`/metrics/${hostname}?hours=1`);
                const data = await response.json();
                alert(`${hostname} has ${data.count} metrics in the last hour`);
            }

            setInterval(loadDashboard, 30000); // Refresh every 30 seconds
            window.onload = loadDashboard;
        </script>
    </head>
    <body>
        <h1>Monitoring Dashboard</h1>
        <div id="hosts"></div>
    </body>
    </html>
    """


if __name__ == "__main__":
    # uvicorn.run(app, host="0.0.0.0", port=8000)
    uvicorn.run(app, host="localhost", port=8000)