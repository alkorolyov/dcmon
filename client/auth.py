#!/usr/bin/env python3
"""
dcmon Client Authentication System
Handles client key generation, storage, and server authentication
"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger('dcmon-client-auth')


class ClientAuth:
    """Client authentication handler using RSA key pairs"""
    
    def __init__(self, config_dir: Path = Path("/etc/dcmon")):
        self.config_dir = Path(config_dir)
        self.private_key_file = self.config_dir / "client.key"
        self.public_key_file = self.config_dir / "client.pub"
        self.token_file = self.config_dir / "client_token"
        
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography package is required but not installed")
    
    def generate_key_pair(self) -> bool:
        """Generate new RSA key pair for client authentication"""
        try:
            logger.info("Generating new RSA key pair...")
            
            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            
            # Get public key
            public_key = private_key.public_key()
            
            # Serialize private key
            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            # Serialize public key
            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            # Create config directory if it doesn't exist
            self.config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            
            # Write private key with restrictive permissions
            self.private_key_file.write_bytes(private_pem)
            self.private_key_file.chmod(0o600)
            
            # Write public key
            self.public_key_file.write_bytes(public_pem)
            self.public_key_file.chmod(0o644)
            
            logger.info("RSA key pair generated successfully")
            logger.info(f"Private key: {self.private_key_file}")
            logger.info(f"Public key: {self.public_key_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to generate key pair: {e}")
            return False
    
    def load_keys(self) -> Tuple[Optional[Any], Optional[str]]:
        """Load private key and public key from files"""
        try:
            if not self.private_key_file.exists() or not self.public_key_file.exists():
                return None, None
            
            # Load private key
            private_key_data = self.private_key_file.read_bytes()
            private_key = load_pem_private_key(private_key_data, password=None)
            
            # Load public key as string
            public_key_str = self.public_key_file.read_text().strip()
            
            return private_key, public_key_str
            
        except Exception as e:
            logger.error(f"Failed to load keys: {e}")
            return None, None
    
    def get_public_key_string(self) -> Optional[str]:
        """Get public key as string for server registration"""
        try:
            if not self.public_key_file.exists():
                return None
            return self.public_key_file.read_text().strip()
        except Exception as e:
            logger.error(f"Failed to read public key: {e}")
            return None
    
    def sign_data(self, data: str) -> Optional[str]:
        """Sign data with private key for authentication"""
        try:
            private_key, _ = self.load_keys()
            if not private_key:
                return None
            
            # Sign the data
            signature = private_key.sign(
                data.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Return base64 encoded signature
            return base64.b64encode(signature).decode('utf-8')
            
        except Exception as e:
            logger.error(f"Failed to sign data: {e}")
            return None
    
    def save_client_token(self, token: str) -> bool:
        """Save authentication token received from server"""
        try:
            self.token_file.write_text(token)
            self.token_file.chmod(0o600)
            return True
        except Exception as e:
            logger.error(f"Failed to save auth token: {e}")
            return False
    
    def load_client_token(self) -> Optional[str]:
        """Load authentication token for API requests"""
        try:
            if self.token_file.exists():
                return self.token_file.read_text().strip()
            return None
        except Exception as e:
            logger.error(f"Failed to load auth token: {e}")
            return None
    
    def has_valid_keys(self) -> bool:
        """Check if valid key pair exists"""
        return (self.private_key_file.exists() and 
                self.public_key_file.exists() and
                self.load_keys()[0] is not None)
    
    def create_registration_payload(self, machine_id: str, hostname: str) -> Optional[Dict[str, Any]]:
        """Create registration payload with signed challenge"""
        try:
            public_key_str = self.get_public_key_string()
            if not public_key_str:
                return None
            
            # Create challenge data to sign
            timestamp = int(time.time())
            challenge_data = f"{machine_id}:{hostname}:{timestamp}"
            
            # Sign the challenge
            signature = self.sign_data(challenge_data)
            if not signature:
                return None
            
            return {
                "machine_id": machine_id,
                "hostname": hostname,
                "public_key": public_key_str,
                "challenge": challenge_data,
                "signature": signature,
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Failed to create registration payload: {e}")
            return None
    
    def cleanup_old_auth(self):
        """Remove old API key files for migration"""
        old_api_key_file = self.config_dir / "api_key"
        if old_api_key_file.exists():
            try:
                old_api_key_file.unlink()
                logger.info("Removed old API key file")
            except Exception as e:
                logger.warning(f"Failed to remove old API key file: {e}")


def setup_client_auth(config_dir: Path = Path("/etc/dcmon"), force_regenerate: bool = False) -> Optional[ClientAuth]:
    """Set up client authentication system"""
    try:
        auth = ClientAuth(config_dir)
        
        # Check if keys already exist
        if auth.has_valid_keys() and not force_regenerate:
            logger.info("Using existing key pair")
            return auth
        
        # Generate new keys
        if auth.generate_key_pair():
            logger.info("Client authentication setup complete")
            return auth
        else:
            logger.error("Failed to set up client authentication")
            return None
            
    except ImportError:
        logger.error("cryptography package is required for client authentication")
        logger.error("Install with: pip install cryptography")
        return None
    except Exception as e:
        logger.error(f"Failed to set up client authentication: {e}")
        return None


if __name__ == "__main__":
    # Test the authentication system
    import tempfile
    import shutil
    
    # Create temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        test_config_dir = Path(temp_dir)
        
        print("Testing client authentication system...")
        
        # Set up auth
        auth = setup_client_auth(test_config_dir)
        if auth:
            print("✓ Key pair generated successfully")
            
            # Test registration payload creation
            payload = auth.create_registration_payload("test-machine", "test-host")
            if payload:
                print("✓ Registration payload created successfully")
                print(f"  Machine ID: {payload['machine_id']}")
                print(f"  Hostname: {payload['hostname']}")
                print(f"  Signature length: {len(payload['signature'])}")
            else:
                print("✗ Failed to create registration payload")
                
            # Test token operations
            test_token = "test_token_123"
            if auth.save_client_token(test_token):
                print("✓ Auth token saved successfully")
                
                loaded_token = auth.load_client_token()
                if loaded_token == test_token:
                    print("✓ Auth token loaded successfully")
                else:
                    print("✗ Auth token mismatch")
            else:
                print("✗ Failed to save auth token")
                
        else:
            print("✗ Failed to set up authentication")