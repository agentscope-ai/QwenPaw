# MCP upgrade defaults

Hand-checked snapshots of supported migration watermarks, not generated expectations.

- `default-v0.json`: disabled AnySearch from `src/qwenpaw/config/config.py:MCPConfig`.
- `default-v1.json`: same raw config plus the default card shape from `legacy_mcp_client_to_driver`; migration watermark 1.
- `default-v2.json`: watermark 2 with its normalized `env:ANYSEARCH_API_KEY` binding.

Card policy includes the serialized defaults from `DriverPolicy` / `PolicyRule`, as persisted by `drivers/storage.py`. v1 and v2 can share this card shape: the current v1 conversion already emits environment references, and v2 healing changes only older opaque static bindings. A historical static `mcp/anysearch` reference cannot prove the bound value is the default placeholder without decrypting; tests require needs_review, preserve it and never decrypt or auto-install. Other explicit custom bindings remain configured.

Only public URLs, variable references and synthetic values appear here. No credential store is needed to classify these fixtures.
