#!/usr/bin/env python3
"""
dcmon FastAPI server — config-first, path-free, policy-enforced

This is the main entry point that creates and runs the dcmon server.
All functionality has been modularized for AI-friendly code navigation.
"""

import argparse
import uvicorn

# Support running as script or as package
try:
    from .core.config import load_config_from, resolve_paths
    from .core.server import create_app
    from .certificates.certificate_manager import get_ssl_context
except ImportError:
    from core.config import load_config_from, resolve_paths
    from core.server import create_app
    from certificates.certificate_manager import get_ssl_context


def main():
    """Main entry point for dcmon server."""
    parser = argparse.ArgumentParser(description="dcmon server")
    parser.add_argument("-c", "--config", help="Path to YAML config", default="config.yaml")
    args = parser.parse_args()

    # Load configuration
    config = load_config_from(args.config)
    
    # Resolve certificate paths for SSL context
    _, _, _, cert_path, key_path = resolve_paths(config)
    ssl_context = get_ssl_context(config.use_tls, config.test_mode, cert_path, key_path)
    
    # Create FastAPI app
    app = create_app(config)

    # Prepare uvicorn configuration
    uvicorn_kwargs = {
        "host": config.host,
        "port": config.port, 
        "reload": False,
        "access_log": False
    }
    
    # Add SSL parameters if TLS is enabled
    if ssl_context:
        uvicorn_kwargs.update({
            "ssl_keyfile": str(key_path),
            "ssl_certfile": str(cert_path)
        })
    
    # Run the server
    uvicorn.run(app, **uvicorn_kwargs)


if __name__ == "__main__":
    main()