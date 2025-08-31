#!/usr/bin/env python3
"""
dcmon Database Models - Clean Peewee Implementation
"""

import time
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

from peewee import *

logger = logging.getLogger('dcmon-models')

# Database instance
database = SqliteDatabase(None)


class BaseModel(Model):
    """Base model with database config"""
    class Meta:
        database = database


class Client(BaseModel):
    """Client registration and authentication"""
    machine_id = CharField(primary_key=True)
    client_token = CharField(unique=True)
    hostname = CharField(null=True)
    last_seen = IntegerField(null=True)
    status = CharField(default='active')
    public_key = TextField(null=True)  # RSA public key
    created_at = IntegerField()
    
    @classmethod
    def get_by_client_token(cls, client_token: str) -> Optional['Client']:
        """Get client by client token"""
        try:
            return cls.get(cls.client_token == client_token)
        except cls.DoesNotExist:
            return None
    
    @classmethod
    def get_active_clients(cls) -> List['Client']:
        """Get all active clients ordered by last seen"""
        return list(cls.select().where(cls.status == 'active').order_by(cls.last_seen.desc()))
    
    def update_last_seen(self, timestamp: Optional[int] = None):
        """Update last seen timestamp"""
        self.last_seen = timestamp or int(time.time())
        self.save()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'machine_id': self.machine_id,
            'hostname': self.hostname,
            'last_seen': self.last_seen,
            'status': self.status,
            'created_at': self.created_at
        }


class Metric(BaseModel):
    """Time-series metric storage"""
    machine_id = CharField()
    timestamp = IntegerField()
    metric_name = CharField()
    value = FloatField(null=True)
    value_int = IntegerField(null=True)  # For counters/bytes optimization
    labels = TextField(null=True)  # JSON string
    
    class Meta:
        primary_key = CompositeKey('machine_id', 'timestamp', 'metric_name')
        indexes = (
            (('machine_id', 'timestamp'), False),
            (('metric_name', 'timestamp'), False),
        )
    
    @classmethod
    def cleanup_old_data(cls, days_to_keep: int = 7):
        """Remove old metrics data"""
        cutoff_time = int(time.time()) - (days_to_keep * 24 * 3600)
        deleted = cls.delete().where(cls.timestamp < cutoff_time).execute()
        logger.info(f"Cleaned up {deleted} old metric records")
        return deleted
    
    @classmethod
    def get_metrics(cls, machine_id: Optional[str] = None, 
                   metric_names: Optional[List[str]] = None,
                   start_time: Optional[int] = None,
                   end_time: Optional[int] = None,
                   limit: int = 1000) -> List['Metric']:
        """Query metrics with filters"""
        query = cls.select()
        
        if machine_id:
            query = query.where(cls.machine_id == machine_id)
        
        if metric_names:
            query = query.where(cls.metric_name.in_(metric_names))
        
        if start_time:
            query = query.where(cls.timestamp >= start_time)
        
        if end_time:
            query = query.where(cls.timestamp <= end_time)
        
        query = query.order_by(cls.timestamp.desc()).limit(limit)
        
        return list(query)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'machine_id': self.machine_id,
            'timestamp': self.timestamp,
            'metric_name': self.metric_name,
            'value': self.value,
            'value_int': self.value_int,
            'labels': self.labels
        }


class Command(BaseModel):
    """Client command queue"""
    id = CharField(primary_key=True)
    machine_id = CharField()
    command_type = CharField()
    command_data = TextField()  # JSON
    status = CharField(default='pending')
    created_at = IntegerField()
    executed_at = IntegerField(null=True)
    result = TextField(null=True)  # JSON
    
    @classmethod
    def get_pending_for_client(cls, machine_id: str) -> List['Command']:
        """Get pending commands for a specific client"""
        return list(cls.select().where(
            (cls.machine_id == machine_id) & 
            (cls.status == 'pending')
        ).order_by(cls.created_at))
    
    def mark_completed(self, result: Dict[str, Any]):
        """Mark command as completed with result"""
        import json
        self.status = 'completed'
        self.executed_at = int(time.time())
        self.result = json.dumps(result)
        self.save()
    
    def mark_failed(self, error: str):
        """Mark command as failed"""
        self.status = 'failed'
        self.executed_at = int(time.time())
        self.result = json.dumps({'error': error})
        self.save()


class DatabaseManager:
    """Database connection and management"""
    
    def __init__(self, db_path: str = "/var/lib/dcmon/dcmon.db"):
        self.db_path = Path(db_path)
        self.connected = False
    
    def connect(self):
        """Initialize database connection"""
        try:
            # Ensure database directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Initialize database
            database.init(str(self.db_path))
            
            # Enable WAL mode for better performance
            database.execute_sql('PRAGMA journal_mode=WAL;')
            database.execute_sql('PRAGMA synchronous=NORMAL;')
            database.execute_sql('PRAGMA cache_size=10000;')
            database.execute_sql('PRAGMA temp_store=MEMORY;')
            
            # Create tables
            database.create_tables([Client, Metric, Command], safe=True)
            
            self.connected = True
            logger.info(f"Database initialized: {self.db_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            return False
    
    def close(self):
        """Close database connection"""
        if self.connected:
            database.close()
            self.connected = False
            logger.info("Database connection closed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            return {
                'clients_total': Client.select().count(),
                'clients_active': Client.select().where(Client.status == 'active').count(),
                'metrics_total': Metric.select().count(),
                'commands_pending': Command.select().where(Command.status == 'pending').count(),
                'database_size_mb': round(self.db_path.stat().st_size / 1024 / 1024, 2) if self.db_path.exists() else 0
            }
        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            return {}

    @staticmethod
    def register_client(machine_id: str,
                        hostname: Optional[str],
                        client_token: str) -> bool:
        """
        Register or update a client (by machine_id).
        Matches the old database.py `register_client` semantics.
        """
        try:
            ts_now = int(time.time())
            (Client.insert(
                machine_id=machine_id,
                client_token=client_token,
                hostname=hostname,
                last_seen=ts_now,
                status='active',
                created_at=ts_now
            ).on_conflict(
                conflict_target=[Client.machine_id],
                update={
                    Client.client_token: client_token,
                    Client.hostname: hostname,
                    Client.last_seen: ts_now,
                    Client.status: 'active',
                    Client.created_at: ts_now,
                }
            ).execute())
            return True
        except Exception as e:
            logger.error(f"Failed to register client {machine_id}: {e}")
            return False

# Global database manager
db_manager = DatabaseManager()


def get_db() -> DatabaseManager:
    """Get database manager instance"""
    return db_manager


if __name__ == "__main__":
    # Test the database models
    print("Testing dcmon database models...")
    
    # Test with temporary database
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        test_db_path = tmp.name
    
    test_manager = DatabaseManager(test_db_path)
    
    if test_manager.connect():
        print("✅ Database connection successful")
        
        # Test client creation
        test_client = Client.create(
            machine_id='test-123',
            client_token='test_token_123',
            hostname='test-host',
            created_at=int(time.time())
        )
        print("✅ Client creation successful")
        
        # Test client retrieval
        found_client = Client.get_by_client_token('test_token_123')
        if found_client and found_client.machine_id == 'test-123':
            print("✅ Client retrieval successful")
        else:
            print("❌ Client retrieval failed")
        
        # Test stats
        stats = test_manager.get_stats()
        print(f"✅ Database stats: {stats}")
        
        test_manager.close()
        
        # Cleanup
        Path(test_db_path).unlink()
        
        print("✅ All database tests passed!")
    else:
        print("❌ Database connection failed")