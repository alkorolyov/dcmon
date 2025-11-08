"""Unit tests for Authentication System

Tests the authentication and authorization layer including:
- RSA signature verification
- Client registration validation
- Token generation
- Admin authentication
- Client authentication
"""
import pytest
import sys
import os
import time
import base64
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from auth import AuthService
from api.dependencies import AuthDependencies
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend


# Test fixtures for RSA keys
@pytest.fixture
def rsa_keypair():
    """Generate RSA key pair for testing"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    public_key = private_key.public_key()

    # Serialize keys
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    return {'private': private_key, 'public_pem': public_pem, 'private_pem': private_pem}


def sign_message(private_key, message: str) -> str:
    """Helper to sign a message with RSA-PSS"""
    signature = private_key.sign(
        message.encode('utf-8'),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')


class TestAuthServiceTokenGeneration:
    """Test token generation"""

    def test_generate_client_token_format(self):
        """Client tokens should have dcmon_ prefix"""
        auth = AuthService()
        token = auth.generate_client_token()

        assert token.startswith("dcmon_")
        assert len(token) > 20  # Should be reasonably long

    def test_generate_admin_token_format(self):
        """Admin tokens should have dcmon_admin_ prefix"""
        auth = AuthService()
        token = auth.generate_admin_token()

        assert token.startswith("dcmon_admin_")
        assert len(token) > 30  # Should be reasonably long

    def test_tokens_are_unique(self):
        """Each token should be unique"""
        auth = AuthService()
        tokens = [auth.generate_client_token() for _ in range(10)]

        assert len(set(tokens)) == 10  # All unique


class TestAuthServiceSignatureVerification:
    """Test RSA signature verification"""

    def test_verify_valid_signature(self, rsa_keypair):
        """Valid signature should verify successfully"""
        auth = AuthService()
        message = "test_message:1234567890"
        signature = sign_message(rsa_keypair['private'], message)

        result = auth.verify_signature(rsa_keypair['public_pem'], message, signature)

        assert result is True

    def test_verify_invalid_signature(self, rsa_keypair):
        """Invalid signature should fail verification"""
        auth = AuthService()
        message = "test_message:1234567890"

        # Wrong signature
        result = auth.verify_signature(rsa_keypair['public_pem'], message, "invalid_signature_base64")

        assert result is False

    def test_verify_wrong_message(self, rsa_keypair):
        """Signature for different message should fail"""
        auth = AuthService()
        message1 = "original_message:1234567890"
        message2 = "tampered_message:1234567890"
        signature = sign_message(rsa_keypair['private'], message1)

        result = auth.verify_signature(rsa_keypair['public_pem'], message2, signature)

        assert result is False

    def test_verify_invalid_public_key(self, rsa_keypair):
        """Invalid public key should fail gracefully"""
        auth = AuthService()
        message = "test_message:1234567890"
        signature = sign_message(rsa_keypair['private'], message)

        result = auth.verify_signature("not_a_valid_pem_key", message, signature)

        assert result is False

    def test_verify_signature_with_different_key(self):
        """Signature from different key should fail"""
        auth = AuthService()

        # Generate two different key pairs
        key1 = rsa.generate_private_key(65537, 2048, default_backend())
        key2 = rsa.generate_private_key(65537, 2048, default_backend())

        public_pem2 = key2.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        message = "test_message:1234567890"
        signature = sign_message(key1, message)

        result = auth.verify_signature(public_pem2, message, signature)

        assert result is False


class TestAuthServiceRegistrationValidation:
    """Test client registration request validation"""

    def test_validate_valid_registration(self, rsa_keypair):
        """Valid registration request should pass validation"""
        auth = AuthService()
        now = int(time.time())
        challenge = f"dcmon_challenge:{now}"
        signature = sign_message(rsa_keypair['private'], challenge)

        request = {
            "hostname": "test-server",
            "public_key": rsa_keypair['public_pem'],
            "challenge": challenge,
            "signature": signature,
            "timestamp": now
        }

        result = auth.validate_registration_request(request)

        assert result["valid"] is True
        assert result["error"] is None
        assert result["hostname"] == "test-server"
        assert result["public_key"] == rsa_keypair['public_pem']

    def test_validate_missing_required_field(self, rsa_keypair):
        """Missing required field should fail validation"""
        auth = AuthService()

        request = {
            "hostname": "test-server",
            # Missing public_key, challenge, signature, timestamp
        }

        result = auth.validate_registration_request(request)

        assert result["valid"] is False
        assert "Missing required field" in result["error"]

    def test_validate_timestamp_too_old(self, rsa_keypair):
        """Old timestamp should fail validation"""
        auth = AuthService(skew_seconds=60)
        old_timestamp = int(time.time()) - 120  # 2 minutes ago
        challenge = f"dcmon_challenge:{old_timestamp}"
        signature = sign_message(rsa_keypair['private'], challenge)

        request = {
            "hostname": "test-server",
            "public_key": rsa_keypair['public_pem'],
            "challenge": challenge,
            "signature": signature,
            "timestamp": old_timestamp
        }

        result = auth.validate_registration_request(request)

        assert result["valid"] is False
        assert "Timestamp out of valid range" in result["error"]

    def test_validate_timestamp_in_future(self, rsa_keypair):
        """Future timestamp should fail validation"""
        auth = AuthService(skew_seconds=60)
        future_timestamp = int(time.time()) + 120  # 2 minutes in future
        challenge = f"dcmon_challenge:{future_timestamp}"
        signature = sign_message(rsa_keypair['private'], challenge)

        request = {
            "hostname": "test-server",
            "public_key": rsa_keypair['public_pem'],
            "challenge": challenge,
            "signature": signature,
            "timestamp": future_timestamp
        }

        result = auth.validate_registration_request(request)

        assert result["valid"] is False
        assert "Timestamp out of valid range" in result["error"]

    def test_validate_challenge_format_invalid(self, rsa_keypair):
        """Invalid challenge format should fail"""
        auth = AuthService()
        now = int(time.time())
        challenge = "invalid_challenge_no_timestamp"
        signature = sign_message(rsa_keypair['private'], challenge)

        request = {
            "hostname": "test-server",
            "public_key": rsa_keypair['public_pem'],
            "challenge": challenge,
            "signature": signature,
            "timestamp": now
        }

        result = auth.validate_registration_request(request)

        assert result["valid"] is False
        assert "Invalid challenge format" in result["error"]

    def test_validate_challenge_timestamp_mismatch(self, rsa_keypair):
        """Challenge timestamp mismatch should fail"""
        auth = AuthService()
        now = int(time.time())
        different_time = now - 50
        challenge = f"dcmon_challenge:{different_time}"
        signature = sign_message(rsa_keypair['private'], challenge)

        request = {
            "hostname": "test-server",
            "public_key": rsa_keypair['public_pem'],
            "challenge": challenge,
            "signature": signature,
            "timestamp": now  # Different from challenge timestamp
        }

        result = auth.validate_registration_request(request)

        assert result["valid"] is False
        assert "Challenge timestamp mismatch" in result["error"]

    def test_validate_invalid_signature(self, rsa_keypair):
        """Invalid signature should fail validation"""
        auth = AuthService()
        now = int(time.time())
        challenge = f"dcmon_challenge:{now}"

        request = {
            "hostname": "test-server",
            "public_key": rsa_keypair['public_pem'],
            "challenge": challenge,
            "signature": "invalid_signature",
            "timestamp": now
        }

        result = auth.validate_registration_request(request)

        assert result["valid"] is False
        assert "Signature verification failed" in result["error"]

    def test_validate_challenge_with_non_numeric_timestamp(self, rsa_keypair):
        """Non-numeric timestamp in challenge should fail"""
        auth = AuthService()
        now = int(time.time())
        challenge = f"dcmon_challenge:not_a_number"
        signature = sign_message(rsa_keypair['private'], challenge)

        request = {
            "hostname": "test-server",
            "public_key": rsa_keypair['public_pem'],
            "challenge": challenge,
            "signature": signature,
            "timestamp": now
        }

        result = auth.validate_registration_request(request)

        assert result["valid"] is False
        assert "Invalid challenge timestamp" in result["error"]


class TestAuthDependenciesAdminAuth:
    """Test admin authentication dependency"""

    @patch('api.dependencies.audit_logger')
    def test_admin_auth_with_valid_basic_auth(self, mock_audit):
        """Valid Basic Auth should authenticate successfully"""
        admin_token = "test_admin_token_12345"
        auth_deps = AuthDependencies(admin_token=admin_token, test_mode=False)

        # Create mock request with Basic Auth
        request = Mock()
        credentials = base64.b64encode(b"admin:test_admin_token_12345").decode('utf-8')
        request.headers.get.return_value = f"Basic {credentials}"

        # Should not raise exception
        result = auth_deps.require_admin_auth(request)
        assert result is None  # Success returns None

    @patch('api.dependencies.audit_logger')
    def test_admin_auth_with_invalid_password(self, mock_audit):
        """Invalid password should fail authentication"""
        admin_token = "correct_token"
        auth_deps = AuthDependencies(admin_token=admin_token, test_mode=False)

        request = Mock()
        credentials = base64.b64encode(b"admin:wrong_token").decode('utf-8')
        request.headers.get.return_value = f"Basic {credentials}"

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            auth_deps.require_admin_auth(request)

        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail

    @patch('api.dependencies.audit_logger')
    def test_admin_auth_with_no_auth_header(self, mock_audit):
        """Missing auth header should fail"""
        admin_token = "test_token"
        auth_deps = AuthDependencies(admin_token=admin_token, test_mode=False)

        request = Mock()
        request.headers.get.return_value = ""

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            auth_deps.require_admin_auth(request)

        assert exc_info.value.status_code == 401

    @patch('api.dependencies.audit_logger')
    def test_admin_auth_with_malformed_basic_auth(self, mock_audit):
        """Malformed Basic Auth should fail"""
        admin_token = "test_token"
        auth_deps = AuthDependencies(admin_token=admin_token, test_mode=False)

        request = Mock()
        request.headers.get.return_value = "Basic invalid_base64!@#$"

        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            auth_deps.require_admin_auth(request)

    @patch('api.dependencies.audit_logger')
    def test_admin_auth_test_mode(self, mock_audit):
        """Test mode should accept dev token"""
        auth_deps = AuthDependencies(admin_token="dev_admin_token_12345", test_mode=True)

        request = Mock()
        credentials = base64.b64encode(b"admin:dev_admin_token_12345").decode('utf-8')
        request.headers.get.return_value = f"Basic {credentials}"

        # Should succeed
        result = auth_deps.require_admin_auth(request)
        assert result is None

    @patch('api.dependencies.audit_logger')
    def test_admin_auth_with_bearer_token_should_fail(self, mock_audit):
        """Bearer token (not Basic Auth) should fail for admin"""
        admin_token = "test_token"
        auth_deps = AuthDependencies(admin_token=admin_token, test_mode=False)

        request = Mock()
        request.headers.get.return_value = "Bearer some_token"

        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            auth_deps.require_admin_auth(request)


class TestAuthDependenciesClientAuth:
    """Test client authentication dependency"""

    @patch('api.dependencies.audit_logger')
    def test_client_auth_with_valid_token(self, mock_audit, test_db, sample_client):
        """Valid client token should authenticate successfully"""
        auth_deps = AuthDependencies(admin_token="test", test_mode=False)

        # Create mock credentials
        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=sample_client.client_token)

        request = Mock()
        request.url = "http://test.com/api/metrics"

        result = auth_deps.require_client_auth(request, creds)

        assert result is not None
        assert result.id == sample_client.id
        assert result.hostname == sample_client.hostname

    @patch('api.dependencies.audit_logger')
    def test_client_auth_with_invalid_token(self, mock_audit, test_db):
        """Invalid client token should fail authentication"""
        auth_deps = AuthDependencies(admin_token="test", test_mode=False)

        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid_token_12345")

        request = Mock()
        request.url = "http://test.com/api/metrics"

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            auth_deps.require_client_auth(request, creds)

        assert exc_info.value.status_code == 401
        assert "invalid client token" in exc_info.value.detail

    @patch('api.dependencies.audit_logger')
    def test_client_auth_with_nonexistent_token(self, mock_audit, test_db):
        """Nonexistent token should fail"""
        auth_deps = AuthDependencies(admin_token="test", test_mode=False)

        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="dcmon_nonexistent_token")

        request = Mock()
        request.url = "http://test.com/api/metrics"

        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            auth_deps.require_client_auth(request, creds)
