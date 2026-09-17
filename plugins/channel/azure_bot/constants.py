# -*- coding: utf-8 -*-
"""Azure Bot Service channel constants."""

# Default HTTP port for the Azure Bot webhook server
AZURE_BOT_DEFAULT_PORT = 3978

# Bot Framework OpenID Metadata endpoint for JWT validation.
AZURE_BOT_OPENID_METADATA_URL = (
    "https://login.botframework.com/v1/.well-known/openidconfiguration"
)

# Bot Framework API scope for outbound REST calls.
AZURE_BOT_FRAMEWORK_SCOPE = "https://api.botframework.com/.default"

# Watchdog interval (seconds) for HTTP server health checks.
AZURE_BOT_WATCHDOG_INTERVAL_S = 10.0

# JWKS cache TTL (seconds) - avoid fetching keys on every request.
AZURE_BOT_JWKS_CACHE_TTL_S = 3600
