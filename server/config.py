#!/usr/bin/env python3
"""
Simple configuration loader for dcmon server using dataclasses
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger('dcmon-config')

@dataclass
class Config:
    """dcmon server configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    database_path: str = "/var/lib/dcmon/dcmon.db"
    admin_token_file: str = "/etc/dcmon-server/admin_token"
    log_level: str = "INFO"
    metrics_days: int = 30
    cleanup_interval: int = 3600
    test_mode: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Config':
        """Create Config from dictionary, using defaults for missing values"""
        # Filter only known fields to avoid dataclass errors
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        
        return cls(**filtered_data)

def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from YAML file with simple fallbacks
    
    Priority:
    1. Provided config_path
    2. Environment variable DCMON_CONFIG
    3. ./config_test.yaml (if exists)
    4. ./config.yaml (if exists)
    5. /etc/dcmon-server/config.yaml (if exists)
    6. Defaults
    """
    
    # Determine config file to use
    if config_path:
        config_files = [config_path]
    else:
        config_files = [
            os.environ.get('DCMON_CONFIG'),
            './config_test.yaml',
            './config.yaml',
            '/etc/dcmon-server/config.yaml'
        ]
    
    # Try to load from files
    for config_file in config_files:
        if not config_file:
            continue
            
        config_file = Path(config_file)
        if config_file.exists():
            try:
                logger.info(f"Loading configuration from: {config_file}")
                with open(config_file, 'r') as f:
                    data = yaml.safe_load(f)
                    if data:
                        return Config.from_dict(data)
            except Exception as e:
                logger.warning(f"Failed to load config from {config_file}: {e}")
                continue
    
    # Using defaults
    logger.info("Using default configuration")
    return Config()

# Global config instance
_config: Optional[Config] = None

def get_config() -> Config:
    """Get global configuration instance"""
    global _config
    if _config is None:
        _config = load_config()
    return _config

if __name__ == "__main__":
    # Test configuration loading
    print("Testing configuration loading...")
    
    config = load_config()
    print(f"Server: {config.host}:{config.port}")
    print(f"Database: {config.database_path}")
    print(f"Admin token file: {config.admin_token_file}")
    print(f"Test mode: {config.test_mode}")
    print(f"Log level: {config.log_level}")
    print(f"Metrics retention: {config.metrics_days} days")
    print(f"Cleanup interval: {config.cleanup_interval} seconds")