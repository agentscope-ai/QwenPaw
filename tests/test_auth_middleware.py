# -*- coding: utf-8 -*-
"""Tests for BasicAuthMiddleware."""

import base64
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.auth_middleware import BasicAuthMiddleware


def create_test_app(
    username="admin",
    password="secret",
    excluded_paths=None,
    enabled=True,
):
    """Create a test app with auth middleware."""
    app = FastAPI()

    @app.get("/test")
    def test_endpoint():
        return {"message": "ok"}

    @app.get("/webhook/feishu")
    def feishu_webhook():
        return {"message": "webhook ok"}

    @app.get("/webhook/feishu/health")
    def feishu_health():
        return {"status": "healthy"}

    if enabled and password:
        app.add_middleware(
            BasicAuthMiddleware,
            username=username,
            password=password,
            excluded_paths=excluded_paths or ["/webhook/feishu"],
        )

    return app


class TestBasicAuthMiddleware:
    """Test cases for BasicAuthMiddleware."""

    def test_no_auth_returns_401(self):
        """Test that requests without auth return 401."""
        app = create_test_app()
        client = TestClient(app)

        response = client.get("/test")

        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers
        assert response.headers["WWW-Authenticate"] == "Basic"

    def test_valid_auth_returns_200(self):
        """Test that requests with valid auth return 200."""
        app = create_test_app()
        client = TestClient(app)

        credentials = base64.b64encode(b"admin:secret").decode("utf-8")
        response = client.get(
            "/test",
            headers={"Authorization": f"Basic {credentials}"},
        )

        assert response.status_code == 200
        assert response.json() == {"message": "ok"}

    def test_invalid_auth_returns_401(self):
        """Test that requests with invalid auth return 401."""
        app = create_test_app()
        client = TestClient(app)

        credentials = base64.b64encode(b"admin:wrongpassword").decode("utf-8")
        response = client.get(
            "/test",
            headers={"Authorization": f"Basic {credentials}"},
        )

        assert response.status_code == 401

    def test_excluded_path_no_auth_required(self):
        """Test that excluded paths don't require auth."""
        app = create_test_app()
        client = TestClient(app)

        response = client.get("/webhook/feishu")

        assert response.status_code == 200
        assert response.json() == {"message": "webhook ok"}

    def test_excluded_path_subpath_no_auth_required(self):
        """Test that subpaths of excluded paths don't require auth."""
        app = create_test_app()
        client = TestClient(app)

        response = client.get("/webhook/feishu/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_disabled_auth_allows_all(self):
        """Test that when password is empty, auth is disabled."""
        app = create_test_app(password="", enabled=True)
        client = TestClient(app)

        response = client.get("/test")

        assert response.status_code == 200
        assert response.json() == {"message": "ok"}

    def test_wrong_username_returns_401(self):
        """Test that wrong username returns 401."""
        app = create_test_app()
        client = TestClient(app)

        credentials = base64.b64encode(b"wronguser:secret").decode("utf-8")
        response = client.get(
            "/test",
            headers={"Authorization": f"Basic {credentials}"},
        )

        assert response.status_code == 401

    def test_custom_credentials_work(self):
        """Test that custom username/password work."""
        app = create_test_app(username="customuser", password="custompass")
        client = TestClient(app)

        credentials = base64.b64encode(b"customuser:custompass").decode(
            "utf-8",
        )
        response = client.get(
            "/test",
            headers={"Authorization": f"Basic {credentials}"},
        )

        assert response.status_code == 200
