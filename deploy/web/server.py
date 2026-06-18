from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class SecurityCenterWebHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        directory = Path(__file__).resolve().parent
        super().__init__(*args, directory=str(directory), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        request_path = self.path.split("?", 1)[0]
        if request_path == "/config.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.end_headers()
            api_base = os.environ.get("SECURITY_CENTER_API_BASE", "http://127.0.0.1:8091")
            self.wfile.write(
                f"window.SECURITY_CENTER_CONFIG = {{ apiBase: {api_base!r} }};".encode("utf-8"),
            )
            return
        if (
            request_path == "/security-events"
            or request_path.startswith("/security-events/")
            or request_path == "/security-event-observation"
        ):
            self.path = "/index.html"
        return super().do_GET()


def main() -> None:
    host = os.environ.get("SECURITY_CENTER_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("SECURITY_CENTER_WEB_PORT", "8092"))
    server = ThreadingHTTPServer((host, port), SecurityCenterWebHandler)
    print(f"Security Center web running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
