"""Generic sample's actual SDK boundary rejects or waits, without host mocks."""

from wechat_merge_support import merge_source


def sdk_fault_source(directory, key, *, capabilities=None):
    source = merge_source(directory, key, capabilities=capabilities)
    sdk = source / key / "sdk.py"
    sdk.write_text(
        sdk.read_text()
        + "\nasync def before_send(mode):\n"
        + '    if mode == "sdk-refused":\n'
        + '        raise DeliveryError("SDK_REFUSED", '
        + "side_effect_possible=False)\n"
    )
    sdk.write_text(
        sdk.read_text()
        + "\nimport asyncio\nfrom pathlib import Path\n"
        + "async def before_finish():\n"
        + "    root = Path(__file__).resolve().parents[2]\n"
        + "    if not (root / 'finish-block').exists():\n        return\n"
        + "    (root / 'finish-started').touch()\n"
        + "    while not (root / 'finish-release').exists():\n"
        + "        await asyncio.sleep(0.01)\n"
    )
    driver = source / key / "driver.py"
    driver.write_text(
        driver.read_text()
        .replace(
            "    async def effect(self, operation, params):\n",
            "    async def effect(self, operation, params):\n"
            "        from .sdk import before_send\n"
            "        await before_send(self.fault)\n",
            1,
        )
        .replace(
            "    async def _before_cleanup_complete(self, snapshot):\n",
            "    async def _before_cleanup_complete(self, snapshot):\n"
            "        from .sdk import before_finish\n"
            "        await before_finish()\n",
            1,
        )
    )
    return source
