#!/usr/bin/env python3
"""
dcmon Database Models — Peewee with default primary keys

Paradigm: Client ↔ Server
- Canonical identity: Client.id (Peewee's default INTEGER PRIMARY KEY AUTOINCREMENT)
- Credential: client_token (TEXT UNIQUE)
- Crypto: public_key (PEM stored for verification)
- Metrics: either value_float or value_int set (XOR enforced)

Notes:
- We use ForeignKeyField for relations; SQLite FK enforcement is turned ON at connect().
- Idempotent metric inserts are ensured by a UNIQUE index on (client, timestamp, metric_name).
"""

import time
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

import peewee
from peewee import (
    Model, SqliteDatabase, CharField, IntegerField, FloatField, TextField,
    ForeignKeyField, Check
)
from playhouse.sqlite_ext import JSONField

logger = logging.getLogger("dcmon.models")

# Global DB handle (initialized in DatabaseManager.connect)
database = SqliteDatabase(None)


class BaseModel(Model):
    class Meta:
        database = database
        legacy_table_names = False


class Client(BaseModel):
    """Client registration & authentication (id added implicitly by Peewee)."""
    client_token = CharField(unique=True)
    hostname = CharField(null=True)
    last_seen = IntegerField(null=True)
    status = CharField(default="active")
    public_key = TextField(null=True)   # PEM (server verifies signatures with this)
    created_at = IntegerField()
    
    # System identification
    machine_id = CharField(unique=True)  # /etc/machine-id for duplicate prevention
    hw_hash = CharField(null=True)       # Hardware fingerprint for change detection
    
    # Hardware inventory fields
    mdb_name = CharField(null=True)      # Motherboard name
    cpu_name = CharField(null=True)      # CPU model name  
    gpu_name = CharField(null=True)      # Primary GPU name
    gpu_count = IntegerField(null=True)  # Number of GPUs
    ram_gb = IntegerField(null=True)     # Total RAM in GB
    cpu_cores = IntegerField(null=True)  # Number of CPU cores
    drives = JSONField(null=True)        # JSON array of all drives
    
    # Vast.ai specific fields
    vast_machine_id = CharField(null=True)  # Vast.ai machine ID from /var/lib/vastai_kaalia/machine_id
    vast_port_range = CharField(null=True)  # Vast.ai port range from /var/lib/vastai_kaalia/host_port_range

    class Meta:
        indexes = (
            (("last_seen",), False),  # helpful for dashboards
        )

    @classmethod
    def get_by_token(cls, token: str) -> Optional["Client"]:
        try:
            return cls.get(cls.client_token == token)
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_by_machine_id(cls, machine_id: str) -> Optional["Client"]:
        try:
            return cls.get(cls.machine_id == machine_id)
        except cls.DoesNotExist:
            return None

    def update_last_seen(self, ts: Optional[int] = None) -> None:
        self.last_seen = ts or int(time.time())
        self.save()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_id": self.id,
            "hostname": self.hostname,
            "last_seen": self.last_seen,
            "status": self.status,
            "created_at": self.created_at,
            "machine_id": self.machine_id,
            "hw_hash": self.hw_hash,
            # Hardware inventory
            "mdb_name": self.mdb_name,
            "cpu_name": self.cpu_name,
            "gpu_name": self.gpu_name,
            "gpu_count": self.gpu_count,
            "ram_gb": self.ram_gb,
            "cpu_cores": self.cpu_cores,
            "drives": self.drives,
            # Vast.ai fields
            "vast_machine_id": self.vast_machine_id,
            "vast_port_range": self.vast_port_range,
        }


class MetricSeries(BaseModel):
    """
    Metric series definitions.
    
    Each unique combination of (client, metric_name, labels) gets one series record.
    This normalizes the schema to avoid duplicating metric definitions.
    """
    client = ForeignKeyField(Client, backref="metric_series", on_delete="CASCADE", index=True)
    metric_name = CharField()
    labels_hash = CharField()  # Hash of labels for uniqueness
    labels = TextField(null=True)  # JSON for display/filtering
    value_type = CharField()  # "int" or "float"
    created_at = IntegerField()

    class Meta:
        indexes = (
            (("client", "metric_name"), False),
            (("client", "metric_name", "labels_hash"), True),  # UNIQUE series definition
        )

    @classmethod
    def get_or_create_series(
        cls, 
        client_id: int, 
        metric_name: str, 
        labels: Optional[str], 
        value_type: str
    ) -> "MetricSeries":
        """Get existing series or create new one."""
        import hashlib
        import json
        
        # Create consistent hash of labels
        if labels:
            labels_dict = json.loads(labels) if isinstance(labels, str) else labels
            labels_str = json.dumps(labels_dict, sort_keys=True, separators=(',', ':'))
        else:
            labels_str = ""
        labels_hash = hashlib.md5(labels_str.encode()).hexdigest()[:16]
        
        try:
            return cls.get(
                (cls.client == client_id) & 
                (cls.metric_name == metric_name) & 
                (cls.labels_hash == labels_hash)
            )
        except cls.DoesNotExist:
            return cls.create(
                client=client_id,
                metric_name=metric_name,
                labels_hash=labels_hash,
                labels=labels_str if labels_str else None,
                value_type=value_type,
                created_at=int(time.time())
            )


class MetricPointsInt(BaseModel):
    """Integer metric points (about 70% of data)."""
    series = ForeignKeyField(MetricSeries, backref="int_points", on_delete="CASCADE", index=True)
    timestamp = IntegerField()
    value = IntegerField()

    class Meta:
        primary_key = False  # Use composite primary key
        constraints = [
            # Composite primary key for uniqueness and performance
        ]
        indexes = (
            (("series", "timestamp"), True),  # PRIMARY KEY equivalent
            (("timestamp",), False),  # For time-range queries
        )

    @classmethod
    def cleanup_old_data(cls, days_to_keep: int = 7) -> int:
        cutoff = int(time.time()) - days_to_keep * 24 * 3600
        deleted = cls.delete().where(cls.timestamp < cutoff).execute()
        logger.info(f"int metrics cleanup: removed {deleted} rows (< {days_to_keep}d)")
        return deleted


class MetricPointsFloat(BaseModel):
    """Float metric points (about 30% of data)."""
    series = ForeignKeyField(MetricSeries, backref="float_points", on_delete="CASCADE", index=True)
    timestamp = IntegerField()
    value = FloatField()

    class Meta:
        primary_key = False  # Use composite primary key
        constraints = [
            # Composite primary key for uniqueness and performance
        ]
        indexes = (
            (("series", "timestamp"), True),  # PRIMARY KEY equivalent  
            (("timestamp",), False),  # For time-range queries
        )

    @classmethod
    def cleanup_old_data(cls, days_to_keep: int = 7) -> int:
        cutoff = int(time.time()) - days_to_keep * 24 * 3600
        deleted = cls.delete().where(cls.timestamp < cutoff).execute()
        logger.info(f"float metrics cleanup: removed {deleted} rows (< {days_to_keep}d)")
        return deleted



class LogEntry(BaseModel):
    """Client log entries for troubleshooting."""
    client = ForeignKeyField(Client, backref="log_entries", on_delete="CASCADE", index=True)
    log_source = CharField()  # 'dmesg', 'journal', 'syslog'
    log_timestamp = IntegerField()  # Original log entry timestamp
    received_timestamp = IntegerField()  # When server received it
    content = TextField()  # Raw log line
    severity = CharField(null=True)  # 'ERROR', 'WARN', 'INFO', 'DEBUG'

    class Meta:
        indexes = (
            (("client", "log_source", "log_timestamp"), False),
            (("client", "severity"), False),  # For severity filtering
            (("received_timestamp",), False),  # For cleanup queries
        )

    @classmethod
    def cleanup_old_logs(cls, days_to_keep: int = 7) -> int:
        """Remove old log entries beyond retention period."""
        cutoff = int(time.time()) - days_to_keep * 24 * 3600
        deleted = cls.delete().where(cls.received_timestamp < cutoff).execute()
        logger.info(f"log cleanup: removed {deleted} entries (< {days_to_keep}d)")
        return deleted

    @classmethod
    def get_logs_for_client(cls, client_id: int, limit: int = 1000, 
                           log_source: Optional[str] = None,
                           severity: Optional[str] = None,
                           start_time: Optional[int] = None,
                           end_time: Optional[int] = None) -> List["LogEntry"]:
        """Query logs for a client with filtering."""
        query = cls.select().where(cls.client == client_id)
        
        if log_source:
            query = query.where(cls.log_source == log_source)
        if severity:
            query = query.where(cls.severity == severity)
        if start_time:
            query = query.where(cls.log_timestamp >= start_time)
        if end_time:
            query = query.where(cls.log_timestamp <= end_time)
            
        return list(query.order_by(cls.log_timestamp.desc()).limit(limit))

    @classmethod
    def get_recent_logs_by_source(cls, client_id: int, log_source: str, limit: int = 50) -> List["LogEntry"]:
        """Get recent logs for a specific client and log source."""
        return list(
            cls.select()
            .where((cls.client == client_id) & (cls.log_source == log_source))
            .order_by(cls.log_timestamp.desc())
            .limit(limit)
        )

    @classmethod
    def get_log_counts_by_source(cls, client_id: int, since_timestamp: Optional[int] = None) -> Dict[str, int]:
        """Get log entry counts by source for a client, optionally since a timestamp."""
        query = cls.select(cls.log_source, peewee.fn.COUNT(cls.id).alias('count')).where(cls.client == client_id)
        
        if since_timestamp:
            query = query.where(cls.log_timestamp >= since_timestamp)
            
        results = query.group_by(cls.log_source)
        return {row.log_source: row.count for row in results}


class DatabaseManager:
    """DB lifecycle + minimal convenience ops."""

    def __init__(self, db_path: str = "/var/lib/dcmon/dcmon.db") -> None:
        self.db_path = Path(db_path)
        self.connected = False

    def connect(self) -> bool:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            database.init(str(self.db_path))
            database.connect(reuse_if_open=True)

            # SQLite pragmas for reliability/perf
            database.execute_sql("PRAGMA foreign_keys=ON;")
            database.execute_sql("PRAGMA journal_mode=WAL;")
            database.execute_sql("PRAGMA synchronous=NORMAL;")
            database.execute_sql("PRAGMA cache_size=10000;")
            database.execute_sql("PRAGMA temp_store=MEMORY;")

            database.create_tables([Client, MetricSeries, MetricPointsInt, MetricPointsFloat, LogEntry], safe=True)
            self.connected = True
            logger.info(f"database initialized: {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"database init failed: {e}")
            return False

    def close(self) -> None:
        if self.connected:
            database.close()
            self.connected = False
            logger.info("database connection closed")

    # ---- convenience API used by the app ----

    @staticmethod
    def register_client(
        *, 
        hostname: Optional[str], 
        client_token: str, 
        machine_id: str,
        hw_hash: Optional[str] = None,
        public_key: Optional[str] = None,
        # Hardware inventory fields
        mdb_name: Optional[str] = None,
        cpu_name: Optional[str] = None,
        gpu_name: Optional[str] = None,
        gpu_count: Optional[int] = None,
        ram_gb: Optional[int] = None,
        cpu_cores: Optional[int] = None,
        drives: Optional[List[Dict[str, Any]]] = None,
        # Vast.ai specific fields
        vast_machine_id: Optional[str] = None,
        vast_port_range: Optional[str] = None,
    ) -> Optional[int]:
        """
        Register a new client with hardware inventory.
        Returns the new client_id (int) or None on failure.
        """
        try:
            now = int(time.time())
            client = Client.create(
                client_token=client_token,
                hostname=hostname,
                machine_id=machine_id,
                hw_hash=hw_hash,
                last_seen=now,
                status="active",
                public_key=public_key,
                created_at=now,
                # Hardware fields
                mdb_name=mdb_name,
                cpu_name=cpu_name,
                gpu_name=gpu_name,
                gpu_count=gpu_count,
                ram_gb=ram_gb,
                cpu_cores=cpu_cores,
                drives=drives,
                # Vast.ai fields
                vast_machine_id=vast_machine_id,
                vast_port_range=vast_port_range,
            )
            return int(client.id)
        except Exception as e:
            logger.error(f"register_client failed: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        try:
            return {
                "clients_total": Client.select().count(),
                "clients_active": Client.select().where(Client.status == "active").count(),
                "metric_series_total": MetricSeries.select().count(),
                "metric_points_int": MetricPointsInt.select().count(),
                "metric_points_float": MetricPointsFloat.select().count(),
                "database_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 2)
                if self.db_path.exists() else 0,
            }
        except Exception as e:
            logger.error(f"get_stats failed: {e}")
            return {}


# Global manager accessor
db_manager = DatabaseManager()


def get_db() -> DatabaseManager:
    return db_manager


if __name__ == "__main__":
    # Smoke test in a temp db
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
        mgr = DatabaseManager(tmp.name)
        assert mgr.connect()
        cid = mgr.register_client(hostname="host-a", client_token="tok-123", public_key="PEM...")
        # Test new schema
        series = MetricSeries.get_or_create_series(cid, "cpu_temp_c", None, "float")
        MetricPointsFloat.create(series=series, timestamp=int(time.time()), value=51.7)
        stats = mgr.get_stats()
        mgr.close()
