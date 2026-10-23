# -*- coding: utf-8 -*-
# pylint: disable=protected-access,too-many-arguments
"""Trusted test adapter; production Loader, custody, Gate and IPC stay real."""

import base64
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
import hashlib
import json
import sys
from types import SimpleNamespace
from uuid import uuid4
import zipfile

from qwenpaw.plugins.architecture import PluginType
from qwenpaw.plugins.dependency_gate import (
    WheelAddition,
    admit_shared_dependencies,
    prepare_shared_dependencies,
)
from qwenpaw.plugins.dependency_usage import current_admission_token
from qwenpaw.plugins.execution import PluginLaunchSpec, PluginProcess
from qwenpaw.plugins.execution_backend import (
    DefinitionResult,
    PluginDescription,
)
from qwenpaw.plugins.lifecycle import QuiescenceError
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt
from qwenpaw.plugins.workspace_projector import WorkspaceProjector

KEY = "fixture-indexer"
SDK = "f4-fixture-sdk"
KIND = "indexer"
WORKER = """import asyncio
import os
from pathlib import Path
import sys
from qwenpaw.plugins.execution import runtime

class Worker:
    def __init__(self):
        self.started = asyncio.Event()
        self.config = {}

    def bind(self, context):
        self.context = context
        context.peer.register_method("fixture.probe", self.probe)
        context.peer.register_method("fixture.reverse", self.reverse)

    async def start(self, config):
        self.config = dict(config)
        with Path(config["ledger"]).open("a") as stream:
            stream.write(str(os.getpid()) + "\\n")
        self.started.set()
        if config.get("fail_start"):
            raise RuntimeError("FIXTURE_START_FAILED")
        await self.context.set_state("ready")

    async def stop(self):
        await self.context.set_state("stopped")

    async def probe(self, _params, _request):
        await self.started.wait()
        import f4_fixture_sdk
        return {
            "pid": os.getpid(),
            "identity": self.context.identity.to_mapping(),
            "isolated": sys.flags.isolated,
            "support": str(Path(runtime.__file__).resolve()),
            "source": str(Path(__file__).resolve()),
            "sdk": str(Path(f4_fixture_sdk.__file__).resolve()),
            "config": dict(self.config),
            "blocked": [name for name in sys.modules if name.startswith((
                "qwenpaw.app", "qwenpaw.channel_protocol",
                "qwenpaw.plugins.loader", "lark_oapi", "dingtalk_stream",
            ))],
        }

    async def reverse(self, params, _request):
        await self.context.peer.notify("fixture.notice", params)
        return await self.context.peer.call(
            "fixture.host", self.context.identity.to_mapping(),
        )
"""


def source(root, version="1.0.0", *, failure=None, requirement="==1.0"):
    """Local candidates cannot run the poisonous Python fallback."""
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": KEY,
                "name": "Fixture indexer",
                "version": version,
                "type": "general",
                "entry": {"descriptor": "indexer.json"},
            },
        ),
    )
    (root / "indexer.json").write_text(
        json.dumps(
            {
                "entrypoint": (
                    "worker:Missing" if failure == "probe" else "worker:Worker"
                ),
                "failure": failure,
            },
        ),
    )
    (root / "worker.py").write_text(WORKER)
    (root / "main.py").write_text(
        "raise AssertionError('descriptor executed Python fallback')\n",
    )
    (root / "requirements.txt").write_text(SDK + requirement + "\n")
    return root


def wheel(root, version="1.0"):
    """Exact offline wheel bytes, including a checked RECORD."""
    package = SDK.replace("-", "_")
    info = f"{package}-{version}.dist-info"
    files = {
        f"{package}.py": f"VERSION = {version!r}\n".encode(),
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {SDK}\nVersion: {version}\n"
        ).encode(),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n" "Tag: py3-none-any\n"
        ).encode(),
        f"{info}/top_level.txt": (package + "\n").encode(),
    }
    rows = []
    for name, data in files.items():
        checksum = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        rows.append(
            f"{name},sha256={checksum.decode().rstrip('=')},{len(data)}",
        )
    files[f"{info}/RECORD"] = (
        "\n".join([*rows, f"{info}/RECORD,,"]) + "\n"
    ).encode()
    path = root / f"{package}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return WheelAddition(path, hashlib.sha256(path.read_bytes()).hexdigest())


def digest(root):
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name, data = (
                path.relative_to(root).as_posix().encode(),
                path.read_bytes(),
            )
            result.update(len(name).to_bytes(8, "big"))
            result.update(name)
            result.update(len(data).to_bytes(8, "big"))
            result.update(data)
    return result.hexdigest()


@dataclass
class Resource:
    process: PluginProcess
    token: object
    blocked: bool = False

    async def stop(self):
        if self.blocked:
            return RuntimeStopReceipt(
                False,
                "FIXTURE_DRAIN_PENDING",
                exited=False,
            )
        result = await self.process.stop(timeout=1)
        return RuntimeStopReceipt(
            result.exited and not result.residual,
            exited=result.exited,
            returncode=result.returncode,
            forced=result.forced,
            residual=result.residual,
        )


class NonChannelBackend:
    """Only fixture-specific description/business callbacks live here."""

    discover_disabled = False
    probe_before_activation = True

    def __init__(self, registry, site, support, ledger):
        self.registry, self.site = registry, site
        self.support, self.ledger = support, ledger
        self.notices = []
        self.events = []
        # Optional offline acquisition uses the same real add-only Gate.
        self.available_wheels = ()

    def dependency_targets(self, _description):
        return (self.site,)

    def describe(self, root, manifest):
        payload = json.loads((root / manifest.entry.descriptor).read_text())
        return PluginDescription(
            manifest,
            root,
            root / "requirements.txt",
            payload,
            digest(root),
        )

    def registration_scope(self, _description):
        return nullcontext()

    def own(self, description, scope, token, *, kind=KIND):
        owners = self.registry.runtime_owners
        lease = owners.reserve(
            description.manifest.id,
            RuntimeKey(kind, KEY, scope),
            description.source_path,
            instance_id=f"{kind}:{scope}",
        )
        resource = Resource(PluginProcess(), token)
        owners.attach(lease, resource.stop, resource=resource)
        self.registry.dependency_usage.bind(lease, token)
        resource.process.dependency_observer = lambda snapshot: (
            self.registry.dependency_usage.observe(lease, snapshot)
        )
        return lease, resource

    def spec(self, description, lease, config=None):
        return PluginLaunchSpec(
            sys.executable,
            self.support,
            description.source_path,
            description.source_identity,
            description.manifest.id,
            lease.instance_id,
            lease.generation,
            description.payload["entrypoint"],
            config or {},
            dependency_paths=(self.site,),
            requirements_path=description.requirements_path,
            startup_timeout=3,
            shutdown_timeout=1,
        )

    @asynccontextmanager
    async def inspection(self, description):
        usage = self.registry.dependency_usage
        token = usage.declare(description.dependency_declaration())
        lease, resource = self.own(
            description,
            uuid4().hex,
            token,
            kind="preparation",
        )
        try:
            yield resource.process, self.spec(description, lease), token
        finally:
            try:
                receipt = await self.registry.runtime_owners.stop(lease)
                if not receipt.stopped:
                    raise QuiescenceError(receipt.detail, receipt=receipt)
            finally:
                usage.withdraw(token)

    async def prepare(
        self,
        description,
        *,
        allow_install,
        probe,
        wheels=(),
        owns_dependency_env=True,
    ):
        self.events.append(("prepare", allow_install, probe))
        async with self.inspection(description) as (process, spec, token):
            admitted = current_admission_token(
                self.registry.dependency_usage,
                description.manifest.id,
                description.source_path,
            )
            snapshot = await prepare_shared_dependencies(
                process,
                spec,
                plugin_id=description.manifest.id,
                requirements_file=description.requirements_path,
                usage_registry=self.registry.dependency_usage,
                admission_token=admitted or token,
                install_target=self.site,
                wheels=(wheels or self.available_wheels)
                if allow_install and owns_dependency_env
                else (),
            )
            if probe:
                await process.probe(spec)
            return snapshot

    async def audit_dependencies(self, description):
        async with self.inspection(description) as (process, spec, _token):
            return (await process.audit(spec)).snapshot

    async def load_definition(
        self,
        description,
        config,
        *,
        saved_definition=None,
    ):
        del config, saved_definition
        self.events.append(("definition", description.source_path))
        return DefinitionResult(Definition(self, description))

    async def before_activate(self, _description):
        return None

    def validate_update(self, _old, _candidate, *, in_place):
        if in_place:
            raise RuntimeError("FIXTURE_IN_PLACE_REFUSED")

    def capture_restore_state(self, _record):
        return None

    def restore_state(self, _state):
        return None


class Definition:
    def __init__(self, backend, description):
        self.backend, self.description = backend, description
        self.token = None

    def register(self, api):
        backend, description = self.backend, self.description
        owners, usage = (
            backend.registry.runtime_owners,
            backend.registry.dependency_usage,
        )
        self.token = api.dependency_token

        async def apply(workspace):
            lease, resource = backend.own(
                description,
                workspace.agent_id,
                self.token,
            )
            process = resource.process
            process.register_method(
                "fixture.host",
                lambda params, _request: params,
            )
            process.register_notification(
                "fixture.notice",
                lambda params, _request: backend.notices.append(params),
            )
            config = {
                **api.config,
                "version": description.manifest.version,
                "ledger": str(backend.ledger),
                "fail_start": description.payload["failure"] == "start",
            }
            spec = backend.spec(description, lease, config)

            async def audit():
                return (await process.audit(spec)).snapshot

            try:
                await admit_shared_dependencies(
                    audit,
                    plugin_id=api.plugin_id,
                    requirements_file=None,
                    usage_registry=usage,
                    admission_token=self.token,
                    targets=backend.dependency_targets(description),
                )
                await process.start(spec)
                probe = await process.call("fixture.probe")
                if probe["config"]["fail_start"]:
                    raise RuntimeError("FIXTURE_START_FAILED")
                return lease
            except BaseException as exc:
                receipt = await owners.stop(lease)
                if not receipt.stopped:
                    exc.binding = lease
                raise

        async def revoke(_workspace, token):
            return await owners.stop(token)

        api._schedule_workspace_intent(
            KIND,
            KEY,
            apply,
            revoke,
            can_apply=lambda workspace: workspace.ready,
            binding_is_current=lambda _workspace, token: owners.resource(token)
            is not None,
        )


def host(root, support, registry):
    """Only external workspace/model effects are replaced."""
    site = root / "package-site"
    site.mkdir()
    workspaces = [
        SimpleNamespace(agent_id=scope, ready=True)
        for scope in ("alpha", "beta")
    ]
    registry.projector = WorkspaceProjector(lambda: workspaces)
    registry.set_workspace_manager(
        SimpleNamespace(agents={ws.agent_id: ws for ws in workspaces}),
    )
    loader = PluginLoader([root / "plugins"])
    backend = NonChannelBackend(registry, site, support, root / "starts")
    loader.backend_resolver.register_descriptor(PluginType.GENERAL, backend)
    return SimpleNamespace(
        loader=loader,
        backend=backend,
        registry=registry,
        workspaces=workspaces,
        root=root,
    )
