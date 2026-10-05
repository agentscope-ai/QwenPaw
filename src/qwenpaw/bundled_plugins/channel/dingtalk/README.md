# DingTalk channel plugin

This is the canonical source of the official DingTalk channel plugin.
`plugin.py` registers a lazy loader with the existing QwenPaw PluginApi.
Each enabled workspace creates its own BaseChannel instance. The stable
channel key is `dingtalk`; credentials and state remain in their existing
workspace locations.

Install from the repository root:

```bash
qwenpaw plugin install src/qwenpaw/bundled_plugins/channel/dingtalk
```

The first compatibility release also ships this source in the host wheel.
On first startup it is copied once into the user plugin directory, without
changing any configuration. Subsequent updates/removal are explicit plugin
operations. Host startup never reinstalls a removed plugin and never installs
missing dependencies for this plugin. Keep the existing DingTalk SDK defaults
until a separate dependency-migration release is ready.

Disable DingTalk in all workspaces and restart before updating or removing
this plugin. The pilot refuses to unload code instantiated earlier in the
same process, including instances in retired workspaces. Do not change the
channel key, credential names, media paths or persisted session/card formats.

See `docs/dingtalk-plugin-pilot.md` in the QwenPaw repository for the test flow.
