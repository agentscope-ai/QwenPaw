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
|- frontend/                    Console UI sources (approval card, settings)
|- dist/index.js                Built console UI bundle (committed artifact)
|- skills/computer_use/         Tool operating guidance
`- tests/                       Adapter contract tests
```

The plugin has no Python GUI automation dependencies.

## Console UI

The manifest points `entry.frontend` at `dist/index.js`. That bundle is a build
artifact of `frontend/`, and it is committed rather than gitignored so the
plugin installs on a machine with no npm toolchain -- the same arrangement
`plugins/bundle/qwenpaw-pet` uses, and the reason the repository `.gitignore`
carries an exception for this path.

It therefore has to be rebuilt and committed alongside any edit under
`frontend/src/`, or the console keeps running the previous UI:

```bash
cd frontend && npm install && npm run build
```

