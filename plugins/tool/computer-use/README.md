# Computer Use

Computer Use is a desktop plugin backed by the QwenPaw desktop host, supported
on Windows and macOS. The Python plugin contains only the tool adapter,
approval bridge, and usage skill. Window discovery, screen capture,
accessibility inspection, input injection, and target validation run in the
host-managed native helper.

The helper is not installed from this directory. It is packaged with the
desktop application and receives a short-lived private transport capability
from the host (a named pipe on Windows, a Unix domain socket on macOS).

## Layout

```text
computer-use/
|- plugin.py                    Plugin registration
|- computer_use_tool/           Protocol adapter and approval bridge
|- skills/computer-use/         Tool operating guidance
`- tests/                       Adapter contract tests
```

The plugin has no Python GUI automation dependencies.
