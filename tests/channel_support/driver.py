# -*- coding: utf-8 -*-
"""Load real channel code and model only its host RPC boundary."""

import importlib
import json
from pathlib import Path
import sys

from qwenpaw.channel_protocol.models import IdentityParams
from qwenpaw.channel_protocol.response_receipts import ResponseReceiptStore
from qwenpaw.channel_protocol.shared_worker import DriverContext

ROOT = Path(__file__).resolve().parents[2]


def module(key, leaf="driver"):
    root = ROOT / "plugins" / "channel" / key
    descriptor = json.loads(
        (root / "channel.json").read_text(encoding="utf-8"),
    )
    package = descriptor["entrypoint"]["module"].rpartition(".")[0]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module(f"{package}.{leaf}")


class HostPeer:
    def __init__(self, root):
        self.methods, self.state = {}, {}
        self.batches, self.notifications, self.calls = [], [], []
        self.receipts = ResponseReceiptStore(root / "receipts.sqlite3")

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def call(self, name, params):
        self.calls.append((name, params))
        if name == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if name == "host.state.put":
            self.state[params["key"]] = json.loads(
                json.dumps(params["value"]),
            )
            return {"stored": True}
        if name == "host.receipt.get":
            return {"value": self.receipts.get(params["key"])}
        if name == "host.receipt.put":
            self.receipts.put(params["key"], params["value"])
            return {"stored": True}
        if name == "event.batch":
            self.batches.append(params)
            return {
                "batch_id": params["batch_id"],
                "accepted_event_ids": [
                    event["event_id"] for event in params["events"]
                ],
            }
        if name.startswith("ingress.endpoint."):
            operation = name.rsplit(".", 1)[1]
            result = {
                "status": {
                    "register": "registered",
                    "update": "updated",
                    "unregister": "unregistered",
                }[operation],
                "generation": params["generation"],
            }
            if operation != "unregister":
                result["readiness"] = params["readiness"]
            return result
        raise AssertionError(f"Unexpected host call: {name}")

    async def notify(self, name, params):
        self.notifications.append((name, params))


def bind(key, driver, tmp_path):
    descriptor = json.loads(
        (ROOT / "plugins" / "channel" / key / "channel.json").read_text(
            encoding="utf-8",
        ),
    )
    peer = HostPeer(tmp_path)
    identity = IdentityParams(key, f"test-{key}", 1)
    driver.bind(DriverContext(peer, identity, descriptor["capabilities"]))
    return peer, identity
