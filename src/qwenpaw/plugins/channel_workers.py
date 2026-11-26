# -*- coding: utf-8 -*-
"""Public, metadata-only declarations for process-backed channels (SDK 1.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Mapping, cast

from .events import JSONData, JSONValue
from .channels import ChannelMessage, ChannelRunEvent
from .messages import ContentBlock
from .resources import ResourceScope
from .storage import PluginStorage, MediaStore
from .logging import PluginLogger
from .channel_ingress import ChannelIngress, ChannelIngressRoute
from .channel_management import (
    ChannelManagementRequest,
    ChannelManagementResult,
    ChannelManagementFailure,
)


@dataclass(frozen=True)
class ChannelExclusiveResource:
    """One named resource identified by a composite of configuration values.

    The namespace is shared across channels in this host process. Drivers
    using the same external resource must agree on its namespace and field
    order. Values come from validated, normalized configuration. The host
    retains ownership until the worker and its resources actually stop.
    This is not an OS lock or coordination across separate host processes.
    """

    namespace: str
    fields: tuple[str, ...]
    operations: tuple[
        Literal["run", "qrcode.fetch", "qrcode.poll", "connection.verify"],
        ...,
    ] = ("run",)


@dataclass(frozen=True)
class ChannelDefinition:
    """The existing channel.json schema, without importing a platform driver.

    entrypoint is ``package.module:ClassName``. The JSON representation retains
    the host's nested runner entrypoint. Capabilities must be sorted, unique
    protocol names. Pass requires to select named plugin dependency groups.
    SDK version and capabilities are declared separately in plugin.json.
    """

    channel_key: str
    label: Mapping[str, str]
    entrypoint: str
    config_schema: Mapping[str, JSONValue]
    config_fields: tuple[str, ...]
    capabilities: tuple[str, ...]
    authorization_fields: tuple[str, ...] = ()
    exclusive_resources: tuple[ChannelExclusiveResource, ...] = ()
    ingress_routes: tuple[ChannelIngressRoute, ...] = ()
    requires: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        from ._events import freeze

        # Validate before freezing; callers cannot change a checked schema.
        data = self.to_dict()
        object.__setattr__(self, "label", freeze(data["label"]))
        object.__setattr__(
            self,
            "config_schema",
            freeze(data["config_schema"]),
        )
        object.__setattr__(self, "config_fields", tuple(self.config_fields))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "ingress_routes", tuple(self.ingress_routes))
        if self.requires is not None:
            object.__setattr__(self, "requires", tuple(self.requires))
        object.__setattr__(
            self,
            "authorization_fields",
            tuple(self.authorization_fields),
        )
        object.__setattr__(
            self,
            "exclusive_resources",
            tuple(
                ChannelExclusiveResource(
                    resource.namespace,
                    tuple(resource.fields),
                    tuple(resource.operations),
                )
                for resource in self.exclusive_resources
            ),
        )

    def to_dict(self) -> dict[str, JSONData]:
        """Return an independent, validated descriptor JSON object."""
        from ..channel_protocol.shared import (
            SharedChannelDescriptor,
            validate_channel_contract,
        )
        from ._models import json_mapping
        from .channel_config import validate_channel_config_schema

        module, separator, qualname = self.entrypoint.partition(":")
        if not separator:
            raise ValueError("Channel entrypoint must be module:ClassName")
        schema = json_mapping(self.config_schema)
        schema["x-qwenpaw-authorization-fields"] = list(
            self.authorization_fields,
        )
        schema["x-qwenpaw-exclusive-resources"] = [
            {
                "namespace": resource.namespace,
                "fields": list(resource.fields),
                "operations": list(resource.operations),
            }
            for resource in self.exclusive_resources
        ]
        schema["x-qwenpaw-ingress-routes"] = [
            {"method": route.method, "path": route.path}
            for route in self.ingress_routes
        ]
        if self.ingress_routes and "ingress_endpoint" not in self.capabilities:
            raise ValueError(
                "Ingress routes require ingress_endpoint capability",
            )
        descriptor = SharedChannelDescriptor.from_mapping(
            {
                **(
                    {
                        "schema_version": 2,
                        "requirements_file": "requirements.txt",
                    }
                    if self.requires is None
                    else {"schema_version": 3, "requires": list(self.requires)}
                ),
                "channel_key": self.channel_key,
                "label": dict(self.label),
                "process_mode": "runner_process",
                "dependency_mode": "shared",
                "entrypoint": {
                    "scope": "runner",
                    "module": module,
                    "qualname": qualname,
                },
                "config_schema": schema,
                "config_fields": list(self.config_fields),
                "capabilities": list(self.capabilities),
            },
        )
        validate_channel_contract(
            descriptor.channel_key,
            descriptor.capabilities,
        )
        validate_channel_config_schema(descriptor.config_schema)
        return cast(dict[str, JSONData], descriptor.to_mapping())

    @classmethod
    def load(cls, path: str | Path) -> ChannelDefinition:
        """Read a descriptor only; importing the declared entrypoint is forbidden."""
        from ..channel_protocol.shared import SharedChannelDescriptor

        descriptor = SharedChannelDescriptor.load(path)
        return cls(
            descriptor.channel_key,
            descriptor.label,
            descriptor.entrypoint.module
            + ":"
            + descriptor.entrypoint.qualname,
            descriptor.config_schema,
            descriptor.config_fields,
            descriptor.capabilities,
            tuple(
                descriptor.config_schema.get(
                    "x-qwenpaw-authorization-fields",
                    (),
                ),
            ),
            tuple(
                ChannelExclusiveResource(
                    resource["namespace"],
                    tuple(resource["fields"]),
                    tuple(resource.get("operations", ("run",))),
                )
                for resource in descriptor.config_schema.get(
                    "x-qwenpaw-exclusive-resources",
                    (),
                )
            ),
            tuple(
                ChannelIngressRoute(route["method"], route["path"])
                for route in descriptor.config_schema.get(
                    "x-qwenpaw-ingress-routes",
                    (),
                )
            ),
            descriptor.requires
            if descriptor.requirements_file is None
            else None,
        )


@dataclass(frozen=True)
class ReplyTarget:
    """Platform target and plugin-owned route data, persisted by the host."""

    key: str
    user_id: str = ""
    session_id: str = ""
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelReceiveResult:
    """Admission to the host queue, not completion of the model response."""

    status: Literal[
        "accepted",
        "duplicate",
        "backpressure",
        "rejected",
        "unknown",
    ]
    response_handle: str
    reason_code: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class ChannelApproval:
    request_id: str
    tool_name: str
    severity: Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class ChannelApprovalAction:
    """A verified platform callback; message supplies its actor and route.

    The message content is ignored. Host approval permissions still apply.
    """

    request_id: str
    decision: Literal["approve", "deny"]
    message: ChannelMessage


@dataclass(frozen=True)
class ChannelApprovalResolution:
    request_id: str
    outcome: Literal[
        "approved",
        "denied",
        "unavailable",
        "forbidden",
        "failed",
    ]
    actor_user_id: str
    tool_name: str | None = None


@dataclass(frozen=True)
class ChannelApprovals:
    _resolve: Callable[
        [ChannelApprovalAction],
        Awaitable[ChannelReceiveResult],
    ] = field(repr=False)

    async def resolve(
        self,
        action: ChannelApprovalAction,
    ) -> ChannelReceiveResult:
        """Submit a control action; acceptance is not approval or completion.

        The host executes its existing approval command with the platform
        actor. The authoritative outcome arrives in ChannelResponse.
        """
        return await self._resolve(action)


@dataclass(frozen=True)
class ChannelContent(ContentBlock):
    """Displayable content after host filtering, never hidden model context.

    Tool arguments and results are display previews and may be truncated.
    Refusals use type="text", role="refusal"; reasoning uses type="thinking".
    A tool result retains the order of its nested text and media blocks.
    """

    output: str | tuple[ChannelContent, ...] = ()
    metadata: dict[str, JSONData] = field(default_factory=dict)
    attributes: dict[str, JSONData] = field(default_factory=dict)
    role: Literal["message", "reasoning", "refusal", "rendered"] = "message"


@dataclass(frozen=True)
class ChannelResponse:
    delivery_id: str
    target: ReplyTarget
    operation: Literal[
        "message.create",
        "message.update",
        "stream.start",
        "stream.delta",
        "stream.end",
        "prepare",
        "reaction",
    ]
    content: tuple[ChannelContent, ...] = ()
    target_delivery_id: str | None = None
    stream_type: Literal["reasoning", "message"] | None = None
    sequence: int | None = None
    text: str = ""
    previous: ChannelSendResult | None = None
    approval: ChannelApproval | None = None
    approval_resolution: ChannelApprovalResolution | None = None


@dataclass(frozen=True)
class ChannelSendResult:
    """Confirmed platform resource; raise ChannelDeliveryError for other results."""

    message_id: str = ""
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelDeliveryStep:
    id: str
    name: str
    completed: bool
    result: ChannelSendResult | None = None


@dataclass(frozen=True)
class ChannelDelivery:
    """Durable effects within the current callback, never a background journal.

    Await prepare_step before a platform effect and record_progress after its
    confirmation. A prepared step with no confirmation cannot be repeated.
    Perform these writes in the callback task, not an unawaited child task.
    """

    _prepare: Callable[[str], Awaitable[ChannelDeliveryStep]] = field(
        repr=False,
    )
    _progress: Callable[
        [ChannelDeliveryStep, ChannelSendResult],
        Awaitable[None],
    ] = field(repr=False)
    _resource: Callable[[str, ChannelSendResult], Awaitable[None]] = field(
        repr=False,
    )
    _resources: Callable[[], Mapping[str, ChannelSendResult]] = field(
        repr=False,
    )

    async def prepare_step(self, name: str) -> ChannelDeliveryStep:
        return await self._prepare(name)

    async def record_progress(
        self,
        step: ChannelDeliveryStep,
        result: ChannelSendResult,
    ) -> None:
        await self._progress(step, result)

    async def record_resource(
        self,
        name: str,
        result: ChannelSendResult,
    ) -> None:
        """Retain a platform resource for finish_response, before further effects."""
        await self._resource(name, result)

    def resources(self) -> Mapping[str, ChannelSendResult]:
        """Read this response's named platform resources, including during finish."""
        return self._resources()


class ChannelDeliveryError(RuntimeError):
    """Whether a platform effect might already have happened controls retries."""

    def __init__(
        self,
        reason_code: str,
        *,
        side_effect_possible: bool,
        retryable: bool = False,
    ) -> None:
        if (
            not reason_code
            or type(side_effect_possible) is not bool
            or type(retryable) is not bool
        ):
            raise ValueError(
                "A delivery error requires a reason and boolean flags",
            )
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable
        super().__init__(reason_code)


@dataclass(frozen=True)
class ResponsePolicy:
    """Host delivery controls; platform formatting stays in the driver.

    ``content_source="semantic"`` requires ``send.structured_parts.v1`` and
    preserves content roles and tool structure after host display filtering.
    Semantic events are not text-merged; merging applies to formatted/direct
    sends. The default retains the host's existing rendered presentation.

    ``text_merge_delay_ms`` requires ``channel.text_merge.v1``. None disables
    merging; zero flushes at response completion; a positive value also
    flushes after that many idle milliseconds. Cancellation discards unsent
    buffered text, but cannot retract a delivery already in progress.

    ``continue_on_delivery_error`` keeps consuming model events after a failed
    send. It does not retry a send or change the failed response outcome;
    an uncertain delivery still fences further effects on that response.

    ``configured_prefix=False`` omits the channel's configured bot prefix
    from direct, content-part and streaming sends. An explicit per-message
    metadata prefix remains effective; platform formatting stays in the driver.
    """

    streaming: bool = False
    prepare: bool = False
    completion_reaction: bool = False
    text_merge_delay_ms: int | None = None
    continue_on_delivery_error: bool = False
    content_source: Literal["rendered", "semantic"] = "rendered"
    configured_prefix: bool = True

    def __post_init__(self) -> None:
        if self.content_source not in {"rendered", "semantic"}:
            raise ValueError("Invalid channel content source")
        if any(
            type(getattr(self, name)) is not bool
            for name in (
                "streaming",
                "prepare",
                "completion_reaction",
                "continue_on_delivery_error",
                "configured_prefix",
            )
        ):
            raise ValueError("Response policy fields must be booleans")
        if self.text_merge_delay_ms is not None and (
            type(self.text_merge_delay_ms) is not int
            or not 0 <= self.text_merge_delay_ms <= 2**63 - 1
        ):
            raise ValueError("Text merge delay must be a nonnegative integer")


@dataclass(frozen=True)
class ChannelAuth:
    """Ask the host to show a login QR link for this worker generation."""

    _required: Callable[[str], Awaitable[None]] = field(repr=False)
    _guard: Callable[[], None] = field(repr=False)

    async def required(self, scan_url: str) -> None:
        self._guard()
        await self._required(scan_url)


@dataclass(frozen=True)
class ChannelWorkerContext:
    """One host-assigned worker generation, with no IPC peer or manager access."""

    plugin_id: str
    workspace_id: str
    channel_key: str
    instance_id: str
    generation: int
    config: Mapping[str, JSONValue] = field(repr=False)
    resources: ResourceScope
    delivery: ChannelDelivery
    storage: PluginStorage
    media: MediaStore
    logger: PluginLogger
    auth: ChannelAuth
    approvals: ChannelApprovals
    ingress: ChannelIngress
    _receive: Callable[
        [ChannelMessage],
        Awaitable[ChannelReceiveResult],
    ] = field(
        repr=False,
        compare=False,
    )
    _status: Callable[[str], Awaitable[None]] = field(
        repr=False,
        compare=False,
    )
    _guard: Callable[[], None] = field(repr=False, compare=False)

    @property
    def deadline(self) -> float | None:
        """Monotonic deadline of the current outbound callback, if any."""
        from ..channel_protocol.outbound_budget import _deadline

        return cast(float | None, _deadline.get())

    @property
    def cancelled(self) -> bool:
        import asyncio

        task = asyncio.current_task()
        return self.resources.closed or bool(task and task.cancelling())

    def check_cancelled(self) -> None:
        import asyncio

        if self.cancelled:
            raise asyncio.CancelledError
        self._guard()
        if self.remaining_timeout() == 0:
            raise TimeoutError("Channel callback deadline exceeded")

    def remaining_timeout(self) -> float | None:
        import asyncio

        deadline = self.deadline
        return (
            None
            if deadline is None
            else max(0.0, deadline - asyncio.get_running_loop().time())
        )

    async def receive(self, message: ChannelMessage) -> ChannelReceiveResult:
        """Validate and admit a message using this worker's trusted identity."""
        self.check_cancelled()
        return await self._receive(message)

    async def report_status(
        self,
        status: Literal["connecting", "connected", "disconnected", "failed"],
    ) -> None:
        self._guard()
        await self._status(status)


class ChannelDriver:
    """Process channel author contract; the host supplies lifecycle and receipts.

    start should establish the transport and register long-running work with
    ch.resources. stop must await platform shutdown. An uncompleted cleanup
    never becomes a successful stop acknowledgment.
    """

    response_policy = ResponsePolicy()

    def response_policy_for(self, target: ReplyTarget) -> ResponsePolicy:
        """Choose a policy synchronously after resolving a new reply target.

        The host validates and persists this policy with the route. Retries
        and worker restarts reuse it without calling this method again.
        Do not perform I/O or start work here. Existing routes without a
        saved policy retain the driver's static response_policy behavior.
        """
        return self.response_policy

    @staticmethod
    async def manage(
        request: ChannelManagementRequest,
    ) -> ChannelManagementResult:
        """Run in a temporary worker, without constructing or starting the driver."""
        return ChannelManagementFailure(
            "MANAGEMENT_UNSUPPORTED",
            unsupported=True,
        )

    async def start(self, ch: ChannelWorkerContext) -> None:
        raise NotImplementedError

    async def stop(self, ch: ChannelWorkerContext) -> None:
        pass

    async def resolve_target(
        self,
        ch: ChannelWorkerContext,
        target: ReplyTarget,
    ) -> ReplyTarget:
        return target

    async def send(
        self,
        ch: ChannelWorkerContext,
        response: ChannelResponse,
    ) -> ChannelSendResult:
        raise NotImplementedError

    async def on_stream(
        self,
        ch: ChannelWorkerContext,
        response: ChannelResponse,
    ) -> ChannelSendResult:
        raise ChannelDeliveryError(
            "STREAM_UNSUPPORTED",
            side_effect_possible=False,
        )

    async def on_run(
        self,
        ch: ChannelWorkerContext,
        event: ChannelRunEvent,
    ) -> None:
        """Observe an admitted processing cycle; requires channel.run_events.v1.

        Start precedes processing and end precedes finish_response. Callbacks
        are ordered and owned by the worker, with a five-second callback
        budget. This is a live notification, not a durable delivery receipt;
        no delivery transaction is bound here. Platform effects belong in
        send/on_stream/prepare_response/reaction. The run_id identifies this
        channel cycle and excludes proactive sends.
        """

    async def prepare_response(
        self,
        ch: ChannelWorkerContext,
        response: ChannelResponse,
    ) -> ChannelSendResult:
        raise ChannelDeliveryError(
            "PREPARE_UNSUPPORTED",
            side_effect_possible=False,
        )

    async def reaction(
        self,
        ch: ChannelWorkerContext,
        response: ChannelResponse,
    ) -> ChannelSendResult:
        raise ChannelDeliveryError(
            "REACTION_UNSUPPORTED",
            side_effect_possible=False,
        )

    async def finish_response(
        self,
        ch: ChannelWorkerContext,
        target: ReplyTarget,
        outcome: Literal["completed", "failed", "cancelled"],
    ) -> None:
        """Release response-local resources; repeated calls must be idempotent.

        This also runs when a platform delivery or stream end is uncertain.
        Do not retry that uncertain effect here. The host retains its receipt
        separately. Raising keeps local cleanup pending for a later retry;
        returning must mean the local resources have actually stopped.
        """
