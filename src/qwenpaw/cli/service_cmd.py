# -*- coding: utf-8 -*-
"""正式多用户实例的部署和生命周期命令。"""

from __future__ import annotations

import json
import subprocess
import time
from collections import deque
from pathlib import Path

import click

from ..service.config import ServiceConfig, ServiceError
from ..service import manager


@click.group("service")
@click.option(
    "--config",
    "config_path",
    default="deploy/service.local.json",
    show_default=True,
    type=click.Path(path_type=Path),
    help="实例 JSON 配置文件",
)
@click.pass_context
def service_group(ctx, config_path):
    """部署、启动、停止和检查多用户服务。"""
    ctx.ensure_object(dict)
    ctx.obj["service_config_path"] = config_path


def config():
    try:
        return ServiceConfig.load(
            click.get_current_context().obj["service_config_path"]
        )
    except ServiceError as exc:
        raise click.ClickException(str(exc)) from None


def execute(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        if result is not None:
            click.echo(json.dumps(result, ensure_ascii=False))
    except ServiceError as exc:
        raise click.ClickException(str(exc)) from None
    except (OSError, subprocess.SubprocessError):
        raise click.ClickException(
            "子进程执行失败或超时，请检查解释器、目录和日志"
        ) from None


@service_group.command("init")
@click.pass_context
def init_cmd(ctx):
    """生成实例配置模板；不覆盖配置或初始化数据库。"""
    path = ctx.obj["service_config_path"].resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    from ..service.template import example_config

    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(example_config(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        path.chmod(0o600)
    except FileExistsError:
        raise click.ClickException("配置已存在，未覆盖") from None
    click.echo(f"已生成 {path}，请填写数据库和目录配置")


@service_group.command("check")
def check_cmd():
    """检查依赖、前端、数据库版本与多用户切换条件。"""
    execute(manager.check, config())


@service_group.command("start")
def start_cmd():
    """后台启动，重复调用不会启动第二个实例。"""
    execute(manager.start, config())


@service_group.command("status")
def status_cmd():
    """输出进程和核心智能体就绪状态；未就绪返回非零。"""
    c = config()
    result = manager.status(c)
    click.echo(json.dumps(result, ensure_ascii=False))
    if result["state"] != "ready":
        raise click.exceptions.Exit(1)
    execute(manager.check, c)


@service_group.command("stop")
@click.option("--force", is_flag=True, help="正常退出超时后强制终止已核验的服务进程")
def stop_cmd(force):
    """正常停止当前实例。"""
    execute(manager.stop, config(), force=force)


@service_group.command("restart")
def restart_cmd():
    """正常停止后重新读取同一配置并启动。"""
    c = config()
    execute(manager.stop, c)
    execute(manager.start, c)


@service_group.command("run")
def run_cmd():
    """前台运行，供调试或 systemd/任务计划程序托管。"""

    def run():
        raise click.exceptions.Exit(manager.foreground(config()))

    execute(run)


@service_group.command("exec", context_settings={"ignore_unknown_options": True})
@click.argument("arguments", nargs=-1, required=True, type=click.UNPROCESSED)
def exec_cmd(arguments):
    """在实例环境执行 QwenPaw 子命令，例如 exec init。"""
    c = config()
    result = subprocess.call(
        [c.python, "-m", "qwenpaw", *arguments], cwd=c.project_dir, env=c.child_env()
    )
    raise click.exceptions.Exit(result)


@service_group.command("database-upgrade")
@click.option("--yes", is_flag=True, help="已备份并明确允许升级所选数据库 schema")
def database_upgrade_cmd(yes):
    """显式升级数据库；普通启动不会执行迁移。"""
    c = config()
    if not yes:
        raise click.ClickException(
            "请先停服、备份并确认目标，再使用 --yes 执行数据库升级"
        )
    with manager.instance_lock(c):
        if manager.managed_process(c):
            raise click.ClickException("请先停止服务再升级数据库")
        execute(manager.assert_port_available, c)
        result = subprocess.call(
            c.command("upgrade"), cwd=c.project_dir, env=c.child_env()
        )
        raise click.exceptions.Exit(result)


@service_group.command("logs")
@click.option("--lines", default=100, type=click.IntRange(1, 10000))
@click.option("--follow", is_flag=True, help="持续显示新日志，Ctrl+C 退出")
def logs_cmd(lines, follow):
    """读取后台启动日志。"""
    path = config().log_dir / "service.log"
    if not path.exists():
        click.echo(f"尚无启动日志：{path}")
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        click.echo("".join(deque(handle, maxlen=lines)), nl=False)
        try:
            while follow:
                chunk = handle.read()
                if chunk:
                    click.echo(chunk, nl=False)
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
