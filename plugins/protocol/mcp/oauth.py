# -*- coding: utf-8 -*-
"""Authenticated OAuth management with finite, source-bound PKCE state."""

import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx

from qwenpaw.plugins.apps import HttpResponse, PawApp

from .oauth_helpers import (
    OAuthError,
    _code_challenge,
    _discover_oauth_metadata,
    _dynamic_register,
    _generate_code_verifier,
)

_TTL_SECONDS = 600


@dataclass
class OAuthSession:
    workspace_id: str
    workspace_instance_id: str
    client_key: str
    source_revision: int
    code_verifier: str
    client_id: str
    auth_endpoint: str
    token_endpoint: str
    redirect_uri: str
    scope: str
    created_at: float = field(default_factory=time.monotonic)

    def is_expired(self):
        return time.monotonic() - self.created_at > _TTL_SECONDS


async def _exchange_code_for_tokens(session, code):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": session.redirect_uri,
        "code_verifier": session.code_verifier,
    }
    if session.client_id:
        data["client_id"] = session.client_id
    async with httpx.AsyncClient() as client:
        response = await client.post(
            session.token_endpoint,
            data=data,
            timeout=15,
        )
    if response.status_code not in (200, 201):
        raise ValueError(
            f"Token exchange failed (HTTP {response.status_code}): "
            f"{response.text[:300]}",
        )
    tokens = response.json()
    if not tokens.get("access_token"):
        raise ValueError("Token response did not contain an access_token.")
    return tokens


class OAuthManagement:
    def __init__(self):
        self._states = {}

    def app(self):
        app = PawApp("MCP", app_id="qwenpaw-mcp")
        for path, method, handler in (
            ("/management", "GET", self.management),
            ("/oauth/start/{client_key:path}", "POST", self.start),
            ("/oauth/callback", "POST", self.callback),
            ("/oauth/status/{client_key:path}", "GET", self.status),
            ("/oauth/{client_key:path}", "DELETE", self.revoke),
        ):
            app.route(path, methods=(method,))(handler)
        return app

    async def management(self, context, _request):
        return {
            "plugin_id": "qwenpaw-mcp",
            "workspace_id": context.workspace_id,
            "capabilities": ["oauth"],
        }

    def _purge(self):
        for state, session in tuple(self._states.items()):
            if session.is_expired():
                self._states.pop(state, None)

    async def start(self, context, request):
        self._purge()
        body = request.json()
        key = request.path_params["client_key"]
        async with context.driver_source("mcp", key) as source:
            existing = await source.credentials.resolve("oauth")
            url = str(
                source.source.endpoint.get("url") or body.get("url") or "",
            )
            redirect = str(body.get("redirect_uri") or "")
            if not url or not redirect:
                return HttpResponse(
                    {"detail": "OAuth URL and redirect_uri are required"},
                    status=400,
                )
            try:
                authorization = body.get("auth_endpoint")
                token = body.get("token_endpoint")
                registration = None
                if not authorization or not token:
                    (
                        authorization,
                        token,
                        registration,
                    ) = await _discover_oauth_metadata(url)
                client_id = str(
                    body.get("client_id")
                    or existing.public.get("client_id")
                    or "",
                )
                if not client_id and registration:
                    client_id = (
                        await _dynamic_register(registration, redirect) or ""
                    )
            except OAuthError as exc:
                return HttpResponse({"detail": str(exc)}, status=exc.status)
            verifier = _generate_code_verifier()
            state = secrets.token_hex(16)
            scope = str(body.get("scope") or "")
            # Recheck admitted source lifetime after discovery network awaits.
            await source.credentials.resolve("oauth")
            self._states[state] = OAuthSession(
                source.workspace_id,
                source.workspace_instance_id,
                key,
                source.source_revision,
                verifier,
                client_id,
                authorization,
                token,
                redirect,
                scope,
            )
        params = {
            "response_type": "code",
            "redirect_uri": redirect,
            "state": state,
            "code_challenge": _code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        if client_id:
            params["client_id"] = client_id
        if scope:
            params["scope"] = scope
        return {
            "auth_url": f"{authorization}?{urlencode(params)}",
            "session_id": state,
        }

    async def callback(self, context, request):
        self._purge()
        body = request.json()
        # Claim before the first await, including provider failures/replays.
        session = self._states.pop(str(body.get("state") or ""), None)
        if session is None or session.is_expired():
            return HttpResponse(
                {"detail": "OAuth session expired or not found"},
                status=400,
            )
        if session.workspace_id != context.workspace_id:
            return HttpResponse(
                {"detail": "OAuth workspace mismatch"},
                status=403,
            )
        if body.get("error") or not body.get("code"):
            return HttpResponse(
                {
                    "detail": str(
                        body.get("error_description")
                        or body.get("error")
                        or "Missing code",
                    ),
                },
                status=400,
            )
        async with context.driver_source("mcp", session.client_key) as source:
            if (
                source.workspace_instance_id != session.workspace_instance_id
                or source.source_revision != session.source_revision
            ):
                return HttpResponse(
                    {"detail": "OAuth source changed"},
                    status=409,
                )
            record = await source.credentials.resolve("oauth")
            try:
                tokens = await _exchange_code_for_tokens(
                    session,
                    str(body["code"]),
                )
            except (ValueError, httpx.HTTPError) as exc:
                return HttpResponse({"detail": str(exc)}, status=400)
            public, sensitive = dict(record.public), dict(record.secrets)
            public.update(
                {
                    "client_id": session.client_id
                    or str(public.get("client_id") or ""),
                    "scope": tokens.get("scope", session.scope),
                    "expires_at": time.time()
                    + int(tokens.get("expires_in", 3600)),
                    "token_endpoint": session.token_endpoint,
                    "auth_endpoint": session.auth_endpoint,
                },
            )
            sensitive["access_token"] = tokens["access_token"]
            if tokens.get("refresh_token"):
                sensitive["refresh_token"] = tokens["refresh_token"]
            await source.credentials.update(
                "oauth",
                expected_revision=record.revision,
                public=public,
                secrets=sensitive,
            )
        return {
            "status": "success",
            "clientKey": session.client_key,
            "agentId": session.workspace_id,
        }

    async def status(self, context, request):
        async with context.driver_source(
            "mcp",
            request.path_params["client_key"],
        ) as source:
            record = await source.credentials.resolve("oauth")
            expiry = float(record.public.get("expires_at") or 0)
            return {
                "authorized": bool(record.secrets.get("access_token"))
                and (expiry <= 0 or expiry > time.time()),
                "expires_at": expiry,
                "scope": str(record.public.get("scope") or ""),
            }

    async def revoke(self, context, request):
        async with context.driver_source(
            "mcp",
            request.path_params["client_key"],
        ) as source:
            record = await source.credentials.resolve("oauth")
            sensitive = dict(record.secrets)
            sensitive.pop("access_token", None)
            sensitive.pop("refresh_token", None)
            await source.credentials.update(
                "oauth",
                expected_revision=record.revision,
                public=record.public,
                secrets=sensitive,
            )
        return {"message": "OAuth tokens cleared"}
