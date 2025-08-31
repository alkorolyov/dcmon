#!/usr/bin/env python3
"""
dcmon Server - Clean V2 Implementation with Peewee
Simplified version focusing on V2 authentication
"""

import logging

from fastapi import FastAPI
from contextlib import asynccontextmanager

from models import DatabaseManager, get_db
from config import Config, load_config
from routes import create_routes, create_auth_dependency

# Logger will be configured in main()
logger = logging.getLogger('dcmon-server')

# Load admin token from config
def load_admin_token(config: Config) -> str:
    """Load admin token from file or use test token"""
    # Check if we should use test token (empty file path or test mode)
    if not config.admin_token_file or config.test_mode:
        logger.warning("Using test admin token (test mode or no file configured)")
        return "dcmon_admin_test123"
    
    try:
        with open(config.admin_token_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning(f"Admin token file not found: {config.admin_token_file}, using test token")
        return "dcmon_admin_test123"
    except Exception as e:
        logger.error(f"Failed to load admin token: {e}")
        return "dcmon_admin_test123"





def create_lifespan(config: Config):
    """Create lifespan manager with the given config"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage database lifecycle"""
        # Startup
        from models import DatabaseManager
        
        db_path = config.database_path
        global db_manager
        db_manager = DatabaseManager(db_path)
        
        if not db_manager.connect():
            raise RuntimeError("Failed to initialize database")
        logger.info(f"dcmon server V2 started with database: {db_path}")
        
        yield
        
        # Shutdown
        db_manager = get_db()
        db_manager.close()
        logger.info("dcmon server V2 stopped")
    return lifespan

def create_app(config: Config) -> FastAPI:
    """Create FastAPI app with the given configuration"""
    global get_admin_auth, ADMIN_TOKEN
    
    admin_token = load_admin_token(config)
    logger.info("Admin token loaded successfully")
    
    # Set global variables for routes
    ADMIN_TOKEN = admin_token
    get_admin_auth = create_auth_dependency(admin_token)
    lifespan = create_lifespan(config)
    
    # FastAPI app with lifespan and conditional docs
    app = FastAPI(
        title="dcmon Server V2",
        description="Datacenter Monitoring Server",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if config.test_mode else None,
        redoc_url="/redoc" if config.test_mode else None,
        openapi_url="/openapi.json" if config.test_mode else None
    )
    
    # Include routes
    router = create_routes(admin_token)
    app.include_router(router)
    return app

def main(config_file: str = "config.yaml"):
    """Main entry point for the server"""
    # Set up basic logging first
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load config
    config = load_config(config_file)
    
    # Update logging level based on config
    log_level = getattr(logging, config.log_level.upper())
    logging.getLogger().setLevel(log_level)
    
    logger.info(f"Starting dcmon server on {config.host}:{config.port}")
    logger.info(f"Database: {config.database_path}")
    logger.info(f"Test mode: {config.test_mode}")
    
    # Create and run the app
    app = create_app(config)
    
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="dcmon Server")
    parser.add_argument("-c", "--config", default="config.yaml", help="Configuration file path")
    args = parser.parse_args()
    
    main(args.config)

