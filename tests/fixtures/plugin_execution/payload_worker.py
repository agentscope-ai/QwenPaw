"""Appended to the existing generic worker; actual RPC owns publication."""

import hashlib

from qwenpaw.plugins.execution.rpc import RpcResponsePublication


class PayloadWorker(Worker):
    def bind(self, context):
        super().bind(context)
        for name in ("echo", "reply", "reverse", "publication", "commit"):
            context.peer.register_method(
                "fixture.payload_" + name, getattr(self, "payload_" + name)
            )

    def record_payload(self, phase, params, request):
        encoded = json.dumps(
            params, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        with Path(MARKER).open("a") as ledger:
            ledger.write(
                json.dumps(
                    {
                        "phase": phase,
                        "request_id": request.id,
                        "pid": os.getpid(),
                        "bytes": len(encoded),
                        "sha256": hashlib.sha256(encoded).hexdigest(),
                    }
                )
                + "\n"
            )

    async def payload_echo(self, params, request):
        self.record_payload("echo", params, request)
        return params

    async def payload_reply(self, params, request):
        self.record_payload("reply", params, request)
        return {"text": "原文" * params["repetitions"]}

    async def payload_reverse(self, params, request):
        self.record_payload("reverse", params, request)
        return await self.context.peer.call("fixture.payload_host", params)

    async def payload_publication(self, params, request):
        def prepare():
            self.record_payload("prepare", params, request)
            return params

        return RpcResponsePublication(
            result=params,
            on_prepare=prepare,
            on_published=lambda: self.record_payload("published", params, request),
            on_write_failed=lambda: self.record_payload("write_failed", params, request),
            on_write_deferred=lambda: self.record_payload("deferred", params, request),
            on_aborted=lambda reason: self.record_payload("aborted:" + reason, params, request),
        )

    async def payload_commit(self, params, request):
        self.record_payload("commit", params, request)
        await asyncio.Event().wait()
