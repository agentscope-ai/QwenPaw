"""Isolated adjacent start/error contract; no Agent or Service replacement."""
import asyncio
import importlib.abc
import json
from pathlib import Path
import sys

root, mode = Path(sys.argv[1]), sys.argv[2]
sys.path[:0] = [str(root / "src"), str(root / "plugins/channel/feishu")]
attempts = []


class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "lark_oapi" or fullname.startswith("lark_oapi."):
            attempts.append(fullname)
            raise ImportError("CONTROLLED_SDK_IMPORT_FAILURE")


guard = Guard()
sys.meta_path.insert(0, guard)
from feishu.driver import FeishuDriver, FeishuDeliveryError
from feishu.errors import FeishuDeliveryError as SharedError
from qwenpaw.channel_protocol.models import IdentityParams
from qwenpaw.channel_protocol.shared_worker import DriverContext

assert not attempts
assert "feishu.platform" not in sys.modules
assert FeishuDeliveryError is SharedError
error = SharedError("DELIVERY", side_effect_possible=True, retryable=True)
assert str(error) == "DELIVERY"
assert (
    error.reason_code == "DELIVERY"
    and error.side_effect_possible
    and error.retryable
)


class Peer:
    def __init__(self):
        self.states = []

    def register_method(self, name, handler):
        pass

    async def notify(self, method, params):
        assert method == "shared.state"
        self.states.append(params["platform_state"])


class PrepareFailure(RuntimeError):
    pass


async def run():
    driver = FeishuDriver()
    peer = Peer()
    driver.bind(
        DriverContext(peer, IdentityParams("feishu", "start-boundary", 1))
    )
    original = {
        "app_id": "app",
        "app_secret": "private-app-secret",
        "encrypt_key": "private-encryption",
        "verification_token": "private-verification",
    }
    secret_reference = None
    platform = None
    if mode == "prepare":
        sys.meta_path.remove(guard)
        import feishu.platform as platform_module

        assert "lark_oapi" in sys.modules
        assert platform_module.FeishuDeliveryError is SharedError
        assert "FeishuDeliveryError" in platform_module.__all__

        class Platform:
            def __init__(self):
                self.closed = 0

            async def prepare(self, config, secret, media_dir):
                nonlocal secret_reference
                secret_reference = secret
                assert secret["app_secret"] == original["app_secret"]
                assert "app_secret" not in config
                raise PrepareFailure("PREPARE_FAILED")

            async def close(self):
                self.closed += 1

        platform = Platform()
        platform_module.LarkOapiPlatform = lambda: platform
    try:
        await driver.start(original)
    except (ImportError, PrepareFailure) as error:
        if mode == "import":
            assert isinstance(error, ImportError) and attempts == ["lark_oapi"]
        else:
            assert isinstance(error, PrepareFailure)
        tb = error.__traceback__
        while tb and tb.tb_frame.f_code.co_name != "start":
            tb = tb.tb_next
        assert tb is not None and tb.tb_frame.f_locals["secret"] == {}
    else:
        raise AssertionError("start failure was swallowed")
    assert peer.states == ["failed"]
    assert not driver._connected
    assert (
        not {"app_secret", "encrypt_key", "verification_token"}
        & driver._config.keys()
    )
    assert original["app_secret"] == "private-app-secret"
    if mode == "prepare":
        assert secret_reference == {}
        assert driver._platform is platform
    await driver.stop()
    assert peer.states == ["failed", "disconnected"]
    assert driver._platform is None
    if platform:
        assert platform.closed == 1
    print(json.dumps({"mode": mode, "passed": True}))


asyncio.run(run())
