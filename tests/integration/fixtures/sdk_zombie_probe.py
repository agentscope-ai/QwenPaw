# -*- coding: utf-8 -*-
"""Exercise adopted Linux zombies in an isolated subreaper process."""

import asyncio
import ctypes
import os
import signal
import subprocess
import sys

import psutil

from qwenpaw.plugins.resources import ResourceOwner, ResourceScope


async def main(asynchronous, separate_group):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0):  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "Cannot become a subreaper")
    resources = ResourceScope(ResourceOwner("zombie-probe", 1), lambda: None)
    code = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c',"
        "'import time; time.sleep(90)'], "
        f"process_group={0 if separate_group else -1}, "
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
        "stderr=subprocess.DEVNULL); print(p.pid,flush=True)"
    )
    args = [sys.executable, "-u", "-c", code]
    descendant = None
    try:
        if asynchronous:
            leader = await resources.async_process(
                args,
                tree=True,
                stdout=asyncio.subprocess.PIPE,
            )
            descendant = int(await leader.stdout.readline())
            await leader.wait()
        else:
            leader = resources.process(args, tree=True, stdout=subprocess.PIPE)
            descendant = int(await asyncio.to_thread(leader.stdout.readline))
            await asyncio.to_thread(leader.wait)
        assert psutil.Process(descendant).ppid() == os.getpid()
        os.kill(descendant, signal.SIGKILL)
        async with asyncio.timeout(3):
            while psutil.Process(descendant).status() != psutil.STATUS_ZOMBIE:
                await asyncio.sleep(0.01)
        await resources.close()
        assert resources.closed
        assert not psutil.pid_exists(descendant)
        assert resources.snapshot()["resources"] == ()
    finally:
        if descendant is not None and psutil.pid_exists(descendant):
            os.kill(descendant, signal.SIGKILL)
            os.waitpid(descendant, 0)
        await resources.close()


if __name__ == "__main__":
    asyncio.run(main(bool(int(sys.argv[1])), bool(int(sys.argv[2]))))
    print("ok")
