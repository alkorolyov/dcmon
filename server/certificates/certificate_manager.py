#!/usr/bin/env python3
"""
SSL Certificate Management for dcmon Server
"""

import logging
import socket
import subprocess
import ssl
from pathlib import Path
from typing import Optional

logger = logging.getLogger("dcmon.server")


def detect_external_ip() -> str:
    """Detect current machine's external IP address."""
    try:
        # Try to get IP from hostname -I (most reliable for server IPs)
        result = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            # Get first IP from the output
            ip = result.stdout.strip().split()[0]
            if ip and ip != '127.0.0.1':
                return ip
    except Exception:
        pass
    
    try:
        # Fallback: connect to external host to determine our IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        pass
    
    return "127.0.0.1"


def generate_test_certificates(cert_path: Path, key_path: Path) -> bool:
    """Generate self-signed certificates for test mode."""
    try:
        external_ip = detect_external_ip()
        logger.info(f"Auto-generating test certificates for IP: {external_ip}")
        
        # Generate certificate with both external IP and localhost
        cmd = [
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', str(key_path), '-out', str(cert_path),
            '-days', '365', '-nodes', '-subj', '/CN=dcmon-server',
            '-addext', f'subjectAltName=IP:{external_ip},IP:127.0.0.1,DNS:localhost'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"Certificate generation failed: {result.stderr}")
            return False
        
        # Set proper permissions
        try:
            key_path.chmod(0o600)
            cert_path.chmod(0o644)
        except Exception as e:
            logger.warning(f"Failed to set certificate permissions: {e}")
        
        logger.info(f"Generated test certificates: cert={cert_path}, key={key_path}")
        return True
        
    except Exception as e:
        logger.error(f"Certificate generation error: {e}")
        return False


def get_ssl_context(use_tls: bool, test_mode: bool, cert_path: Path, key_path: Path) -> Optional[ssl.SSLContext]:
    """Create SSL context for HTTPS if TLS is enabled and certificates exist."""
    if not use_tls:
        return None
    
    cert_file = str(cert_path)
    key_file = str(key_path)
    
    # Check if certificate files exist
    if not cert_path.exists() or not key_path.exists():
        if test_mode:
            # Auto-generate certificates in test mode
            logger.info("Test mode: auto-generating HTTPS certificates")
            if not generate_test_certificates(cert_path, key_path):
                logger.warning("Failed to generate test certificates. Server will start without TLS.")
                return None
        else:
            # Production mode: require existing certificates
            logger.warning("TLS enabled but certificate files not found: cert=%s, key=%s", cert_file, key_file)
            logger.warning("Server will start without TLS. Generate certificates or set use_tls=false")
            return None
    
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_file, key_file)
    logger.info("TLS enabled with cert=%s, key=%s", cert_file, key_file)
    return ssl_context