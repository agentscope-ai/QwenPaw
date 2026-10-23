"""Generic process observation; no channel RPC, SDK network or Agent."""
import os
import sys


class Worker:
    def bind(self, context):
        self.context = context
        context.peer.register_method("fixture.observe_context", self.observe)

    async def start(self, config):
        self.config = config

    async def stop(self):
        pass

    async def observe(self, params, request):
        from qwenpaw_channel_sip.stt_tts import _resolve_dashscope_key

        return {
            "pid": os.getpid(),
            "cwd": os.getcwd(),
            "environment": {
                name: os.environ.get(name)
                for name in (
                    "QQ_API_BASE",
                    "QQ_TOKEN_URL",
                    "QQ_PORTAL_HOST",
                    "DASHSCOPE_API_KEY",
                    "UNRELATED_HOST_SECRET",
                    "PYTHONPATH",
                    "PYTHONSTARTUP",
                    "LD_PRELOAD",
                    "DYLD_INSERT_LIBRARIES",
                )
            },
            "sip_explicit": _resolve_dashscope_key("explicit-test-key"),
            "sip_fallback": _resolve_dashscope_key(),
            "sys_path": list(sys.path),
            "loaded_support": {
                name: module.__file__
                for name, module in sys.modules.items()
                if name.startswith("qwenpaw.plugins.execution")
                and getattr(module, "__file__", None)
            },
        }
