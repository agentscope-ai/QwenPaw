"""Run the retained native gateway mock outside the actual Core process."""

import asyncio
from importlib import import_module
import json
import os
from pathlib import Path
import sys

import psutil

ROOT, DIRECTORY = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).parent)]

web = import_module("aiohttp.web")
native = import_module("yuanbao_native_support")
YuanbaoExternal, inbound = native.YuanbaoExternal, native.inbound


class Gateway(YuanbaoExternal):
    async def http_request(self, request):
        if request.path == "/_test/activation":
            self.activation = await request.json()
            self.activation_observations = []
            return web.json_response({"ok": True})
        if request.path == "/_test/push":
            value = await request.json()
            await self.push(inbound(**value))
            return web.json_response({"ok": True})
        if request.path == "/_test/kickout":
            codec = native.codec
            raw = codec.encode_pb(
                codec.KICKOUT_MSG, {"reason": "test kickout"}
            )
            assert raw is not None
            await self.ws.send_bytes(
                codec.encode_conn_msg(
                    {
                        "cmdType": codec.CMD_TYPE_PUSH,
                        "cmd": codec.CMD_KICKOUT,
                        "seqNo": 1,
                        "msgId": "test-kickout",
                        "module": codec.MODULE_CONN_ACCESS,
                    },
                    raw,
                )
            )
            return web.json_response({"ok": True})
        if request.path == "/_test/state":
            return web.json_response(
                {
                    "pid": os.getpid(),
                    "sends": self.sends,
                    "frames": [{"head": row["head"]} for row in self.frames],
                    "calls": [
                        {k: v for k, v in row.items() if k != "raw"}
                        for row in self.calls
                    ],
                    "connections": len(self.connections),
                    "open_connections": sum(
                        not ws.closed for ws in self.connections
                    ),
                    "activation_observations": getattr(
                        self, "activation_observations", []
                    ),
                }
            )
        if request.path == "/_test/behavior":
            self.behaviors.append((await request.json())["value"])
            return web.json_response({"ok": True})
        if request.path == "/_test/stop":
            STOP.set()
            return web.json_response({"ok": True})
        activation = getattr(self, "activation", None)
        if activation and request.path == "/api/v5/robotLogic/sign-token":
            version = json.loads(
                Path(activation["manifest_path"]).read_text()
            )["version"]
            self.activation_observations.append(
                {
                    "version": version,
                    "old_worker_alive": psutil.pid_exists(
                        activation["old_pid"]
                    ),
                }
            )
            if version == activation["fail_version"]:
                return web.json_response(
                    {"code": 403, "msg": "controlled candidate refusal"}
                )
        return await super().http_request(request)


async def main():
    gateway = await Gateway(DIRECTORY).start()
    try:
        (DIRECTORY / "ready.json").write_text(
            json.dumps(
                {
                    "base": gateway.base,
                    "ws_url": gateway.ws_url,
                    "pid": os.getpid(),
                }
            )
        )
        await STOP.wait()
    finally:
        await gateway.stop()


STOP = asyncio.Event()
asyncio.run(main())
