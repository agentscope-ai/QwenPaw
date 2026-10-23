"""A stop reply failure must not become a clean exit by closing stdin."""

from dataclasses import replace

import pytest

from process_suite import api, launch, processes, digest, alive


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["acknowledged", "error", "receipt-lost"])
async def test_nonchannel_real_stop_requires_ack_or_actual_owned_signal(
    api, launch, processes, outcome
):
    spec, marker = launch()
    source = spec.code_root / "worker.py"
    with source.open("a") as output:
        output.write(
            "\nasync def controlled_stop(self):\n"
            "    Path(MARKER).write_text('stop-entered')\n"
            + (
                "    raise RuntimeError('component close failed')\n"
                if outcome == "error"
                else (
                    "    await asyncio.Event().wait()\n"
                    if outcome == "receipt-lost"
                    else "    return None\n"
                )
            )
            + "Worker.stop = controlled_stop\n"
        )
    spec = replace(spec, source_revision=digest(spec.code_root))
    process = processes()
    await process.start(spec)
    pid = process.health_snapshot()["pid"]
    assert alive(pid)
    result = await process.stop()
    assert marker.read_text() == "stop-entered"
    assert result.exited
    assert not alive(pid)
    if outcome == "acknowledged":
        assert result.forced is False
        assert result.returncode == 0
    else:
        assert result.forced is True
        assert result.returncode != 0
