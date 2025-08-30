#!/usr/bin/env python3
"""
dcmon Server Database Module
SQLite database setup and management
"""

import aiosqlite
import asyncio
import logging
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class MetricPoint:
    """Metric data point"""
    machine_id: str
    timestamp: int
    metric_name: str
    value: float
    value_int: Optional[int] = None
    labels: Optional[str] = None

@dataclass 
class Client:
    """Client registration info"""
    machine_id: str
    api_key: str
    hostname: Optional[str] = None
    last_seen: Optional[int] = None
    status: str = 'active'
    client_info: Optional[str] = None
    created_at: Optional[int] = None

@dataclass
class Command:
    """Command for client execution"""
    id: str
    machine_id: str
    command_type: str
    command_data: str  # JSON string
    status: str = 'pending'
    created_at: Optional[int] = None
    executed_at: Optional[int] = None
    result: Optional[str] = None

class Database:
    """SQLite database manager"""
    
    def __init__(self, db_path: str = "/var/lib/dcmon/dcmon.db"):
        self.db_path = db_path
        self.connection = None
        
        # Ensure database directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    async def connect(self):
        """Connect to database and initialize schema"""
        self.connection = await aiosqlite.connect(
            self.db_path,
            timeout=30.0
        )
        
        # Enable WAL mode for better concurrency
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA synchronous=NORMAL")
        await self.connection.execute("PRAGMA cache_size=10000")
        await self.connection.execute("PRAGMA temp_store=MEMORY")
        
        await self._create_tables()
        logger.info(f"Database connected: {self.db_path}")
    
    async def close(self):
        """Close database connection"""
        if self.connection:
            await self.connection.close()
            self.connection = None
    
    async def _create_tables(self):
        """Create database tables if they don't exist"""
        
        # Clients table
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                machine_id TEXT PRIMARY KEY,
                api_key TEXT NOT NULL UNIQUE,
                hostname TEXT,
                last_seen INTEGER,
                status TEXT DEFAULT 'active',
                client_info TEXT,  -- JSON
                created_at INTEGER NOT NULL
            )
        """)
        
        # Metrics table - optimized for time-series data
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                machine_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL,
                value_int INTEGER,
                labels TEXT,  -- JSON
                PRIMARY KEY (machine_id, timestamp, metric_name)
            )
        """)
        
        # Metrics catalog for tracking available metrics per client
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS client_metrics_catalog (
                machine_id TEXT,
                metric_name TEXT,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                data_type TEXT,  -- 'integer', 'float'
                PRIMARY KEY (machine_id, metric_name)
            )
        """)
        
        # Commands table
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                command_type TEXT NOT NULL,
                command_data TEXT NOT NULL,  -- JSON
                status TEXT DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                executed_at INTEGER,
                result TEXT  -- JSON
            )
        """)
        
        # Create indexes for better query performance
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_time 
            ON metrics(timestamp)
        """)
        
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_machine_time 
            ON metrics(machine_id, timestamp)
        """)
        
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_name_time 
            ON metrics(metric_name, timestamp)
        """)
        
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_commands_machine_status 
            ON commands(machine_id, status)
        """)
        
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_clients_last_seen 
            ON clients(last_seen)
        """)
        
        await self.connection.commit()
        logger.info("Database schema initialized")
    
    # Client management methods
    async def register_client(self, client: Client) -> bool:
        """Register a new client"""
        try:
            await self.connection.execute("""
                INSERT OR REPLACE INTO clients 
                (machine_id, api_key, hostname, last_seen, status, client_info, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                client.machine_id,
                client.api_key, 
                client.hostname,
                client.last_seen or int(time.time()),
                client.status,
                client.client_info,
                client.created_at or int(time.time())
            ))
            await self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to register client {client.machine_id}: {e}")
            return False
    
    async def get_client(self, machine_id: str) -> Optional[Client]:
        """Get client by machine_id"""
        try:
            async with self.connection.execute("""
                SELECT machine_id, api_key, hostname, last_seen, status, client_info, created_at
                FROM clients WHERE machine_id = ?
            """, (machine_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Client(*row)
                return None
        except Exception as e:
            logger.error(f"Failed to get client {machine_id}: {e}")
            return None
    
    async def get_client_by_api_key(self, api_key: str) -> Optional[Client]:
        """Get client by API key"""
        try:
            async with self.connection.execute("""
                SELECT machine_id, api_key, hostname, last_seen, status, client_info, created_at
                FROM clients WHERE api_key = ?
            """, (api_key,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Client(*row)
                return None
        except Exception as e:
            logger.error(f"Failed to get client by API key: {e}")
            return None
    
    async def update_client_last_seen(self, machine_id: str, timestamp: int = None):
        """Update client last seen timestamp"""
        if timestamp is None:
            timestamp = int(time.time())
        
        try:
            await self.connection.execute("""
                UPDATE clients SET last_seen = ? WHERE machine_id = ?
            """, (timestamp, machine_id))
            await self.connection.commit()
        except Exception as e:
            logger.error(f"Failed to update last seen for {machine_id}: {e}")
    
    async def get_all_clients(self) -> List[Client]:
        """Get all registered clients"""
        try:
            async with self.connection.execute("""
                SELECT machine_id, api_key, hostname, last_seen, status, client_info, created_at
                FROM clients ORDER BY last_seen DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [Client(*row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get clients: {e}")
            return []
    
    # Metrics storage methods
    async def store_metrics(self, metrics: List[MetricPoint]) -> bool:
        """Store multiple metrics efficiently"""
        if not metrics:
            return True
            
        try:
            # Prepare data for batch insert
            metrics_data = []
            catalog_updates = {}
            
            for metric in metrics:
                metrics_data.append((
                    metric.machine_id,
                    metric.timestamp,
                    metric.metric_name,
                    metric.value,
                    metric.value_int,
                    metric.labels
                ))
                
                # Track for catalog updates
                key = (metric.machine_id, metric.metric_name)
                if key not in catalog_updates:
                    catalog_updates[key] = {
                        'timestamp': metric.timestamp,
                        'data_type': 'integer' if metric.value_int is not None else 'float'
                    }
            
            # Batch insert metrics
            await self.connection.executemany("""
                INSERT OR REPLACE INTO metrics 
                (machine_id, timestamp, metric_name, value, value_int, labels)
                VALUES (?, ?, ?, ?, ?, ?)
            """, metrics_data)
            
            # Update metrics catalog
            for (machine_id, metric_name), info in catalog_updates.items():
                await self.connection.execute("""
                    INSERT OR REPLACE INTO client_metrics_catalog
                    (machine_id, metric_name, first_seen, last_seen, data_type)
                    VALUES (?, ?, 
                        COALESCE((SELECT first_seen FROM client_metrics_catalog 
                                 WHERE machine_id = ? AND metric_name = ?), ?),
                        ?, ?)
                """, (
                    machine_id, metric_name, machine_id, metric_name,
                    info['timestamp'], info['timestamp'], info['data_type']
                ))
            
            await self.connection.commit()
            return True
            
        except Exception as e:
            logger.error(f"Failed to store metrics: {e}")
            return False
    
    async def get_metrics(self, machine_id: str = None, metric_names: List[str] = None,
                         start_time: int = None, end_time: int = None,
                         limit: int = 1000) -> List[MetricPoint]:
        """Query metrics with filters"""
        try:
            conditions = []
            params = []
            
            if machine_id:
                conditions.append("machine_id = ?")
                params.append(machine_id)
            
            if metric_names:
                conditions.append(f"metric_name IN ({','.join(['?' for _ in metric_names])})")
                params.extend(metric_names)
            
            if start_time:
                conditions.append("timestamp >= ?")
                params.append(start_time)
            
            if end_time:
                conditions.append("timestamp <= ?")
                params.append(end_time)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            query = f"""
                SELECT machine_id, timestamp, metric_name, value, value_int, labels
                FROM metrics
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params.append(limit)
            
            async with self.connection.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [MetricPoint(*row) for row in rows]
                
        except Exception as e:
            logger.error(f"Failed to query metrics: {e}")
            return []
    
    # Command management methods
    async def create_command(self, command: Command) -> bool:
        """Create a new command"""
        try:
            await self.connection.execute("""
                INSERT INTO commands 
                (id, machine_id, command_type, command_data, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                command.id,
                command.machine_id,
                command.command_type,
                command.command_data,
                command.status,
                command.created_at or int(time.time())
            ))
            await self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to create command {command.id}: {e}")
            return False
    
    async def get_pending_commands(self, machine_id: str) -> List[Command]:
        """Get pending commands for a client"""
        try:
            async with self.connection.execute("""
                SELECT id, machine_id, command_type, command_data, status, created_at, executed_at, result
                FROM commands 
                WHERE machine_id = ? AND status = 'pending'
                ORDER BY created_at ASC
            """, (machine_id,)) as cursor:
                rows = await cursor.fetchall()
                return [Command(*row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get pending commands for {machine_id}: {e}")
            return []
    
    async def update_command_result(self, command_id: str, result: Dict[str, Any], 
                                   status: str = 'completed') -> bool:
        """Update command execution result"""
        try:
            await self.connection.execute("""
                UPDATE commands 
                SET result = ?, status = ?, executed_at = ?
                WHERE id = ?
            """, (
                json.dumps(result),
                status,
                int(time.time()),
                command_id
            ))
            await self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to update command result {command_id}: {e}")
            return False
    
    # Data cleanup methods
    async def cleanup_old_data(self, days_to_keep: int = 7):
        """Clean up old metrics data"""
        try:
            cutoff_time = int(time.time()) - (days_to_keep * 24 * 3600)
            
            # Delete old metrics
            await self.connection.execute("""
                DELETE FROM metrics WHERE timestamp < ?
            """, (cutoff_time,))
            
            # Delete old completed commands
            await self.connection.execute("""
                DELETE FROM commands 
                WHERE status IN ('completed', 'failed') AND created_at < ?
            """, (cutoff_time,))
            
            await self.connection.commit()
            logger.info(f"Cleaned up data older than {days_to_keep} days")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")

    async def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            stats = {}
            
            # Client count
            async with self.connection.execute("SELECT COUNT(*) FROM clients") as cursor:
                stats['total_clients'] = (await cursor.fetchone())[0]
            
            # Active clients (seen in last hour)
            cutoff = int(time.time()) - 3600
            async with self.connection.execute(
                "SELECT COUNT(*) FROM clients WHERE last_seen > ?", (cutoff,)
            ) as cursor:
                stats['active_clients'] = (await cursor.fetchone())[0]
            
            # Total metrics count
            async with self.connection.execute("SELECT COUNT(*) FROM metrics") as cursor:
                stats['total_metrics'] = (await cursor.fetchone())[0]
            
            # Pending commands
            async with self.connection.execute(
                "SELECT COUNT(*) FROM commands WHERE status = 'pending'"
            ) as cursor:
                stats['pending_commands'] = (await cursor.fetchone())[0]
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            return {}