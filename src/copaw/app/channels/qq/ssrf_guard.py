from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"}
ALLOWED_PORTS = {80, 443, 8080, 8443}


def is_safe_url(url):
    p = urlparse(url)
    if p.scheme.lower() not in ALLOWED_SCHEMES: return False
    if p.hostname and p.hostname.lower() in BLOCKED_HOSTS: return False
    if p.port and p.port not in ALLOWED_PORTS: return False
    return True


def validate_remote_url(url): return is_safe_url(url)
