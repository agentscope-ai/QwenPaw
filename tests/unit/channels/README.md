# Channel tests

Each official channel has one `test_<channel>.py` file covering its core startup, shutdown and message delivery behavior. Tests replace external SDK/network boundaries where needed; they do not certify real robot credentials or native desktop releases.

Shared coverage lives in:

- `test_channel_host.py`: discovery, configuration, host routing and shared channel lifecycle.
- `../plugins/test_plugin_process.py`: worker execution, process ownership and cleanup.
- `../../contract/channels/test_console_contract.py`: the built-in Console channel's `BaseChannel` contract.
- `../../channel_support/`: shared fixtures used by the retained tests.

Official channel plugins use the channel protocol; they do not need a separate legacy `create_instance()` contract suite.

## Run

From the repository root, with project test dependencies installed:

```sh
./scripts/check-channels.sh feishu
./scripts/check-channels.sh --changed
./scripts/check-channels.sh all
python -m pytest tests/unit/channels/test_channel_host.py tests/unit/plugins/test_plugin_process.py -q
```

The runner treats selected core test failures as failures. `--changed` selects current uncommitted and untracked changes; shared channel code selects the full channel group. It is not a substitute for the repository's broader CI.

Keep new coverage in the existing channel, host or process file. Prefer a focused behavioral assertion over another full installation/reload cycle; retain real lifecycle execution where ownership, shutdown or recovery is the behavior being tested. Do not restore the retired fixture suites or duplicate them in helpers.
