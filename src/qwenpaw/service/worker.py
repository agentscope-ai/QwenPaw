# -*- coding: utf-8 -*-
"""在独立进程中校验和启动应用，环境由父进程预先注入。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from .config import ServiceConfig, ServiceError


def preflight(c):
    if not Path(c.python).is_file():
        raise ServiceError("配置的 Python 解释器不存在")
    if not shutil.which("git"):
        raise ServiceError("PATH 中未找到 Git，请安装 Git 并配置系统 PATH")
    if not c.working_dir.is_dir() or not (c.working_dir / "config.json").is_file():
        raise ServiceError("工作目录尚未初始化，请先使用 service exec init")
    bundled = Path(__file__).resolve().parents[1] / "console"
    static = os.getenv("QWENPAW_CONSOLE_STATIC_DIR")
    candidates = (
        [Path(static)]
        if static
        else [c.project_dir / "console/dist", bundled, bundled / "dist"]
    )
    if not any((p / "index.html").is_file() for p in candidates):
        raise ServiceError("前端资源不存在，请先构建 console")
    from qwenpaw.persistence.settings import load_database_settings
    from qwenpaw.persistence.repository_provider import validate_runtime_cutover

    settings = load_database_settings()
    if not settings.multi_user_enabled:
        raise ServiceError("正式实例必须显式配置 QWENPAW_MULTI_USER_ENABLED=true")
    asyncio.run(validate_runtime_cutover())
    print(
        json.dumps(
            {
                "check": "passed",
                "mode": "multi_user",
                "database": settings.safe_database_target,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def serve(c):
    import uvicorn
    import psutil
    from .manager import record_process

    # Windows venv 的 python.exe 可能是重定向父进程，登记真正的服务 PID。
    record_process(c, psutil.Process())
    from qwenpaw.app._app import app
    from qwenpaw.browser.control_link.chrome.protocol import NM_MAX_INBOUND_BYTES
    from qwenpaw.config.utils import write_last_api

    write_last_api("127.0.0.1" if c.host == "0.0.0.0" else c.host, c.port)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=c.host,
            port=c.port,
            workers=1,
            ws_max_size=NM_MAX_INBOUND_BYTES,
            timeout_graceful_shutdown=5,
            log_level="info",
        )
    )
    finished = threading.Event()

    def monitor():
        while not finished.wait(0.5):
            try:
                if c.stop_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    server.should_exit = True
                    return
            except OSError:
                pass

    threading.Thread(target=monitor, daemon=True).start()

    async def run_server():
        async def heartbeat():
            from qwenpaw.persistence.repository_provider import validate_runtime_cutover

            created = psutil.Process().create_time()
            while True:
                event = getattr(app.state, "startup_ready", None)
                healthy = bool(server.started and event and event.is_set())
                if healthy:
                    try:
                        await asyncio.wait_for(validate_runtime_cutover(), timeout=10)
                    except Exception:
                        healthy = False
                c.state_dir.mkdir(parents=True, exist_ok=True)
                target = c.state_dir / "health.json"
                staged = target.with_suffix(".new")
                staged.write_text(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "created": created,
                            "time": time.time(),
                            "ready": healthy,
                        }
                    ),
                    encoding="utf-8",
                )
                staged.replace(target)
                await asyncio.sleep(3)

        task = asyncio.create_task(heartbeat())
        try:
            await server.serve()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(run_server())
    finally:
        finished.set()
    if not server.started:
        raise ServiceError("应用启动未完成")


def upgrade(c):
    from alembic import command
    from alembic.config import Config
    from qwenpaw.persistence.settings import load_database_settings
    from qwenpaw.persistence.repository_provider import _database_schema

    settings = load_database_settings()
    if not settings.dsn:
        raise ServiceError("缺少 PostgreSQL 配置")
    ini = c.project_dir / "alembic.ini"
    if not ini.is_file():
        raise ServiceError("升级要求源码部署目录包含 alembic.ini 和 migrations")
    config = Config(str(ini))
    config.set_main_option("script_location", str(c.project_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.dsn.replace("%", "%%"))
    config.attributes["target_schema"] = _database_schema()
    command.upgrade(config, "head")
    print("数据库已升级到 head", flush=True)


def main():
    try:
        c = ServiceConfig.load(sys.argv[1])
        action = sys.argv[2]
        if action == "check":
            preflight(c)
        elif action == "serve":
            serve(c)
        elif action == "upgrade":
            upgrade(c)
        else:
            raise ServiceError("未知内部操作")
    except Exception as exc:
        # 数据库驱动异常可能包含 DSN，只展示已审核的错误码。
        detail = (
            str(exc)
            if isinstance(exc, ServiceError)
            else getattr(exc, "error_code", type(exc).__name__)
        )
        print(f"服务操作失败: {detail}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
