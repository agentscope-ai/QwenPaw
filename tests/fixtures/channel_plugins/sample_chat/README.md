# Generic Channel process example

This runnable offline plugin uses `channel.generic.v1`. `channel.json` declares a
static JSON Schema and process capabilities; discovery reads it without importing
`sample_chat.driver` or `sample_chat.sdk`. `requirements.txt` is empty because the
SDK boundary is local and offline.

The Driver extends the SDK-free `SharedResponseDriver`, not an official platform
Driver. It computes `session_id`, `user_id`, and `debounce_key` before submitting
`InboundEvent`. `acl_sender_id` remains the authenticated member even when the
Agent's `user_id` is `group`. `conversation.type` carries the group/DM distinction.
Thread and platform extension metadata may be carried without host interpretation.

`channel.response.open` decodes the neutral proactive target and persists the
resulting room route. Saved `sample:old:<room>` targets retain their historical
meaning. An absent room returns `OUTBOUND_TARGET_UNKNOWN`. The synchronous
`response_policy(response_handle)` hook reads the established route and returns
three booleans: `streaming`, `prepare`, and `completion_reaction`. Describe does
not send, prepare, or mutate durable route state. Sending and finishing use the
shared delivery journal, including uncertain receipt preservation.

The `fixture.*` RPCs replace a vendor event/network boundary for local acceptance;
they are test instrumentation. Replace these and `sdk.py` with the real platform
transport when adapting the example. Do not import that transport in the host.

Run the example's real Loader/Manager acceptance from the repository root:

```sh
python -I -m pytest \
  --confcutdir tests/fixtures/channel_plugins \
  tests/fixtures/channel_plugins/extension_process_suite.py -q
```

`extension_sample.sample_source(directory, key)` copies this exact artifact and
renames only its package/manifest/entrypoint. Acceptance runs `sample_chat` and
`another_chat` with different configuration and capabilities without changing
Loader, Manager, or the host proxy.
