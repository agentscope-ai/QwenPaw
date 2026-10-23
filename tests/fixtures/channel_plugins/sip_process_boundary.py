"""Native SDK boundary loaded only inside the actual shared worker."""
import asyncio
import json
import os
from pathlib import Path
import sys

from .vendor_boundary import Vendor

WORK = globals()["WORK"]  # Injected literal in the copied test entrypoint.
vendor = Vendor()
for name, module in vendor.modules().items():
    sys.modules[name] = module
from .driver import SIPDriver

__all__ = ["SIPDriver"]


def record(kind, **values):
    with (Path(WORK) / "ledger.jsonl").open("a") as stream:
        stream.write(
            json.dumps({"kind": kind, "pid": os.getpid(), **values}) + "\n"
        )


async def commands():
    count = 0
    seen = set()
    try:
        while not (Path(WORK) / "stop-boundary").exists():
            inbox = Path(WORK) / "inbox.jsonl"
            rows = inbox.read_text().splitlines() if inbox.exists() else []
            for line in rows[count:]:
                value = json.loads(line)
                if value["kind"] == "incoming":
                    vendor.phones[0].incoming(
                        value["call_id"], value["sender"]
                    )
                elif value["kind"] == "transcript":
                    vendor.asrs[-1].sentence(value["text"])
                elif value["kind"] == "fail_write":
                    vendor.fail_write = value["value"]
                count += 1
                record("command", number=count)
            for i, asr in enumerate(vendor.asrs):
                if ("asr", i) not in seen:
                    seen.add(("asr", i))
                    record("asr", key=asr.kwargs["api_key"])
            for phone in vendor.phones:
                for call in phone.calls:
                    for i, data in enumerate(call.writes):
                        if (id(call), i) not in seen:
                            seen.add((id(call), i))
                            record("audio", hex=data.hex())
            await asyncio.sleep(0.005)
    finally:
        record("boundary-stopped")


record(
    "loaded",
    sdk_modules=[
        name
        for name in sys.modules
        if name in ("pyVoIP", "dashscope_realtime")
    ],
)
boundary_task = asyncio.create_task(commands())
