# -*- coding: utf-8 -*-
"""跨平台进程管理，实例锁与 PID 身份校验。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager

import psutil

from .config import ServiceError


@contextmanager
def instance_lock(c):
    c.state_dir.mkdir(parents=True, exist_ok=True)
    with (c.state_dir / "service.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ServiceError("另一个服务管理操作正在进行，请稍后重试") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def managed_process(c):
    try:
        state = json.loads(c.pid_file.read_text(encoding="utf-8"))
        p = psutil.Process(state["pid"])
        if abs(p.create_time() - state["created"]) > 0.01:
            return None
        args = p.cmdline()
        marker = args.index("qwenpaw.service.worker")
        if args[marker + 1 : marker + 3] != [str(c.path), "serve"]:
            return None
        return p
    except (OSError, ValueError, KeyError, IndexError, psutil.Error):
        return None


def ready(c):
    try:
        p = managed_process(c)
        state = json.loads((c.state_dir / "health.json").read_text(encoding="utf-8"))
        return bool(
            p
            and state["pid"] == p.pid
            and abs(state["created"] - p.create_time()) < 0.01
            and state["ready"]
            and 0 <= time.time() - state["time"] < 30
        )
    except (OSError, ValueError, KeyError, psutil.Error):
        return False


def check(c):
    result = subprocess.run(
        c.command("check"), cwd=c.project_dir, env=c.child_env(), timeout=45
    )
    if result.returncode:
        raise ServiceError("部署检查失败，请按上述检查结果修正配置")


def assert_port_available(c):
    family = socket.AF_INET6 if ":" in c.host else socket.AF_INET
    with socket.socket(family) as probe:
        try:
            probe.bind((c.host, c.port))
        except OSError:
            raise ServiceError(
                f"端口 {c.port} 已占用或无法绑定，未启动新进程"
            ) from None


def record_process(c, child):
    try:
        created = psutil.Process(child.pid).create_time()
    except psutil.Error:
        raise ServiceError(f"进程立即退出，查看 {c.log_dir / 'service.log'}") from None
    c.pid_file.write_text(
        json.dumps({"pid": child.pid, "created": created}), encoding="utf-8"
    )


def foreground(c):
    with instance_lock(c):
        if managed_process(c):
            raise ServiceError("已有实例正在运行")
        check(c)
        assert_port_available(c)
        c.stop_file.unlink(missing_ok=True)
        child = subprocess.Popen(
            c.command("serve"), cwd=c.project_dir, env=c.child_env()
        )
        record_process(c, child)
    try:
        return child.wait()
    except KeyboardInterrupt:
        # Windows/POSIX 控制台信号也会到达子进程，停止文件为额外保障。
        stop(c)
        return child.wait(timeout=5)


def status(c):
    p = managed_process(c)
    if p is None:
        return {"state": "stopped", "port": c.port}
    return {
        "state": "ready" if ready(c) else "starting_or_unhealthy",
        "pid": p.pid,
        "port": c.port,
    }


def start(c):
    with instance_lock(c):
        if managed_process(c):
            result = status(c)
            if result["state"] != "ready":
                raise ServiceError("已有服务尚未就绪或不健康，请运行 status/logs 检查")
            return result
        check(c)
        assert_port_available(c)
        c.log_dir.mkdir(parents=True, exist_ok=True)
        c.stop_file.unlink(missing_ok=True)
        options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        with (c.log_dir / "service.log").open("ab") as log:
            child = subprocess.Popen(
                c.command("serve"),
                cwd=c.project_dir,
                env=c.child_env(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                **options,
            )
        record_process(c, child)
        deadline = time.monotonic() + c.timeout
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise ServiceError(f"服务启动失败，查看 {c.log_dir / 'service.log'}")
            if ready(c):
                return status(c)
            time.sleep(0.5)
        raise ServiceError(
            "等待就绪超时；进程保留供诊断，请运行 status/logs，必要时 stop"
        )


def stop(c, force=False):
    with instance_lock(c):
        p = managed_process(c)
        if p is None:
            return {"state": "stopped"}
        c.stop_file.write_text(str(p.pid), encoding="utf-8")
        try:
            p.wait(timeout=20)
        except psutil.TimeoutExpired:
            if not force:
                raise ServiceError(
                    "正常关闭超时；检查日志，或显式使用 stop --force"
                ) from None
            # 强制操作前再次校验，避免 PID 被其他进程复用。
            p = managed_process(c)
            if p:
                p.kill()
                p.wait(timeout=10)
        c.pid_file.unlink(missing_ok=True)
        c.stop_file.unlink(missing_ok=True)
        return {"state": "stopped"}
