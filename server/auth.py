#!/usr/bin/env python3
"""
dcmon Server Authentication System
Handles client public key verification and token management
"""

import base64
import hashlib
import secrets
import time
import logging
from typing import Optional, Dict, Any

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger('dcmon-server-auth')


class ServerAuth:
    """Server-side authentication handler"""
    
    def __init__(self):
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography package is required but not installed")
    
    def verify_client_signature(self, public_key_pem: str, challenge_data: str, signature_b64: str) -> bool:
        """Verify client signature using their public key"""
        try:
            # Load the public key
            public_key = load_pem_public_key(public_key_pem.encode('utf-8'))
            
            # Decode the signature
            signature = base64.b64decode(signature_b64)
            
            # Verify the signature
            public_key.verify(
                signature,
                challenge_data.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return True
            
        except Exception as e:
            logger.warning(f"Signature verification failed: {e}")
            return False
    
    def validate_registration_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate client registration payload"""
        result = {
            'valid': False,
            'error': 'Invalid payload',
            'machine_id': None,
            'hostname': None,
            'public_key': None
        }
        
        try:
            # Check required fields
            required_fields = ['machine_id', 'hostname', 'public_key', 'challenge', 'signature', 'timestamp']
            for field in required_fields:
                if field not in payload:
                    result['error'] = f'Missing required field: {field}'
                    return result
            
            # Check auth version (for backward compatibility)
            auth_version = payload.get('auth_version', 'v1')
            if auth_version != 'v2':
                result['error'] = f'Unsupported auth version: {auth_version}'
                return result
            
            # Validate timestamp (not too old, not in future)
            timestamp = payload['timestamp']
            current_time = int(time.time())
            if abs(current_time - timestamp) > 300:  # 5 minute window
                result['error'] = 'Timestamp out of valid range'
                return result
            
            # Validate machine_id format
            machine_id = payload['machine_id']
            if not machine_id or len(machine_id) < 8:
                result['error'] = 'Invalid machine_id'
                return result
            
            # Verify the signature
            if not self.verify_client_signature(
                payload['public_key'],
                payload['challenge'],
                payload['signature']
            ):
                result['error'] = 'Signature verification failed'
                return result
            
            # Validate the challenge format
            challenge_parts = payload['challenge'].split(':')
            if len(challenge_parts) != 3:
                result['error'] = 'Invalid challenge format'
                return result
            
            challenge_machine_id, challenge_hostname, challenge_timestamp = challenge_parts
            if (challenge_machine_id != machine_id or 
                challenge_hostname != payload['hostname'] or
                int(challenge_timestamp) != timestamp):
                result['error'] = 'Challenge data mismatch'
                return result
            
            # All validations passed
            result.update({
                'valid': True,
                'error': None,
                'machine_id': machine_id,
                'hostname': payload['hostname'],
                'public_key': payload['public_key']
            })
            
            return result
            
        except Exception as e:
            logger.error(f"Registration payload validation failed: {e}")
            result['error'] = f'Validation error: {str(e)}'
            return result
    
    def generate_client_token(self, machine_id: str, public_key_pem: str) -> str:
        """Generate client token for client"""
        try:
            # Create a deterministic but secure token based on machine_id and public key hash
            key_hash = hashlib.sha256(public_key_pem.encode('utf-8')).hexdigest()[:16]
            random_part = secrets.token_urlsafe(16)
            
            # Format: dcmon_v2_<machine_id_short>_<key_hash>_<random>
            machine_short = machine_id[:8] if len(machine_id) > 8 else machine_id
            token = f"dcmon_v2_{machine_short}_{key_hash}_{random_part}"
            
            return token
            
        except Exception as e:
            logger.error(f"Failed to generate client token: {e}")
            return ""
    
    def extract_machine_id_from_token(self, token: str) -> Optional[str]:
        """Extract machine_id from auth token for validation"""
        try:
            if not token.startswith('dcmon_v2_'):
                return None
            
            parts = token.split('_')
            if len(parts) >= 4:
                return parts[2]  # machine_short part
            
            return None
            
        except:
            return None
    


# Global server auth instance
server_auth = ServerAuth() if CRYPTO_AVAILABLE else None


def get_server_auth() -> Optional[ServerAuth]:
    """Get server auth instance"""
    return server_auth


if __name__ == "__main__":
    # Test the server authentication system
    print("Testing server authentication system...")
    
    if not CRYPTO_AVAILABLE:
        print("✗ cryptography package not available")
        exit(1)
    
    auth = ServerAuth()
    
    # Create a test payload (would normally come from client)
    test_payload = {
        "machine_id": "test-machine-123",
        "hostname": "test-host",
        "public_key": """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1234567890abcdef...
-----END PUBLIC KEY-----""",
        "challenge": "test-machine-123:test-host:1234567890",
        "signature": "base64signature...",
        "timestamp": int(time.time()),
        "auth_version": "v2"
    }
    
    # Test token generation
    token = auth.generate_client_token(test_payload["machine_id"], test_payload["public_key"])
    if token:
        print(f"✓ Generated auth token: {token[:20]}...")
        
        # Test token parsing
        machine_id = auth.extract_machine_id_from_token(token)
        if machine_id == test_payload["machine_id"][:8]:
            print("✓ Token parsing successful")
        else:
            print("✗ Token parsing failed")
            
        # Test token version detection
        if auth.is_v2_client_token(token):
            print("✓ V2 token detection successful")
        else:
            print("✗ V2 token detection failed")
    else:
        print("✗ Failed to generate auth token")
    
    print("Server authentication system test complete")