# -*- coding: utf-8 -*-
"""A2A client module for CloudPaw.

Provides Agent-to-Agent communication capabilities:
- GatewayTokenProvider: AK-SK → Bearer Token
- BearerTokenInterceptor: SDK interceptor for auth injection
- GatewayAdapter: URL /rpc + A2A-Version adaptations
- A2AClientManager: Client lifecycle and connection management
"""
