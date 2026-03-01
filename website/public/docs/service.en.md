# Service management

`copaw service` registers CoPaw as a system service for **background execution** and **auto-start on boot**, replacing the `nohup copaw app &` approach.

> Don't need background mode? Just use `copaw app` to run in the foreground. See [CLI](./cli).

---

## Before vs. after

**Before** (foreground, stops when terminal closes):

```bash
pip install copaw
copaw init --defaults
copaw app                      # foreground
# or
nohup copaw app > copaw.log 2>&1 &   # background, lost after reboot
```

**Now** (system service, auto-starts on boot):

```bash
pip install copaw
copaw init --defaults
copaw service install          # register + enable auto-start
copaw service start            # start now
```

> If you used `install.sh` or `install.ps1`, `copaw service install` runs automatically during installation.

### Day-to-day comparison

| Task         | Before                             | Now                     |
| ------------ | ---------------------------------- | ----------------------- |
| Start        | `copaw app` or `nohup copaw app &` | `copaw service start`   |
| Stop         | Ctrl+C or `kill <pid>`             | `copaw service stop`    |
| Restart      | stop then start manually           | `copaw service restart` |
| Status       | `ps aux \| grep copaw`             | `copaw service status`  |
| Logs         | terminal output or nohup.out       | `copaw service logs`    |
| After reboot | must restart manually              | starts automatically    |

### Impact on existing commands

`copaw app` still works exactly as before. Use `copaw app` for development/debugging (see output directly), `copaw service` for long-term deployment (background + auto-start). Do not use both on the same port simultaneously.

---

## Supported platforms

| Platform | Backend        | Level                                | Auto-start trigger          |
| -------- | -------------- | ------------------------------------ | --------------------------- |
| Linux    | systemd        | User (default) / System (`--system`) | At boot (no login required) |
| macOS    | launchd        | User LaunchAgent                     | At user login               |
| Windows  | Task Scheduler | User task                            | At user login               |

---

## Command reference

### copaw service install

Install and enable the service.

```bash
copaw service install                          # default 127.0.0.1:8088
copaw service install --host 0.0.0.0 --port 9090   # custom address
copaw service install --system                 # system-wide (Linux only, needs sudo)
```

| Option     | Default     | Description                      |
| ---------- | ----------- | -------------------------------- |
| `--host`   | `127.0.0.1` | Bind host                        |
| `--port`   | `8088`      | Bind port                        |
| `--system` | no          | System-wide service (Linux only) |

To change parameters, just re-install — new config overwrites the old one:

```bash
copaw service install --host 0.0.0.0 --port 9090
```

### copaw service uninstall

Stop and remove the service.

```bash
copaw service uninstall          # interactive confirmation
copaw service uninstall --yes    # skip confirmation
copaw service uninstall --system # remove system-wide service (Linux only)
```

### copaw service start / stop / restart

```bash
copaw service start              # start
copaw service stop               # stop
copaw service restart            # restart
```

### copaw service status

Show current service status. Output varies by platform:

- **Linux**: full `systemctl status` output (PID, memory, recent logs)
- **macOS**: PID and state from launchd
- **Windows**: `schtasks /Query` task details

### copaw service logs

View service logs.

```bash
copaw service logs               # last 50 lines
copaw service logs -n 100        # last 100 lines
copaw service logs -f            # follow (Ctrl+C to stop)
```

| Option            | Default | Description                |
| ----------------- | ------- | -------------------------- |
| `-n` / `--lines`  | `50`    | Number of lines to show    |
| `-f` / `--follow` | off     | Continuously follow output |

Log sources: Linux uses `journalctl`; macOS and Windows read log files in `~/.copaw/logs/`.

---

## Platform details

### Linux (systemd)

#### User service (default)

`copaw service install` will:

1. Create `~/.config/systemd/user/copaw.service`
2. Run `systemctl --user enable copaw`
3. Run `loginctl enable-linger` so the service starts at boot without login

Generated unit file example:

```ini
[Unit]
Description=CoPaw Personal Assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/<user>/.copaw/venv/bin/copaw app --host 127.0.0.1 --port 8088
Restart=on-failure
RestartSec=5
Environment=COPAW_WORKING_DIR=/home/<user>/.copaw

[Install]
WantedBy=default.target
```

#### System-wide service (`--system`)

Writes to `/etc/systemd/system/copaw.service` (needs sudo), with `WantedBy=multi-user.target`.

### macOS (launchd)

`copaw service install` creates `~/Library/LaunchAgents/com.copaw.app.plist`:

- `RunAtLoad=true` — starts at login
- `KeepAlive=true` — auto-restarts on crash
- Logs to `~/.copaw/logs/copaw.log` and `~/.copaw/logs/copaw.err`

> `--system` is not supported on macOS. System-wide LaunchDaemons require root and manual configuration.

### Windows (Task Scheduler)

`copaw service install` creates a scheduled task named `CoPaw` via PowerShell:

- Trigger: at user logon (AtLogOn)
- Runs on battery, does not stop when switching to battery
- Restarts 3 times on failure, 1-minute interval
- No execution time limit

To inspect: press `Win+R`, type `taskschd.msc`, find `CoPaw` in the library.

> `--system` is ignored on Windows. For a true Windows Service (runs without user login), consider [NSSM](https://nssm.cc/):
>
> ```cmd
> nssm install CoPaw C:\Users\<user>\.copaw\venv\Scripts\copaw.exe app --host 127.0.0.1 --port 8088
> ```

---

## File impact

### Files created

| Platform | Path                                         | Description                               |
| -------- | -------------------------------------------- | ----------------------------------------- |
| Linux    | `~/.config/systemd/user/copaw.service`       | systemd user unit file                    |
| Linux    | `/etc/systemd/system/copaw.service`          | System unit file (`--system`, needs sudo) |
| macOS    | `~/Library/LaunchAgents/com.copaw.app.plist` | launchd user agent plist                  |
| All      | `~/.copaw/logs/`                             | Log directory                             |

### System state changes

| Platform | Change         | Description                                                |
| -------- | -------------- | ---------------------------------------------------------- |
| Linux    | systemd enable | `systemctl --user enable copaw`                            |
| Linux    | linger         | `loginctl enable-linger` — user service runs without login |
| macOS    | launchd job    | `launchctl load/unload`                                    |
| Windows  | Task Scheduler | `Register-ScheduledTask` / `schtasks`                      |

`copaw service uninstall` reverses all of the above. `copaw uninstall` also auto-detects and cleans up the service.

---

## Troubleshooting

### Linux: service doesn't start after reboot

Check that linger is enabled:

```bash
loginctl show-user $(whoami) --property=Linger
```

If it shows `Linger=no`:

```bash
loginctl enable-linger $(whoami)
```

### macOS: service exits immediately after start

Check the error log:

```bash
copaw service logs
# or directly
cat ~/.copaw/logs/copaw.err
```

Common causes: port already in use, missing config, broken Python environment.

### Windows: how to see the scheduled task

Press `Win+R`, type `taskschd.msc`. Or via command line:

```cmd
schtasks /Query /TN CoPaw /V
```

---

## Related pages

- [Quick start](./quickstart) — Install and first run
- [CLI](./cli) — Full command reference
- [Config & working directory](./config) — Working dir and config.json
