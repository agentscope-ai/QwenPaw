# -*- coding: utf-8 -*-
"""Vercel Serverless Function - CoPaw Telemetry Service."""
from http.server import BaseHTTPRequestHandler
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler."""

    def _set_headers(
        self,
        status_code: int = 200,
        content_type: str = "application/json",
    ):
        """Set response headers."""
        self.send_response(status_code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, data: dict, status_code: int = 200):
        """Send JSON response."""
        self._set_headers(status_code)
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.wfile.write(response)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self._set_headers(204)

    def do_GET(self):
        """Handle GET requests."""
        if self.path in ("/", "/api"):
            self._send_json(
                {
                    "service": "CoPaw Telemetry Service",
                    "status": "running",
                    "version": "1.0.0",
                    "platform": "Vercel Serverless",
                },
            )
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        """Handle POST requests."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_json({"error": "Empty request body"}, 400)
                return

            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            required_fields = [
                "install_id",
                "os",
                "os_version",
                "python_version",
                "architecture",
                "has_gpu",
            ]

            for field in required_fields:
                if field not in data:
                    self._send_json(
                        {"error": f"Missing required field: {field}"},
                        400,
                    )
                    return

            logger.info(
                f"Telemetry received: {json.dumps(data, ensure_ascii=False)}",
            )

            self._send_json(
                {
                    "status": "success",
                    "message": "Telemetry data received",
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
        except Exception as e:
            logger.error(f"Error processing telemetry: {str(e)}")
            self._send_json({"error": "Internal server error"}, 500)
