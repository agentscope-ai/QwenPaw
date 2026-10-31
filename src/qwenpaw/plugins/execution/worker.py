# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Absolute-path worker; only trusted stdlib mechanics run before stdin."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import types
from typing import Any


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        "_qwenpaw_execution_" + name,
        Path(__file__).with_name(name + ".py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("BOOTSTRAP_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _configure(
    boot: Any,
    packet: dict[str, Any],
    protected_namespaces: tuple[str, ...],
) -> None:
    root = boot._absolute_existing_directory(packet["code_root"], "code_root")
    support = Path(__file__).resolve().parents[3]
    if support != Path(packet["support_root"]).resolve(strict=True):
        raise RuntimeError("BOOTSTRAP_UNAVAILABLE")
    # Keep trusted execution support ahead of any plugin-provided namespace.
    for namespace in (
        "qwenpaw/plugins/execution",
        "qwenpaw/plugins/execution.py",
        *protected_namespaces,
    ):
        if (root / namespace).exists() or (root / namespace).is_symlink():
            raise RuntimeError("BOOTSTRAP_UNAVAILABLE")
    packet["_audit_sites"] = [
        *packet["dependency_paths"],
        *(item for item in sys.path if item),
    ]
    sys.dont_write_bytecode = True
    inherited = [
        item
        for item in sys.path
        if item and Path(item).resolve() not in {root, support}
    ]
    stdlib = {
        Path(value).resolve()
        for value in (
            sysconfig.get_path("stdlib"),
            sysconfig.get_path("platstdlib"),
        )
        if value
    }
    zip_name = f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    standard_paths = {
        *stdlib,
        *((path.parent / zip_name).resolve() for path in stdlib),
        (Path(sys.base_prefix) / zip_name).resolve(),
    }
    extension_path = sysconfig.get_config_var("DESTSHARED")
    if extension_path:
        standard_paths.add(Path(extension_path).resolve())
    if sys.platform == "win32":
        standard_paths.add((Path(sys.base_exec_prefix) / "DLLs").resolve())
    # Explicit sites preserve their order after trusted bootstrap/stdlib.
    dependencies = [
        str(boot._absolute_existing_directory(value, "dependency_path"))
        for value in packet["dependency_paths"]
    ]
    sys.path[:] = list(
        dict.fromkeys(
            [str(support)]
            + [
                item
                for item in inherited
                if Path(item).resolve() in standard_paths
            ]
            + dependencies
            + inherited,
        ),
    )
    lease_spec = importlib.util.spec_from_file_location(
        "_qwenpaw_dependency_maintenance",
        Path(__file__).resolve().parents[1] / "dependency_maintenance.py",
    )
    if lease_spec is None or lease_spec.loader is None:
        raise RuntimeError("BOOTSTRAP_UNAVAILABLE")
    custody = importlib.util.module_from_spec(lease_spec)
    sys.modules[lease_spec.name] = custody
    lease_spec.loader.exec_module(custody)
    custody.state_root()
    # Reuse this context if trusted support imports the module later.
    sys.modules["qwenpaw.plugins.dependency_maintenance"] = custody
    custody.lease_environment(
        (*dependencies, *custody.host_sites()),
        parent_pid=int(sys.argv[1])
        if packet.get("mode") in {"audit", "probe"}
        else None,
        timeout=packet["startup_timeout"],
    )
    package = types.ModuleType("qwenpaw")
    package.__package__ = "qwenpaw"
    package.__path__ = [str(support / "qwenpaw")]
    sys.modules["qwenpaw"] = package
    plugins = types.ModuleType("qwenpaw.plugins")
    plugins.__package__ = "qwenpaw.plugins"
    plugins.__path__ = [str(support / "qwenpaw/plugins")]
    sys.modules["qwenpaw.plugins"] = plugins
    # Direct path assignment never executes additional .pth files.
    boot._clean_environment(())
    private_env = boot.validate_private_environment(
        packet.get("private_env", {}),
    )
    if private_env and packet.get("mode", "run") not in {"run", "manage"}:
        raise RuntimeError("LAUNCH_ENVIRONMENT_INVALID")
    os.environ.update(private_env)


async def run(
    boot: Any,
    packet: dict[str, Any],
    output: Any,
    runtime: Any,
    *,
    input_handle: Any,
) -> None:
    from .errors import ProtocolValidationError
    from .framing import FramedTransport
    from .payloads import PayloadStore
    from .rpc import RpcResponsePublication

    payloads = (
        PayloadStore.attach(packet["payload_transport"])
        if "payload_transport" in packet
        else None
    )
    transport = await boot._open_protocol_transport(
        FramedTransport,
        output,
        input_handle=input_handle,
        payloads=payloads,
    )
    peer = runtime.peer(transport)
    identity = runtime.identity(packet)
    context = None
    component = None
    management_stop = None
    start_task = None
    stopped = asyncio.Event()

    async def stop(params: Any, _request: Any) -> Any:
        if type(identity).from_mapping(params) != identity:
            raise ProtocolValidationError("identity mismatch")
        if start_task is not None:
            start_task.cancel()
        if component is not None:
            await component.stop()
        if management_stop is not None:
            await management_stop()
        return RpcResponsePublication(
            result={"stopped": True},
            on_prepare=lambda: {"stopped": True},
            on_published=stopped.set,
            on_write_failed=stopped.set,
            on_write_deferred=stopped.set,
            on_aborted=lambda _reason: stopped.set(),
        )

    async def connect() -> None:
        try:
            await component.start(packet["config"])
        except Exception:
            await runtime.state(context, runtime.failed_state)

    mode = packet.get("mode", "run")
    if not isinstance(mode, str) or mode not in {
        "run",
        "manage",
        "audit",
        "probe",
    }:
        raise boot.BootstrapError("EXECUTION_MODE_INVALID", "invalid mode")
    if mode in {"run", "manage"}:
        peer.register_method(runtime.control_prefix + "stop", stop)
    await peer.start()
    try:
        component_class = await _prepare_component(
            boot,
            packet,
            runtime,
            identity,
            peer,
        )
        if mode in {"audit", "probe"}:
            await peer.notify(
                runtime.control_prefix + "inspected",
                identity.to_mapping(),
            )
            await peer.wait_closed()
            return
        if mode == "manage":
            bind = getattr(runtime, "bind_management", None)
            if not callable(bind):
                raise boot.BootstrapError(
                    "ENTRYPOINT_INVALID",
                    "mode unsupported",
                )
            management_stop = bind(packet, component_class, peer, identity)
        else:
            context = runtime.context(peer, identity)
            component = component_class()
            if any(
                not callable(getattr(component, name, None))
                for name in ("bind", "start", "stop")
            ):
                raise boot.BootstrapError(
                    "ENTRYPOINT_INVALID",
                    "invalid component",
                )
            component.bind(context)
            await runtime.state(context, runtime.initial_state)
        await peer.notify(
            runtime.control_prefix + "ready",
            identity.to_mapping(),
        )
        if mode == "run":
            start_task = asyncio.create_task(connect())
        closed_task = asyncio.create_task(peer.wait_closed())
        stop_task = asyncio.create_task(stopped.wait())
        await asyncio.wait(
            (closed_task, stop_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        await asyncio.sleep(0)
        for task in (closed_task, stop_task):
            task.cancel()
        await asyncio.gather(closed_task, stop_task, return_exceptions=True)
    except Exception as exc:
        await _report_error(peer, identity, runtime, exc)
    finally:
        if start_task is not None:
            start_task.cancel()
        if management_stop is not None:
            await management_stop()
        await peer.aclose()
        if payloads is not None:
            await payloads.cleanup(deadline=asyncio.get_running_loop().time())


async def _prepare_component(boot, packet, runtime, identity, peer):
    """Publish child evidence and optionally import a nonconnecting Driver."""
    mode = packet.get("mode", "run")
    from .dependencies import (
        observe_dependencies,
        validate_driver,
        check_import_origins,
        require_dependencies,
    )

    snapshot = observe_dependencies(packet)
    accepted = await peer.call(
        "execution.dependencies",
        {
            "identity": identity.to_mapping(),
            "snapshot": snapshot.to_mapping(),
        },
        timeout=packet["startup_timeout"],
    )
    if accepted != {"accepted": True}:
        raise boot.BootstrapError("HELLO_REJECTED", "evidence rejected")
    if mode == "audit":
        if (
            boot._hash_code_root(Path(packet["code_root"]))
            != packet["source_revision"]
        ):
            raise boot.BootstrapError(
                "SOURCE_REVISION_MISMATCH",
                "source mismatch",
            )
        return None
    relevant = require_dependencies(snapshot, packet)
    packet["dependency_versions"] = {
        name: snapshot.distributions[name]["version"] for name in relevant
    }
    entrypoint, source, hello = runtime.verify(boot, packet, identity)
    accepted = await peer.call(
        runtime.hello_method,
        hello,
        timeout=packet["startup_timeout"],
    )
    if accepted != {"accepted": True}:
        raise boot.BootstrapError("HELLO_REJECTED", "hello rejected")
    # Candidate paths enter only after trusted metadata/protocol imports.
    root = Path(packet["code_root"])
    sys.path.insert(0, str(root))
    sys.modules["qwenpaw"].__path__.insert(0, str(root / "qwenpaw"))
    component_class = boot._load_driver_class(entrypoint, source)
    check_import_origins(
        snapshot,
        Path(packet["code_root"]).resolve(),
        relevant,
    )
    if mode == "probe":
        validate_driver(component_class)
    return component_class


async def _report_error(
    peer: Any,
    identity: Any,
    runtime: Any,
    exc: Exception,
) -> None:
    from .process import PluginProcess

    reason = getattr(exc, "reason_code", "WORKER_START_FAILED")
    if reason not in PluginProcess.startup_errors:
        reason = "WORKER_START_FAILED"
    try:
        await peer.notify(
            runtime.control_prefix + "error",
            {**identity.to_mapping(), "reason_code": reason},
        )
    except Exception:
        pass


def _guard_inspection(boot):
    """Python audit guard installed before any candidate path is admitted."""

    def guard(event, _args):
        if event in {
            "socket.connect",
            "socket.sendto",
            "socket.sendmsg",
            "socket.bind",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "os.fork",
            "os.forkpty",
            "os.exec",
        }:
            raise boot.BootstrapError(
                "PROBE_NETWORK_OR_PROCESS_DENIED",
                "inspection operation denied",
            )

    sys.addaudithook(guard)


def main(
    runtime_factory: Any = None,
    *,
    protected_namespaces: tuple[str, ...] = (),
) -> int:
    output = None
    protocol_input = None
    input_transferred = False
    try:
        _sibling("process_tree").watch_parent(int(sys.argv[1]))
        boot = _sibling("bootstrap")
        boot._require_isolated_python()
        output = boot._capture_protocol_output()
        boot._redirect_ordinary_output()
        protocol_input = (
            boot._capture_protocol_input()
            if os.name == "nt"
            else sys.stdin.buffer
        )
        raw = protocol_input.readline(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or not raw.endswith(b"\n"):
            return 70
        packet = json.loads(raw)
        mode = packet.get("mode", "run")
        if not isinstance(mode, str) or mode not in {
            "run",
            "manage",
            "audit",
            "probe",
        }:
            return 70

        async def enter() -> None:
            nonlocal input_transferred
            # Windows builds the trusted loop's self-pipe with socketpair.
            # Install the guard after that, but before candidate paths enter.
            if mode in {"audit", "probe"}:
                # Windows Python 3.11 may run `ver` to initialize uname.
                platform.uname()
                _guard_inspection(boot)
            _configure(boot, packet, protected_namespaces)
            from qwenpaw.plugins.execution.runtime import Runtime

            run_component = importlib.import_module(
                "qwenpaw.plugins.execution.worker",
            ).run

            runtime = (
                Runtime() if runtime_factory is None else runtime_factory()
            )
            input_transferred = True
            await run_component(
                boot,
                packet,
                output,
                runtime,
                input_handle=protocol_input,
            )

        asyncio.run(enter())
        return 0
    except BaseException as exc:
        reason = getattr(exc, "reason_code", None)
        if reason is None:
            reason = (
                str(exc).split(":", 1)[0]
                if str(exc).startswith("DEPENDENCY_")
                else type(exc).__name__
            )
        sys.stderr.write(json.dumps({"error": reason}) + "\n")
        sys.stderr.flush()
        return 70
    finally:
        # A Windows reader may hold the buffer lock in a blocking read.
        # Once transferred, it closes its stream or process exit reclaims it.
        if os.name == "nt" and protocol_input is not None:
            if not input_transferred:
                protocol_input.close()
        if output is not None:
            output.close()


if __name__ == "__main__":
    os._exit(main())
