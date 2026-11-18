# -*- coding: utf-8 -*-
import asyncio
from concurrent.futures import ThreadPoolExecutor

from utils.io_pool import configure_io_thread_pool


def test_unset_and_presupplied_host_pool_are_untouched(monkeypatch):
    async def check():
        loop = asyncio.get_running_loop()
        monkeypatch.delenv("CREATOR_IO_THREADS", raising=False)
        assert configure_io_thread_pool() == 0
        host = ThreadPoolExecutor(max_workers=2)
        loop.set_default_executor(host)
        monkeypatch.setenv("CREATOR_IO_THREADS", "4")
        assert configure_io_thread_pool() == 0
        assert loop._default_executor is host

    asyncio.run(check())


def test_explicit_pool_is_configured_once_per_loop(monkeypatch):
    monkeypatch.setenv("CREATOR_IO_THREADS", "4")

    async def check():
        assert configure_io_thread_pool() == 4
        assert configure_io_thread_pool() == 0

    asyncio.run(check())
    asyncio.run(check())
