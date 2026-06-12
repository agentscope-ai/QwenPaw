# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/oauth/authorize":
            self.send_error(404)
            return
        query = parse_qs(parsed.query)
        redirect_uri = query["redirect_uri"][0]
        state = query.get("state", [""])[0]
        params = urlencode({"code": "fake-code", "state": state})
        location = f"{redirect_uri}?{params}"
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/oauth/token":
            self.send_error(404)
            return
        body = {
            "access_token": "fake-access-token",
            "refresh_token": "fake-refresh-token",
            "expires_in": 3600,
            "scope": "tools:read tools:call",
        }
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 18082), OAuthHandler).serve_forever()
