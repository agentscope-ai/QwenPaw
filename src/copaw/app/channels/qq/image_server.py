import hashlib
import http.server
import logging
import os
import socketserver
import threading
import urllib.parse
import uuid

DEFAULT_PORT = 18765
DEFAULT_STORAGE_DIR = "./qqbot-images"
LOG = logging.getLogger(__name__)


class SimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def _resolve_path(self, path):
        root = os.path.abspath(self.server.storage_dir)
        parsed_path = urllib.parse.urlparse(path).path
        unquoted_path = urllib.parse.unquote(parsed_path)
        name = os.path.normpath(unquoted_path).lstrip("/\\")
        if not name or name.startswith("..") or os.path.isabs(name):
            return None
        target = os.path.abspath(os.path.join(root, name))
        return target if os.path.commonpath([root, target]) == root else None

    def translate_path(self, path):
        return self._resolve_path(path) or os.path.join(
            os.path.abspath(self.server.storage_dir),
            "__missing__",
        )

    def do_GET(self):
        if not self._resolve_path(self.path):
            self.send_error(403, "Forbidden")
            return
        super().do_GET()

    def do_HEAD(self):
        if not self._resolve_path(self.path):
            self.send_error(403, "Forbidden")
            return
        super().do_HEAD()

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.address_string(), fmt % args)


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ImageServer:
    def __init__(self, port=DEFAULT_PORT, storage_dir=DEFAULT_STORAGE_DIR):
        self.port = port
        self.storage_dir = os.path.abspath(storage_dir)
        self._server = None
        self._thread = None

    def start(self):
        if self._server:
            return
        os.makedirs(self.storage_dir, exist_ok=True)
        self._server = _ThreadingTCPServer(
            ("127.0.0.1", self.port),
            SimpleHTTPRequestHandler,
        )
        self._server.storage_dir = self.storage_dir
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        if not self._server:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=1)
        self._server = self._thread = None

    def save_image(self, content, filename=None):
        os.makedirs(self.storage_dir, exist_ok=True)
        if not filename:
            ext = ".bin"
            if content.startswith(b"\x89PNG"):
                ext = ".png"
            elif content.startswith(b"\xff\xd8"):
                ext = ".jpg"
            elif content.startswith((b"GIF87a", b"GIF89a")):
                ext = ".gif"
            elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
                ext = ".webp"
            digest = hashlib.sha256(content).hexdigest()[:12]
            filename = f"{digest}-{uuid.uuid4().hex[:8]}{ext}"
        filename = os.path.basename(filename)
        with open(os.path.join(self.storage_dir, filename), "wb") as f:
            f.write(content)
        return filename

    def get_image_url(self, filename):
        quoted_filename = urllib.parse.quote(os.path.basename(filename))
        return f"http://127.0.0.1:{self.port}/{quoted_filename}"


_DEFAULT_SERVER = ImageServer()


def start_server(port=DEFAULT_PORT):
    global _DEFAULT_SERVER
    if (
        _DEFAULT_SERVER.port != port
        and _DEFAULT_SERVER._server  # pylint: disable=protected-access
    ):
        _DEFAULT_SERVER.stop()
    if _DEFAULT_SERVER.port != port:
        _DEFAULT_SERVER = ImageServer(
            port=port,
            storage_dir=_DEFAULT_SERVER.storage_dir,
        )
    _DEFAULT_SERVER.start()


def save_image(content, filename=None):
    return _DEFAULT_SERVER.save_image(content, filename)


def get_image_url(filename):
    return _DEFAULT_SERVER.get_image_url(filename)
