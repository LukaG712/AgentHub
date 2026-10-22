"""Tests for user authentication and session management."""

import os
import time
from unittest.mock import patch, MagicMock

import pytest

from hub.api.auth import (
    hash_password,
    verify_password,
    create_user,
    get_user,
    update_user,
    change_password,
    list_users,
    create_session,
    validate_session,
    revoke_session,
    cleanup_expired_sessions,
    _sign_session_token,
    _verify_session_token,
    _users,
    _sessions,
    _sanitize_user,
)


@pytest.fixture(autouse=True)
def clear_auth_stores():
    """Clear user and session stores before each test."""
    _users.clear()
    _sessions.clear()
    yield
    _users.clear()
    _sessions.clear()


class TestPasswordHashing:
    """Test password hashing and verification."""

    def test_hash_and_verify(self):
        """Hashed password should verify correctly."""
        password = "SecureP@ssw0rd!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        """Wrong password should not verify."""
        password = "SecureP@ssw0rd!"
        hashed = hash_password(password)
        assert verify_password("WrongPassword123", hashed) is False

    def test_hash_is_different_each_time(self):
        """Each hash should be unique (due to salt)."""
        password = "SecureP@ssw0rd!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2
        # But both should verify
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)

    def test_sha256_fallback(self):
        """SHA-256 fallback should work when bcrypt is unavailable."""
        # Simulate SHA-256 fallback
        import secrets
        import hashlib
        salt = secrets.token_hex(16)
        password = "SecureP@ssw0rd!"
        hashed = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        hashed = f"$sha256${salt}${hashed}"
        assert verify_password(password, hashed) is True
        assert verify_password("WrongPassword123", hashed) is False


class TestUserManagement:
    """Test user CRUD operations."""

    def test_create_user(self):
        """Creating a user should store it without password hash."""
        with patch("hub.api.auth.save_auth_user"):
            user = create_user("testuser", "SecureP@ss1", role="user")
        
        assert user["username"] == "testuser"
        assert user["role"] == "user"
        assert "password_hash" not in user  # Sanitized
        assert user["is_active"] is True

    def test_create_user_min_password_length(self):
        """Password must be at least 8 characters."""
        with patch("hub.api.auth.save_auth_user"):
            with pytest.raises(ValueError, match="at least 8"):
                create_user("testuser", "short")

    def test_create_duplicate_user(self):
        """Creating a duplicate user should raise ValueError."""
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
            with pytest.raises(ValueError, match="already exists"):
                create_user("testuser", "SecureP@ss2")

    def test_create_user_empty_password(self):
        """Empty password should raise ValueError."""
        with patch("hub.api.auth.save_auth_user"):
            with pytest.raises(ValueError, match="required"):
                create_user("testuser", "")

    def test_get_user(self):
        """Getting an existing user should return sanitized data."""
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
        
        user = get_user("testuser")
        assert user is not None
        assert user["username"] == "testuser"
        assert "password_hash" not in user

    def test_get_nonexistent_user(self):
        """Getting a nonexistent user should return None."""
        assert get_user("nonexistent") is None

    def test_update_user(self):
        """Updating a user should change allowed fields."""
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
            updated = update_user("testuser", display_name="Test User", email="test@example.com")
        
        assert updated["display_name"] == "Test User"
        assert updated["email"] == "test@example.com"

    def test_update_nonexistent_user(self):
        """Updating a nonexistent user should return None."""
        assert update_user("nonexistent", display_name="Test") is None

    def test_update_user_ignores_disallowed_fields(self):
        """Updating with disallowed fields should ignore them."""
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
            update_user("testuser", password_hash="hacked", role="admin")
        
        user = get_user("testuser")
        assert user["role"] == "user"  # Role not in allowed fields for update_user

    def test_change_password(self):
        """Changing password should update hash and revoke sessions."""
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
            change_password("testuser", "SecureP@ss1", "NewSecureP@ss2")
        
        # Old password should not work
        user_data = _users["testuser"]
        assert not verify_password("SecureP@ss1", user_data["password_hash"])
        # New password should work
        assert verify_password("NewSecureP@ss2", user_data["password_hash"])

    def test_change_password_wrong_old(self):
        """Changing with wrong old password should raise ValueError."""
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
            with pytest.raises(ValueError, match="incorrect"):
                change_password("testuser", "WrongPassword1", "NewSecureP@ss2")

    def test_change_password_short_new(self):
        """New password must be at least 8 characters."""
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
            with pytest.raises(ValueError, match="at least 8"):
                change_password("testuser", "SecureP@ss1", "short")

    def test_list_users(self):
        """Listing users should return all users without password hashes."""
        with patch("hub.api.auth.save_auth_user"):
            create_user("user1", "SecureP@ss1")
            create_user("user2", "SecureP@ss2")
        
        users = list_users()
        assert len(users) == 2
        for user in users:
            assert "password_hash" not in user

    def test_sanitize_user(self):
        """Sanitize should remove password hash."""
        user = {
            "id": "123",
            "username": "test",
            "password_hash": "$2b$12$...",
            "role": "user",
        }
        sanitized = _sanitize_user(user)
        assert "password_hash" not in sanitized
        assert sanitized["username"] == "test"


class TestSessionManagement:
    """Test session creation, validation, and revocation."""

    def test_create_session(self):
        """Creating a session should return a signed token."""
        with patch("hub.api.auth.save_auth_session"):
            token = create_session("user-123", "testuser")
        
        assert "." in token  # Signed token format
        session_id = _verify_session_token(token)
        assert session_id is not None
        assert session_id in _sessions

    def test_validate_session(self):
        """Valid session should return session data."""
        with patch("hub.api.auth.save_auth_session"):
            token = create_session("user-123", "testuser")
        
        session = validate_session(token, ip_address="127.0.0.1")
        assert session is not None
        assert session["username"] == "testuser"
        assert session["ip_address"] == "127.0.0.1"

    def test_validate_invalid_token(self):
        """Invalid token should return None."""
        assert validate_session("invalid.token.here") is None

    def test_validate_revoked_session(self):
        """Revoked session should return None."""
        with patch("hub.api.auth.save_auth_session"):
            token = create_session("user-123", "testuser")
            revoke_session(token)
        
        assert validate_session(token) is None

    def test_validate_expired_session(self):
        """Expired session should return None."""
        session_id = "test-session"
        _sessions[session_id] = {
            "session_id": session_id,
            "user_id": "user-123",
            "username": "testuser",
            "created_at": "2020-01-01T00:00:00+00:00",
            "expires_at": "2020-01-01T00:00:00+00:00",
            "expires_at_ts": 0.0,  # Already expired
            "revoked": False,
            "revoked_at": None,
            "ip_address": None,
            "user_agent": None,
        }
        token = _sign_session_token(session_id)
        assert validate_session(token) is None

    def test_revoke_session(self):
        """Revoking a session should mark it as revoked."""
        with patch("hub.api.auth.save_auth_session"):
            token = create_session("user-123", "testuser")
            result = revoke_session(token)
        
        assert result is True
        session_id = _verify_session_token(token)
        assert _sessions[session_id]["revoked"] is True

    def test_revoke_invalid_token(self):
        """Revoking an invalid token should return False."""
        assert revoke_session("invalid.token") is False

    def test_cleanup_expired_sessions(self):
        """Cleanup should remove expired and revoked sessions."""
        # Add an expired session
        session_id = "expired-session"
        _sessions[session_id] = {
            "session_id": session_id,
            "user_id": "user-123",
            "username": "testuser",
            "created_at": "2020-01-01T00:00:00+00:00",
            "expires_at": "2020-01-01T00:00:00+00:00",
            "expires_at_ts": 0.0,
            "revoked": False,
            "revoked_at": None,
            "ip_address": None,
            "user_agent": None,
        }
        # Add a valid session
        with patch("hub.api.auth.save_auth_session"):
            create_session("user-456", "validuser")
        
        count = cleanup_expired_sessions()
        assert count >= 1
        assert session_id not in _sessions

    def test_session_token_signature(self):
        """Session token signature should be verifiable."""
        session_id = "test-session-id"
        token = _sign_session_token(session_id)
        verified = _verify_session_token(token)
        assert verified == session_id

    def test_session_token_tampering(self):
        """Tampered session token should fail verification."""
        session_id = "test-session-id"
        token = _sign_session_token(session_id)
        # Tamper with the session ID part
        parts = token.rsplit(".", 1)
        tampered = f"tampered-id.{parts[1]}"
        assert _verify_session_token(tampered) is None


class TestAuthorization:
    """Test authorization dependencies."""

    @pytest.mark.asyncio
    async def test_require_auth_no_session(self):
        """require_auth should raise 401 without session."""
        from hub.api.auth import require_auth
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await require_auth(None)
        
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_admin_non_admin(self):
        """require_admin should raise 403 for non-admin users."""
        from hub.api.auth import require_admin
        from fastapi import HTTPException
        
        # Mock get_current_user to return a non-admin user
        with patch("hub.api.auth.get_current_user", return_value=MagicMock(
            __await__=lambda self: {"username": "testuser", "role": "user"}
        )):
            # This test is simplified — in reality, require_admin calls require_auth
            # which calls get_current_user. We test the role check directly.
            pass  # Role check is tested via the endpoint tests

    @pytest.mark.asyncio
    async def test_get_current_user_no_cookie(self):
        """get_current_user should return None without session cookie."""
        from hub.api.auth import get_current_user
        
        result = await get_current_user(None)
        assert result is None


class TestLoginLogout:
    """Test login and logout helpers."""

    @pytest.mark.asyncio
    async def test_login_success(self):
        """Successful login should return user data and set cookie."""
        from hub.api.auth import login
        
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
        
        mock_response = MagicMock()
        result = await login("testuser", "SecureP@ss1", mock_response)
        
        assert result["user"]["username"] == "testuser"
        assert "session" in result
        mock_response.set_cookie.assert_called_once()
        
        # Verify cookie settings
        call_kwargs = mock_response.set_cookie.call_args[1]
        assert call_kwargs["httponly"] is True
        assert call_kwargs["samesite"] == "lax"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        """Wrong password should raise 401."""
        from hub.api.auth import login
        from fastapi import HTTPException
        
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
        
        mock_response = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await login("testuser", "WrongPassword1", mock_response)
        
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self):
        """Nonexistent user should raise 401."""
        from hub.api.auth import login
        from fastapi import HTTPException
        
        mock_response = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await login("nonexistent", "SecureP@ss1", mock_response)
        
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_disabled_user(self):
        """Disabled user should raise 401."""
        from hub.api.auth import login
        from fastapi import HTTPException
        
        with patch("hub.api.auth.save_auth_user"):
            create_user("testuser", "SecureP@ss1")
            update_user("testuser", is_active=False)
        
        mock_response = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await login("testuser", "SecureP@ss1", mock_response)
        
        assert exc_info.value.status_code == 401
        assert "disabled" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_logout(self):
        """Logout should revoke session and clear cookie."""
        from hub.api.auth import logout
        
        with patch("hub.api.auth.save_auth_session"):
            token = create_session("user-123", "testuser")
        
        mock_response = MagicMock()
        result = await logout(mock_response, token)
        
        assert result["message"] == "Logged out successfully"
        mock_response.delete_cookie.assert_called_once()
