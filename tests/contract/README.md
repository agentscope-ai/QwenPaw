# Contract tests

`BaseContractTest` and `ChannelContractTest` verify the interface of built-in `BaseChannel` implementations. The retained channel suite is `channels/test_console_contract.py`; its `create_instance()` factory constructs Console for checks such as required methods, signatures, attributes and session routing.

```sh
python scripts/check_channel_contracts.py
python -m pytest tests/contract/channels -q
```

The static checker describes built-in channels only. Official channel plugins have a different execution contract and are tested in `tests/unit/channels/test_<channel>.py`. Do not add legacy `BaseChannel` contract subclasses for these plugins.

Shared host and worker behavior belongs in `tests/unit/channels/test_channel_host.py` and `tests/unit/plugins/test_plugin_process.py`. See [channel test guidance](../unit/channels/README.md) for the current runner and coverage boundaries.

Contract checks establish interface compatibility; real lifecycle and message behavior still require the core behavioral tests. Avoid duplicating those tests in this directory.
