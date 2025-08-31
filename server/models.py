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

from peewee import (
    Model, SqliteDatabase, CharField, IntegerField, FloatField, TextField,
    ForeignKeyField, Check
)

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
    
    # Hardware inventory fields
    mdb_name = CharField(null=True)      # Motherboard name
    cpu_name = CharField(null=True)      # CPU model name  
    gpu_name = CharField(null=True)      # Primary GPU name
    gpu_count = IntegerField(null=True)  # Number of GPUs
    ram_gb = IntegerField(null=True)     # Total RAM in GB
    cpu_cores = IntegerField(null=True)  # Number of CPU cores
    disk_name = CharField(null=True)     # Primary disk name
    disk_size = IntegerField(null=True)  # Primary disk size in GB

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
            # Hardware inventory
            "mdb_name": self.mdb_name,
            "cpu_name": self.cpu_name,
            "gpu_name": self.gpu_name,
            "gpu_count": self.gpu_count,
            "ram_gb": self.ram_gb,
            "cpu_cores": self.cpu_cores,
            "disk_name": self.disk_name,
            "disk_size": self.disk_size,
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


class Command(BaseModel):
    """Server→Client command queue."""
    client = ForeignKeyField(Client, backref="commands", on_delete="CASCADE", index=True)
    command_type = CharField()
    command_data = TextField()  # JSON
    status = CharField(default="pending")
    created_at = IntegerField()
    executed_at = IntegerField(null=True)
    result = TextField(null=True)  # JSON

    class Meta:
        indexes = (
            (("client", "status"), False),
        )

    @classmethod
    def get_pending_for_client(cls, client_id: int) -> List["Command"]:
        return list(
            cls.select()
              .where((cls.client == client_id) & (cls.status == "pending"))
              .order_by(cls.created_at)
        )

    def mark_completed(self, result: Dict[str, Any]) -> None:
        import json
        self.status = "completed"
        self.executed_at = int(time.time())
        self.result = json.dumps(result)
        self.save()

    def mark_failed(self, error: str) -> None:
        import json
        self.status = "failed"
        self.executed_at = int(time.time())
        self.result = json.dumps({"error": error})
        self.save()


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

            database.create_tables([Client, MetricSeries, MetricPointsInt, MetricPointsFloat, Command], safe=True)
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
        public_key: Optional[str] = None,
        # Hardware inventory fields
        mdb_name: Optional[str] = None,
        cpu_name: Optional[str] = None,
        gpu_name: Optional[str] = None,
        gpu_count: Optional[int] = None,
        ram_gb: Optional[int] = None,
        cpu_cores: Optional[int] = None,
        disk_name: Optional[str] = None,
        disk_size: Optional[int] = None,
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
                disk_name=disk_name,
                disk_size=disk_size,
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
                "commands_pending": Command.select().where(Command.status == "pending").count(),
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
        print("client_id:", cid)
        # Test new schema
        series = MetricSeries.get_or_create_series(cid, "cpu_temp_c", None, "float")
        MetricPointsFloat.create(series=series, timestamp=int(time.time()), value=51.7)
        pending = Command.get_pending_for_client(cid)
        print("pending commands:", len(pending))
        print("stats:", mgr.get_stats())
        mgr.close()
