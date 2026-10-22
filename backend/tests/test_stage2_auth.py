import asyncio
from typing import AsyncGenerator
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


class InMemoryRedisMock:
    """Async in-memory key-value store simulating Redis for blacklist operations."""

    def __init__(self):
        self.store = {}

    async def setex(self, key: str, time_secs: int, value: str) -> bool:
        self.store[key] = (value, asyncio.get_event_loop().time() + time_secs)
        return True

    async def exists(self, key: str) -> int:
        if key in self.store:
            _, exp = self.store[key]
            if asyncio.get_event_loop().time() < exp:
                return 1
            del self.store[key]
        return 0

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.store.clear()


@pytest_asyncio.fixture(scope="function")
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide isolated test database and Redis for each test function."""
    # 1. Create in-memory SQLite async engine
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_maker() as session:
            try:
                yield session
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    # 2. Mock Redis client
    mock_redis = InMemoryRedisMock()
    with patch("app.core.security.get_redis_client", return_value=mock_redis):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client

    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_user_registration_success(async_client: httpx.AsyncClient):
    """Test POST /api/v1/auth/register creates user and returns 201 Created."""
    payload = {
        "email": "user@example.com",
        "password": "strongpassword123",
        "full_name": "Test User",
        "custom_system_prompt": "You are a helpful coding assistant.",
    }
    response = await async_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["email"] == "user@example.com"
    assert data["full_name"] == "Test User"
    assert data["custom_system_prompt"] == "You are a helpful coding assistant."
    assert data["is_active"] is True
    assert "id" in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_user_registration_duplicate_email_rejected(async_client: httpx.AsyncClient):
    """Test duplicate registration returns 400 Bad Request."""
    payload = {
        "email": "duplicate@example.com",
        "password": "secretpassword",
        "full_name": "Original User",
    }
    # Initial registration
    res1 = await async_client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    # Attempt second registration with same email
    res2 = await async_client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 400
    assert "Email already registered" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_user_login_success_and_failure(async_client: httpx.AsyncClient):
    """Test POST /api/v1/auth/login issues JWT tokens and rejects invalid credentials."""
    # Register user
    reg_payload = {
        "email": "login_user@example.com",
        "password": "correct_password_123",
        "full_name": "Login Tester",
    }
    reg_res = await async_client.post("/api/v1/auth/register", json=reg_payload)
    assert reg_res.status_code == 201

    # Test login with incorrect password
    bad_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "login_user@example.com", "password": "wrong_password"},
    )
    assert bad_login.status_code == 401
    assert "Incorrect email or password" in bad_login.json()["detail"]

    # Test login with valid credentials
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "login_user@example.com", "password": "correct_password_123"},
    )
    assert login_res.status_code == 200
    tokens = login_res.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"
    assert tokens["user"]["email"] == "login_user@example.com"


@pytest.mark.asyncio
async def test_get_current_user_profile(async_client: httpx.AsyncClient):
    """Test GET /api/v1/users/me returns profile for authenticated user."""
    # Register and login
    await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": "profile@example.com",
            "password": "password12345",
            "full_name": "Profile Name",
        },
    )
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "profile@example.com", "password": "password12345"},
    )
    access_token = login_res.json()["access_token"]

    # Test unauthenticated request
    unauth_res = await async_client.get("/api/v1/users/me")
    assert unauth_res.status_code == 401

    # Test authenticated request
    headers = {"Authorization": f"Bearer {access_token}"}
    me_res = await async_client.get("/api/v1/users/me", headers=headers)
    assert me_res.status_code == 200
    user_data = me_res.json()
    assert user_data["email"] == "profile@example.com"
    assert user_data["full_name"] == "Profile Name"


@pytest.mark.asyncio
async def test_update_user_settings_custom_prompt(async_client: httpx.AsyncClient):
    """Test PATCH /api/v1/users/me/settings updates custom_system_prompt and full_name."""
    # Register and login
    await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": "prompt_test@example.com",
            "password": "initialpassword",
            "full_name": "Initial Name",
        },
    )
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "prompt_test@example.com", "password": "initialpassword"},
    )
    access_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # Update custom system prompt
    patch_res = await async_client.patch(
        "/api/v1/users/me/settings",
        json={
            "custom_system_prompt": "You are a senior financial analyst.",
            "full_name": "Updated Financial Name",
        },
        headers=headers,
    )
    assert patch_res.status_code == 200
    updated_data = patch_res.json()
    assert updated_data["custom_system_prompt"] == "You are a senior financial analyst."
    assert updated_data["full_name"] == "Updated Financial Name"

    # Verify persisted in database via GET /me
    verify_res = await async_client.get("/api/v1/users/me", headers=headers)
    assert verify_res.status_code == 200
    assert verify_res.json()["custom_system_prompt"] == "You are a senior financial analyst."


@pytest.mark.asyncio
async def test_logout_token_revocation(async_client: httpx.AsyncClient):
    """Test POST /api/v1/auth/logout revokes token in Redis blacklist, causing 401 on reuse."""
    # Register and login
    await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": "logout_test@example.com",
            "password": "passwordToRevoke",
        },
    )
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "logout_test@example.com", "password": "passwordToRevoke"},
    )
    access_token = login_res.json()["access_token"]
    refresh_token = login_res.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # Verify token works before logout
    check_before = await async_client.get("/api/v1/users/me", headers=headers)
    assert check_before.status_code == 200

    # Logout
    logout_res = await async_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
        headers=headers,
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["message"] == "Successfully logged out"

    # Verify token is rejected with 401 Unauthorized after logout
    check_after = await async_client.get("/api/v1/users/me", headers=headers)
    assert check_after.status_code == 401
    assert "revoked" in check_after.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_token_rotation(async_client: httpx.AsyncClient):
    """Test POST /api/v1/auth/refresh provides new valid access token."""
    await async_client.post(
        "/api/v1/auth/register",
        json={"email": "refresh@example.com", "password": "password123"},
    )
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "refresh@example.com", "password": "password123"},
    )
    refresh_token = login_res.json()["refresh_token"]

    # Exchange refresh token for new access token
    refresh_res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_res.status_code == 200
    new_tokens = refresh_res.json()
    assert "access_token" in new_tokens
    new_access_token = new_tokens["access_token"]

    # Verify new access token works
    headers = {"Authorization": f"Bearer {new_access_token}"}
    me_res = await async_client.get("/api/v1/users/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "refresh@example.com"
