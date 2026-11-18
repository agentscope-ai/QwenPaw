# -*- coding: utf-8 -*-
"""Bound ephemeral provider input without changing durable conversations."""

from __future__ import annotations

from copy import deepcopy
import base64
import binascii
import hashlib
import json
import os
import re
from typing import Any, Callable, Final, Mapping, Sequence

from services.project_files.model_view import (
    json_bytes,
    json_text,
    project_snapshot_view,
)

try:
    # The host already prices media the way vision models read it: Qwen-VL 28px
    # patches, audio by duration. Reusing that estimate keeps one answer for
    # "what will this cost" instead of a plugin-local guess that drifts.
    from qwenpaw.agents.context.visual_compression.pipeline.budget import (
        count_text_tokens as _host_count_text_tokens,
    )
    from qwenpaw.agents.utils.media_token_estimate import (
        estimate_data_url_tokens as _host_estimate_data_url_tokens,
    )
    from qwenpaw.providers.context_windows import (
        resolve_context_window as _host_resolve_context_window,
    )

    _HOST_CONTEXT_ESTIMATOR_AVAILABLE = True
    _HOST_CONTEXT_WINDOW_AVAILABLE = True
except ImportError:  # pragma: no cover - standalone plugin installs
    _host_count_text_tokens = None
    _host_estimate_data_url_tokens = None
    _host_resolve_context_window = None
    _HOST_CONTEXT_ESTIMATOR_AVAILABLE = False
    _HOST_CONTEXT_WINDOW_AVAILABLE = False

try:
    # The platform scroll already owns the eviction-index odometer: a tiered
    # map of evicted turns keyed by their durable seq. Creator's own flat map
    # predated it; reusing the class lets the archived map share the platform's
    # folding algorithm, at the cost of Creator's own wording - the host
    # preamble names stores and recall tools a Creator session lacks, so it is
    # sliced off and Creator re-emits its own. The module itself imports
    # nothing but dataclasses, so it is safe to pull in even though Creator
    # drives its own (byte-gated) compaction loop.
    from qwenpaw.agents.context.scroll.eviction_index import (
        EvictionIndex as _HostEvictionIndex,
        Leaf as _HostEvictionLeaf,
    )

    _HOST_EVICTION_INDEX_AVAILABLE = True
except ImportError:  # pragma: no cover - standalone plugin installs
    _HostEvictionIndex = None
    _HostEvictionLeaf = None
    _HOST_EVICTION_INDEX_AVAILABLE = False

# A transport safety floor — not the primary gate when a token window is
# resolved. The actual guard is the input token budget from
# ``context_window()``, whose byte equivalent can be far larger; this
# constant stops a single request from growing without bound.
MODEL_INPUT_BYTES = 384 * 1024
HISTORY_BYTES = 128 * 1024

# Providers bill inline media as vision tokens, not as request bytes. Counting
# a ``data:`` URL by its Base64 text length charges a 2MB image ~2.7MB against
# a 384KB budget, and because media-bearing user messages are contract content
# that compaction may not drop, the request is refused locally and never
# reaches the model — the understanding record just comes back empty. Charge a
# representative text-equivalent instead: decoded bytes / 128, clamped.
# Calibrated against a measured 2MB image costing ~2.5K vision tokens, which is
# roughly 10KB of text budget; the clamp keeps a huge clip from being treated
# as free.
_INLINE_MEDIA_BYTES_DIVISOR = 128
_INLINE_MEDIA_MIN_BYTES = 8 * 1024
_INLINE_MEDIA_MAX_BYTES = 512 * 1024

# The absolute ceiling above predates a fatal arithmetic: it was larger than
# MODEL_INPUT_BYTES itself, so one big screenshot could outgrow the entire
# input budget on its own. Nothing in compaction can reclaim it either, since
# the message carrying it is contract content, which means the request was
# refused locally and never reached the provider. The ceiling therefore has to
# derive from the budget actually in force: a single block must always stay
# small enough that dropping every tool exchange leaves it somewhere to live.
MEDIA_CLAMP_RATIO_ENV = "CREATOR_MEDIA_CLAMP_RATIO"
DEFAULT_MEDIA_CLAMP_RATIO = 0.5
# Tuning the share down is legitimate; tuning it to nothing is not. A ratio
# small enough to charge a screenshot for a few bytes would make every block
# free, which is the failure this guard exists to catch.
MIN_MEDIA_CLAMP_RATIO = 0.05
# Only the ceiling is derived from the budget. The floor stays absolute, so a
# huge clip is never treated as free just because the budget happens to be
# small: several floor-priced blocks must still be able to overflow it.


def _media_clamp_ratio() -> float:
    """Share of the input budget one inline media part may occupy."""
    raw = (os.environ.get(MEDIA_CLAMP_RATIO_ENV) or "").strip()
    if not raw:
        return DEFAULT_MEDIA_CLAMP_RATIO
    try:
        ratio = float(raw)
    except ValueError:
        return DEFAULT_MEDIA_CLAMP_RATIO
    # A nonsensical setting must not disable the guard it exists to provide.
    if not 0 < ratio <= 1:
        return DEFAULT_MEDIA_CLAMP_RATIO
    return min(1.0, max(MIN_MEDIA_CLAMP_RATIO, ratio))


MEDIA_OBSERVATION_DEGRADE_ENV = "CREATOR_MEDIA_OBSERVATION_DEGRADE_ENABLED"

# The input window a token budget can be measured against.  Resolution
# prefers an operator-declared value, then the host catalog (same
# precedence the platform scroll follows), then gives up — no window
# means the byte transport floor stays the sole limit.
MODEL_CONTEXT_TOKENS_ENV = "CREATOR_MODEL_CONTEXT_TOKENS"


def context_window(model_name: str | None = None) -> int | None:
    """The input-context window for this deployment, or ``None``.

    Resolution order (matches the platform scroll):

    1. ``CREATOR_MODEL_CONTEXT_TOKENS`` env — explicit override wins.
    2. Host catalog via ``resolve_context_window(model_name)`` — same
       values the platform uses for its own token budgeting.
    3. ``None`` — the server-side guard stays off and lets the byte
       transport floor (``MODEL_INPUT_BYTES``) remain the only limit.
    """
    raw = (os.environ.get(MODEL_CONTEXT_TOKENS_ENV) or "").strip()
    if raw:
        try:
            tokens = int(raw)
        except ValueError:
            tokens = 0
        if tokens > 0:
            return tokens
    if model_name and _HOST_CONTEXT_WINDOW_AVAILABLE:
        # Use the same catalog the platform scroll reads.  An explicit
        # configure=False would value a local-serving Ollama provider
        # whose actual runtime window is deployment-specific, but
        # Creator always routes through a managed model endpoint.
        return _host_resolve_context_window(
            model_name,
            use_catalog=True,
        )
    return None


def declared_context_tokens() -> int | None:
    """The context window declared for this deployment, or ``None``.

    Read per call, like the other knobs, so a restart-free change stays
    possible in tests and a value of 0 or junk means "not declared" rather
    than a budget that refuses every request.

    Deprecated: prefer ``context_window(model_name)``, which also reads
    the host catalog and matches the platform scroll's resolution order.
    """
    return context_window(model_name=None)


def media_observation_degrade_enabled() -> bool:
    """Whether demotion may run at all; off restores the hard local refusal.

    Demotion is visible and recallable rather than silent, but a deployment
    that would rather take the failure and read the diagnostics can switch it
    off without a code change.
    """
    raw = (os.environ.get(MEDIA_OBSERVATION_DEGRADE_ENV) or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


CONTINUATION_SUMMARY_ENV = "CREATOR_CONTINUATION_SUMMARY_ENABLED"


def continuation_summary_enabled() -> bool:
    """Whether an archived slice may be summarized by one extra model turn.

    The prose continuation summary is the platform scroll's fourth relief
    lever: a state cache that reads beside the seq recall map so the model
    sees a coherent snapshot of what the archived middle decided and still
    owes, not only a list of pointers. It costs a model turn, and the map
    already guarantees nothing is lost, so a deployment that would rather not
    spend the turn flips it off and keeps the recall-only behavior.
    """
    raw = (os.environ.get(CONTINUATION_SUMMARY_ENV) or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _media_charge_bounds(budget_bytes: int) -> tuple[int, int]:
    """Return the ``(floor, ceiling)`` one media part is charged within."""
    ceiling = min(
        _INLINE_MEDIA_MAX_BYTES,
        max(1, int(budget_bytes * _media_clamp_ratio())),
    )
    # A ceiling below the floor would silently un-floor the charge, so the
    # floor follows it down at most as far as the ceiling itself.
    floor = min(_INLINE_MEDIA_MIN_BYTES, ceiling)
    return floor, ceiling


def _data_url_charge(
    url: str,
    *,
    budget_bytes: int = MODEL_INPUT_BYTES,
) -> int:
    """Text-budget representative of one inline ``data:`` URL."""
    _, _, encoded = url.partition(";base64,")
    decoded_bytes = len(encoded) * 3 // 4
    charge = decoded_bytes // _INLINE_MEDIA_BYTES_DIVISOR
    floor, ceiling = _media_charge_bounds(budget_bytes)
    return max(floor, min(charge, ceiling))


def _data_url_relief_in_text(
    text: str,
    *,
    budget_bytes: int = MODEL_INPUT_BYTES,
) -> int:
    """Relief for every base64 data URL buried inside one string.

    Detected with the same ``_DATA_URL_PATTERN`` the demotion walk uses, so
    a payload priced as media here is exactly a payload the ladder may
    retire there - whether it sits under a ``url`` key or inside a JSON tool
    answer. The ``";base64,"`` gate is what keeps the whole-history walk
    cheap: ordinary conversation text drops out on a single substring test
    instead of a regex pass over every megabyte of a serialized script.
    """
    if ";base64," not in text:
        return 0
    relief = 0
    for match in _DATA_URL_PATTERN.finditer(text):
        url = match.group(0)
        # A base64 payload is ASCII by construction, so the character count
        # is the byte count. Only the hand-edited exception pays for an
        # encode, which would otherwise copy the payload a second time.
        raw = len(url) if url.isascii() else len(url.encode("utf-8"))
        relief += max(
            0,
            raw - _data_url_charge(url, budget_bytes=budget_bytes),
        )
    return relief


def _inline_media_relief(
    node: Any,
    *,
    budget_bytes: int = MODEL_INPUT_BYTES,
) -> int:
    """Bytes the naive JSON count over-charges for inline media parts.

    Subtracted from ``json_bytes`` so both measurements agree on what one
    image or clip actually costs the provider. Media is detected with the
    same pattern ``_demote_in_node`` strips on, so nothing that can leave
    the history is still billed at full text length - including the base64
    embedded in a plain string, which the old ``url``-key-only walk priced
    as text even though the ladder retired it.
    """
    if node is None:
        return 0
    if isinstance(node, str):
        return _data_url_relief_in_text(node, budget_bytes=budget_bytes)
    if isinstance(node, dict):
        return sum(
            _inline_media_relief(value, budget_bytes=budget_bytes)
            for value in node.values()
        )
    if isinstance(node, (list, tuple)):
        return sum(
            _inline_media_relief(item, budget_bytes=budget_bytes)
            for item in node
        )
    return 0


def _media_aware_bytes(
    value: Any,
    *,
    budget_bytes: int = MODEL_INPUT_BYTES,
) -> int:
    """Serialized size with inline media charged as vision tokens."""
    return json_bytes(value) - _inline_media_relief(
        value,
        budget_bytes=budget_bytes,
    )


# A block the guard demoted and the Agent then recalled is the runtime's own
# observation again: the pointer can answer for it a second time, so it stays
# as trimmable as any other runtime receipt. The Agent loop labels that
# injection with this source.
MEDIA_RECALL_SOURCE = "media_recall"

# Media the runtime observed on the model's behalf - a delegated target's own
# file, frames a video reader sampled, pages a document reader rendered. Any
# tool can produce it again, so it is a runtime receipt in the provider's user
# role rather than a requirement a person typed or uploaded, and the first
# rung of the ladder may trade it without touching an upload.
MEDIA_OBSERVATION_SOURCE = "media_observation"

# These are runtime receipts carried in the provider's user role, not human
# requirements. Keep durable messages intact, but let old receipts leave the
# bounded history just like old tool results. Unknown sources fail closed.
_AUTOMATED_HISTORY_SOURCES = frozenset(
    {
        "run_review_feedback",
        "render_review_feedback",
        "runtime_notification",
        "mainline_resume",
        "prompt_contract_resume",
        "yolo_auto_resume",
        "review_approval_resume",
        MEDIA_RECALL_SOURCE,
        MEDIA_OBSERVATION_SOURCE,
    },
)


class ModelContextBudgetError(ValueError):
    """Local refusal carrying the accounting that produced it.

    The bare message used to be all a caller got, which left every report of
    "the session just errors out" guessing at whether text, tools or one
    oversized image was to blame. ``diagnostics`` names the culprit instead,
    so a caller can demote media knowingly rather than by accident.
    """

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


# Matches the same shape the platform estimator reads, so a block counted here
# and a block counted there are the same block.
_DATA_URL_PATTERN = re.compile(
    r"data:([^;,\"']*)?;base64,([A-Za-z0-9+/=]+)",
)
# Providers carry inline media in these part types. Anything not listed keeps
# its payload untouched, since rewriting an unknown shape can corrupt it.
_INLINE_MEDIA_PART_TYPES = frozenset(
    {
        "image_url",
        "image",
        "audio",
        "audio_url",
        "input_audio",
        "video",
        "video_url",
    },
)
# Called with a data URL, returns the 64-hex handle the bytes were stored
# under, or ``None`` when no durable copy exists. Supplied by the runtime that
# owns a data root, so this module keeps doing arithmetic and never touches
# the filesystem.
MediaVault = Callable[[str], "str | None"]


def _data_url_of(node: Any) -> str | None:
    """First inline ``data:`` URL carried by a content part, if any."""
    if isinstance(node, str):
        return node if node.startswith("data:") else None
    if isinstance(node, Mapping):
        direct = node.get("url")
        if isinstance(direct, str) and direct.startswith("data:"):
            return direct
        for value in node.values():
            if isinstance(value, (Mapping, list, tuple)):
                found = _data_url_of(value)
                if found is not None:
                    return found
    elif isinstance(node, (list, tuple)):
        for item in node:
            found = _data_url_of(item)
            if found is not None:
                return found
    return None


def _split_data_url(url: str) -> tuple[str, str]:
    header, _, encoded = url.partition(";base64,")
    mime = header[5:] if header.startswith("data:") else header
    return mime.split(";")[0], encoded


def _decoded_size(encoded: str) -> int:
    # Exact rather than approximate: a pointer advertises how many bytes its
    # handle stands for, and padding is the only thing separating a Base64
    # length from the payload behind it.
    return len(encoded) * 3 // 4 - encoded.count("=")


def _media_digest(url: str) -> str:
    """Content handle for a demoted block.

    Taken over the decoded bytes, which is the key the media vault stores
    under, so the pointer a model reads and the recall answering it cannot
    drift apart. A payload that refuses to decode still gets an identity over
    its text form instead of losing one.
    """
    _, encoded = _split_data_url(url)
    try:
        payload = base64.b64decode("".join(encoded.split()), validate=True)
    except (binascii.Error, ValueError):
        payload = encoded.encode("ascii", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def _demotion_stub(
    url: str,
    vault: "MediaVault | None" = None,
    *,
    human: bool = False,
) -> tuple[str, str | None]:
    """Pointer text, plus a durable handle when one could be written.

    A human attachment is announced as what it is. A model that finds an
    unexplained hole where a person's screenshot was can conclude the person
    withdrew it and re-plan around a requirement that never changed.
    """
    mime, encoded = _split_data_url(url)
    handle = vault(url) if vault is not None else None
    if handle:
        guidance = (
            f"handle=sha256:{handle}. "
            "Call recall_media with that handle to read it again."
        )
    else:
        guidance = (
            f"fingerprint=sha256:{_media_digest(url)}. "
            "Re-run the producing tool to observe it again."
        )
    label = (
        "user attachment moved out of this request"
        if human
        else "inline media left this context"
    )
    return (
        f"[{label}: {mime or 'unknown type'}, "
        f"{_decoded_size(encoded)} bytes. {guidance}]",
        handle,
    )


def _demote_in_node(
    node: Any,
    vault: "MediaVault | None" = None,
    *,
    human: bool = False,
) -> tuple[Any, list[tuple[str, str | None]]]:
    """Replace inline media under ``node`` with (data URL, handle) records."""
    removed: list[tuple[str, str | None]] = []
    if isinstance(node, str):
        if ";base64," not in node:
            return node, removed

        def replace(match: "re.Match[str]") -> str:
            stub, handle = _demotion_stub(
                match.group(0),
                vault,
                human=human,
            )
            removed.append((match.group(0), handle))
            return stub

        return _DATA_URL_PATTERN.sub(replace, node), removed
    if isinstance(node, Mapping):
        # Every value goes through the same walk, so a bare ``url`` holding a
        # payload turns into a stub instead of vanishing: a part the list
        # branch above did not recognize must still tell the model what left.
        out: dict[str, Any] = {}
        for key, value in node.items():
            replacement, inner = _demote_in_node(
                value,
                vault,
                human=human,
            )
            removed.extend(inner)
            out[key] = replacement
        return out, removed
    if isinstance(node, (list, tuple)):
        out_list: list[Any] = []
        for item in node:
            if (
                isinstance(item, Mapping)
                and str(item.get("type")) in _INLINE_MEDIA_PART_TYPES
            ):
                url = _data_url_of(item)
                if url is not None:
                    stub, handle = _demotion_stub(
                        url,
                        vault,
                        human=human,
                    )
                    out_list.append({"type": "text", "text": stub})
                    removed.append((url, handle))
                    continue
            replacement, inner = _demote_in_node(
                item,
                vault,
                human=human,
            )
            removed.extend(inner)
            out_list.append(replacement)
        return out_list, removed
    return node, removed


def collect_inline_media(
    value: Any,
    *,
    budget_bytes: int = MODEL_INPUT_BYTES,
) -> list[dict[str, Any]]:
    """Every inline block with the charge the budget actually applies to it.

    Shares ``_data_url_charge`` with the accounting path on purpose: an
    explanation that disagreed with what was being billed would be worse than
    no explanation at all.

    The walk has to reach the payloads that live inside a string rather than
    under a ``url`` key, because that is the shape a JSON tool answer takes and
    ``_demote_in_node`` strips those too. A census that skipped them would
    report fewer blocks than really left, and would tell the entry gate nothing
    is media-shaped while megabytes of Base64 sit in plain text the ladder is
    allowed to retire.
    """
    found: list[dict[str, Any]] = []

    def from_text(node: str) -> None:
        for match in _DATA_URL_PATTERN.finditer(node):
            mime, encoded = _split_data_url(match.group(0))
            found.append(
                {
                    "mime": mime,
                    "decoded_bytes": _decoded_size(encoded),
                    "charge": _data_url_charge(
                        match.group(0),
                        budget_bytes=budget_bytes,
                    ),
                },
            )

    def walk(node: Any) -> None:
        if isinstance(node, str):
            from_text(node)
            return
        if isinstance(node, Mapping):
            for key, child in node.items():
                if (
                    key == "url"
                    and isinstance(child, str)
                    and child.startswith("data:")
                ):
                    mime, encoded = _split_data_url(child)
                    found.append(
                        {
                            "mime": mime,
                            "decoded_bytes": _decoded_size(encoded),
                            "charge": _data_url_charge(
                                child,
                                budget_bytes=budget_bytes,
                            ),
                        },
                    )
                elif isinstance(child, str):
                    from_text(child)
                elif isinstance(child, (Mapping, list, tuple)):
                    walk(child)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(value)
    return found


# Same convention the host falls back to, so a plugin running without the host
# package measures the same request the same way.
_TEXT_BYTES_PER_TOKEN = 4.0


def _text_tokens(text: str) -> int:
    if _host_count_text_tokens is not None:
        return _host_count_text_tokens(text)
    if not text:
        return 0
    return max(
        1,
        int(len(text.encode("utf-8")) / _TEXT_BYTES_PER_TOKEN + 0.5),
    )


def _data_url_tokens(url: str) -> int:
    if _host_estimate_data_url_tokens is not None:
        estimated = _host_estimate_data_url_tokens(url)
        if estimated is not None:
            return estimated
    # A payload the host estimator will not price (an exotic container) still
    # has to cost something, so the byte charge converts at the text rate.
    return max(
        1,
        int(
            _data_url_charge(url) / _TEXT_BYTES_PER_TOKEN + 0.5,
        ),
    )


def estimate_input_tokens(value: Any) -> int:
    """Tokens a provider input would cost, inline media priced as vision.

    Bytes and tokens disagree in both directions: a screenshot is megabytes of
    Base64 for a few thousand tokens, while dense CJK text is few bytes for
    many tokens. A guard watching only one of them will keep the wrong thing.
    """
    if value is None:
        return 0
    if isinstance(value, str):
        if not value:
            return 0
        total = 0
        cursor = 0
        for match in _DATA_URL_PATTERN.finditer(value):
            total += _text_tokens(value[cursor : match.start()])
            total += _data_url_tokens(match.group(0))
            cursor = match.end()
        return total + _text_tokens(value[cursor:])
    if isinstance(value, Mapping):
        total = 0
        for key, child in value.items():
            if (
                key == "url"
                and isinstance(child, str)
                and child.startswith("data:")
            ):
                # The same shape the byte accounting walks, so the two
                # measurements cannot diverge on which block is media.
                total += _data_url_tokens(child)
            else:
                total += estimate_input_tokens(child)
        return total
    if isinstance(value, (list, tuple)):
        return sum(estimate_input_tokens(item) for item in value)
    return 0


def budget_diagnostics(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    *,
    max_bytes: int,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    payload = {"messages": messages, "tools": tools}
    blocks = collect_inline_media(payload, budget_bytes=max_bytes)
    by_role: dict[str, int] = {}
    for item in messages:
        role = str(item.get("role") or "?")
        by_role[role] = by_role.get(role, 0) + _media_aware_bytes(
            item,
            budget_bytes=max_bytes,
        )
    return {
        "max_bytes": max_bytes,
        "used_bytes": _media_aware_bytes(payload, budget_bytes=max_bytes),
        "raw_bytes": json_bytes(payload),
        "max_tokens": max_tokens,
        "input_tokens": estimate_input_tokens(payload),
        "role_bytes": by_role,
        "media_block_count": len(blocks),
        "media_charge_bytes": sum(int(b["charge"]) for b in blocks),
        # The most expensive blocks first: the one worth shrinking is nearly
        # always at the head, and a long list would bury it.
        "media_blocks": sorted(
            blocks,
            key=lambda b: int(b["charge"]),
            reverse=True,
        )[:5],
    }


# Recorded on the message that carried the block and kept through history
# compaction by the metadata whitelist below, so "what left this context"
# stays answerable several turns after the demotion happened.
DEMOTED_MEDIA_METADATA_KEY = "demotedMedia"
MAX_RECORDED_DEMOTIONS = 8


def _handle_record(url: str, handle: str, *, turn: Any) -> dict[str, Any]:
    """What a pointer promises: the bytes, the price, where they came from."""
    mime, encoded = _split_data_url(url)
    return {
        "handle": handle,
        "mime": mime or "application/octet-stream",
        "decodedBytes": _decoded_size(encoded),
        "estimatedTokens": _data_url_tokens(url),
        "messageSeq": turn,
    }


def _demotion_eligible(record: Mapping[str, Any]) -> bool:
    """Whether this message's media is the runtime's own observation.

    Tool results and the receipts the runtime carries in the user role can be
    observed again by re-running the tool that produced them. A requirement a
    person typed or uploaded cannot, so it stays out of this set.
    """
    return record.get("role") == "tool" or (
        record.get("role") == "user"
        and record.get("source") in _AUTOMATED_HISTORY_SOURCES
    )


def _record_demotions(
    record: dict[str, Any],
    removed: list[tuple[str, str | None]],
) -> list[dict[str, Any]]:
    """Attach the stored handles to the message that lost its media."""
    handles = [
        _handle_record(url, handle, turn=record.get("messageSeq"))
        for url, handle in removed
        if handle
    ]
    if not handles:
        return []
    metadata = dict(record.get("metadata") or {})
    previous = metadata.get(DEMOTED_MEDIA_METADATA_KEY)
    listed = [*handles, *(previous if isinstance(previous, list) else [])]
    metadata[DEMOTED_MEDIA_METADATA_KEY] = listed[:MAX_RECORDED_DEMOTIONS]
    record["metadata"] = metadata
    return handles


def demote_derived_inline_media(
    messages: Sequence[Mapping[str, Any]],
    *,
    budget_bytes: int = MODEL_INPUT_BYTES,
    vault: "MediaVault | None" = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Move inline media out of the messages compaction is allowed to trim.

    Compaction stops at contract content, so a refused request carrying a
    derived screenshot has no other relief available. This demotes only what
    can be observed again by re-running a tool; a human attachment is left to
    ``demote_human_inline_media``, which additionally requires a durable copy.

    ``vault`` writes a payload down and returns its handle. Without one the
    pointer still describes what left, just without a recall to offer.
    """
    result: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []
    untouched: list[dict[str, Any]] = []
    handles: list[dict[str, Any]] = []
    for item in messages:
        record = dict(item)
        blocks = collect_inline_media(
            record.get("content"),
            budget_bytes=budget_bytes,
        )
        if not blocks:
            result.append(record)
            continue
        if not _demotion_eligible(record):
            untouched.extend(blocks)
            result.append(record)
            continue
        content, removed = _demote_in_node(record.get("content"), vault)
        if removed:
            record["content"] = content
            demoted.extend(blocks)
            handles.extend(_record_demotions(record, removed))
        result.append(record)
    return result, {
        "demoted_blocks": len(demoted),
        "demoted_charge_bytes": sum(int(b["charge"]) for b in demoted),
        "stored_blocks": len(handles),
        "human_attachment_blocks": len(untouched),
        "handles": handles,
    }


def demote_human_inline_media(
    messages: Sequence[Mapping[str, Any]],
    *,
    vault: "MediaVault | None",
    budget_bytes: int = MODEL_INPUT_BYTES,
    one_step: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Last relief under real pressure: move a human attachment, or leave it.

    A message is demoted whole or not at all, because a partially shorn
    requirement reads like a person who changed their mind. A block whose
    bytes could not be stored keeps its payload: the budget is allowed to
    fail, an upload a human made is not allowed to disappear quietly.

    ``one_step`` moves the single most expensive attachment and stops. The
    caller re-checks the real budget after every step, so a request that fits
    once one picture has left does not lose the rest of a person's uploads.
    """
    result: list[dict[str, Any]] = [dict(item) for item in messages]
    candidates: list[tuple[int, int]] = []
    for index, record in enumerate(result):
        if _demotion_eligible(record):
            continue
        blocks = collect_inline_media(
            record.get("content"),
            budget_bytes=budget_bytes,
        )
        if blocks:
            candidates.append(
                (index, sum(int(block["charge"]) for block in blocks)),
            )

    moved: list[dict[str, Any]] = []
    handles: list[dict[str, Any]] = []
    refused = 0

    def attempt(index: int) -> bool:
        nonlocal refused
        record = result[index]
        blocks = collect_inline_media(
            record.get("content"),
            budget_bytes=budget_bytes,
        )
        content, removed = (
            _demote_in_node(record.get("content"), vault, human=True)
            if vault is not None
            else (None, [])
        )
        if not removed or not all(handle for _, handle in removed):
            refused += len(blocks)
            return False
        record["content"] = content
        moved.extend(blocks)
        handles.extend(_record_demotions(record, removed))
        return True

    ordered = (
        sorted(candidates, key=lambda item: -item[1])
        if one_step
        else candidates
    )
    for index, _charge in ordered:
        if attempt(index) and one_step:
            break
    return result, {
        "demoted_blocks": len(moved),
        "demoted_charge_bytes": sum(int(block["charge"]) for block in moved),
        "stored_blocks": len(handles),
        "refused_blocks": refused,
        "handles": handles,
    }


def _format_bytes(value: Any) -> str:
    return f"{int(value):,}"


def format_budget_failure(exc: ModelContextBudgetError) -> str:
    """Render a local refusal as something a user can act on."""
    info = exc.diagnostics
    if not info:
        return str(exc)
    lines = [
        str(exc),
        (
            f"预算 {_format_bytes(info.get('max_bytes', 0))} 字节，"
            f"实际 {_format_bytes(info.get('used_bytes', 0))} 字节"
            f"（未计媒体时 {_format_bytes(info.get('raw_bytes', 0))} 字节）。"
        ),
    ]
    token_limit = info.get("max_tokens")
    if token_limit:
        lines.append(
            "按模型窗口计：输入 "
            f"{_format_bytes(info.get('input_tokens', 0))} token，"
            f"上限 {_format_bytes(token_limit)} token。",
        )
    roles = info.get("role_bytes") or {}
    if roles:
        lines.append(
            "按角色占用："
            + "、".join(
                f"{role} {_format_bytes(size)}"
                for role, size in sorted(
                    roles.items(),
                    key=lambda kv: int(kv[1]),
                    reverse=True,
                )
            ),
        )
    blocks = info.get("media_blocks") or []
    if blocks:
        priciest = "、".join(
            (
                f"{block.get('mime') or '未知类型'} "
                f"{_format_bytes(block.get('decoded_bytes', 0))} 字节"
                f"→计费 {_format_bytes(block.get('charge', 0))}"
            )
            for block in blocks[:3]
        )
        lines.append(
            "内联媒体 "
            f"{info.get('media_block_count', len(blocks))} 块，"
            f"共计费 {_format_bytes(info.get('media_charge_bytes', 0))} 字节，"
            f"最贵的：{priciest}",
        )
        lines.append(
            "可压缩的工具交换已清空，超出部分由上述媒体或必要契约输入承担。",
        )
    return "\n".join(lines)


def media_could_bridge_the_gap(diagnostics: Mapping[str, Any]) -> bool:
    """Whether retiring inline media could plausibly close a refusal's gap.

    The accounting that names the overage also names what every inline block
    costs, so a request overflowing on contract text can be told apart from
    one overflowing on a screenshot. Only the second kind earns a human upload
    being moved: an attachment cannot shrink text by a byte, so demoting the
    whole batch spends the uploads on the way to the same failure.

    A refusal carrying no diagnostics answers ``True``, which is no licence to
    demote on a guess: the caller is expected to measure the shape it is about
    to trade first, since an unread gap is more often contract text than media.
    """
    if not diagnostics:
        return True
    used = int(diagnostics.get("used_bytes") or 0)
    ceiling = int(diagnostics.get("max_bytes") or 0)
    charged = int(diagnostics.get("media_charge_bytes") or 0)
    if used <= ceiling:
        # The token guard refused, not the byte guard. Media is still the only
        # thing this ladder can move, and a byte charge is not comparable to a
        # token gap, so the guard is not dismissed here.
        return True
    return charged >= used - ceiling


def format_demotion_record(
    entries: Sequence[tuple[str, Mapping[str, Any]]],
) -> str:
    """Say what the guard already gave up, so a refusal is locatable.

    A refusal that arrives after two demotion steps means the surviving input
    is not what the caller handed in. Without the record, "it keeps erroring"
    has no way to show which blocks left and where their bytes are.
    """
    parts: list[str] = []
    handles: list[str] = []
    for label, receipt in entries:
        count = int(receipt.get("demoted_blocks") or 0)
        stored = int(receipt.get("stored_blocks") or 0)
        if not count and not stored:
            continue
        parts.append(f"{label} {count} 块（已存档 {stored} 块）")
        for item in receipt.get("handles") or []:
            if isinstance(item, Mapping) and item.get("handle"):
                handles.append(str(item["handle"]))
    if not parts:
        return ""
    text = "媒体降级记录：" + "；".join(parts)
    if handles:
        shown = "、".join(f"sha256:{handle[:12]}" for handle in handles[:3])
        text += f"；句柄 {shown}" + (" 等" if len(handles) > 3 else "")
    return text


def _snapshot_content(content: Any) -> Mapping[str, Any] | None:
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                snapshot = _snapshot_content(part.get("text"))
                if snapshot is not None:
                    return snapshot
        return None
    if not isinstance(content, str):
        return None
    # Every project view carries a quoted ``etag`` and every ordinary tool
    # answer does not, so one C-level substring scan replaces parsing the
    # megabytes of scene reviews and file listings that make up most of a
    # long history. Nothing that could pass the checks below lacks the key.
    if '"etag"' not in content:
        return None
    try:
        payload = json.loads(content)
    except ValueError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("project"), dict):
        if payload["project"].get("project_id") and payload.get("etag"):
            return payload
    return None


# The project view compaction reattaches after it evicts the exchange that
# held the snapshot. It is a compaction artifact carried in the provider's
# user role, not a turn anyone asked for, so the prefix is what identifies it
# once it leaves this module: ``_context_snapshot`` is stripped on the way.
PROJECT_MODEL_VIEW_PREFIX = "CURRENT_PROJECT_MODEL_VIEW="


def is_carried_project_view(message: Mapping[str, Any]) -> bool:
    """Whether this row is a project view an earlier compaction reattached.

    A run that adopts the shape it just sent hands its own output back as the
    next turn's input. Recognizing the artifact by its marker alone would then
    pin one stale view per turn: user-role rows are never evictable here, so
    the pinned copies accumulate until nothing left can move and the request
    refuses itself. Matching the prefix keeps the guarantee the compaction
    already intends — one view, always the newest.
    """
    if message.get("_context_snapshot"):
        return True
    content = message.get("content")
    return (
        message.get("role") == "user"
        and isinstance(content, str)
        and content.startswith(PROJECT_MODEL_VIEW_PREFIX)
    )


# An elided turn is only gone from the live window; its record stays
# durable in the session store, addressable by ``messageSeq``. The map below
# mirrors the platform eviction index: it tells the model *what* was dropped
# and *which seq* to recall it by, instead of leaving a bare count that no
# one can act on. The dropped turns are already out of the byte gate by the
# time the map is built, so it rides on top of the result rather than inside
# that gate. It is hard-bounded here - a fixed per-block line cap and a
# character budget - but that bound (``ARCHIVED_INDEX_CHAR_BUDGET`` plus the
# preamble, ~3.4KB) is larger than the 256-byte headroom the compaction loop
# reserves, so the combined history view can still sit up to one bounded map
# above ``HISTORY_BYTES``. The outer byte and token gates measure the
# serialized request again, so the overshoot stays bounded and safe.
_ARCHIVED_HEADLINE_CHARS = 120
_ARCHIVED_INDEX_MAX_LINES = 24
# The host odometer is folded to this character budget for the model view.
# It is Creator's own bound, aligned with the per-block line cap, not the
# one-off character cap the continuation-summary preview borrows elsewhere.
ARCHIVED_INDEX_CHAR_BUDGET = 3_200

# Creator's own recall guidance, emitted on both the host and fallback paths
# so the model is never shown the platform's wording about a
# ``conversation_history`` table and an "advanced Python recall tool" that a
# Creator session does not have.
_ARCHIVED_MAP_PREAMBLE = (
    "[context compressed] the turns below left the live window but remain "
    "durable by messageSeq; read them back with "
    'recall_history(op="expand", lo=..., hi=...) or '
    'op="search". Oldest first.'
)


def _record_headline(item: Mapping[str, Any]) -> str:
    """One bounded line naming what an elided turn was about."""
    content = item.get("content")
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                text = part["text"]
                break
    collapsed = " ".join(text.split())
    if not collapsed:
        role = str(item.get("role") or "message")
        source = str(item.get("source") or "")
        collapsed = f"{role} {source}".strip()
    return collapsed[:_ARCHIVED_HEADLINE_CHARS]


def _split_host_map_body(rendered: str) -> str | None:
    """Keep the platform odometer body, drop the host recall preamble.

    ``render`` leads with prose naming a ``conversation_history`` table and
    an "advanced Python recall tool" that do not exist for a Creator session,
    then the tiered body. Every fold level - expanded, endpoint, or the
    last-resort global span - opens its body with a ``====`` banner and no
    preamble line ever does, so slicing at the first banner keeps exactly the
    map the platform draws while Creator supplies its own preamble.

    ``None`` means no banner was found: a host upgrade changed the render,
    leaving no trustworthy boundary between that preamble and the body. The
    caller then keeps Creator's own flat map rather than echo the host's
    preamble - it names a store and a tool this session does not have, and
    it describes a live-turn banner the render was asked to omit.
    """
    lines = rendered.splitlines()
    for offset, line in enumerate(lines):
        if line.startswith("===="):
            return "\n".join(lines[offset:])
    return None


def _render_archived_index(
    archived: Sequence[Mapping[str, Any]],
) -> tuple[str, int | None, int | None]:
    """Render dropped turns into a recallable map, oldest first.

    Turns without a durable ``messageSeq`` (unit-test fixtures) carry no
    address, so they are skipped: the map only lists what recall can
    actually fetch back, never a pointer to nothing.

    When the host scroll is importable the platform ``EvictionIndex`` draws
    the map. The archived turns are split into blocks of
    ``_ARCHIVED_INDEX_MAX_LINES`` and dropped one eviction per block, so the
    odometer actually carries and folds as the archive grows the way the
    platform intends - feeding a single block would leave one endpoint line
    naming just the oldest and newest headlines and throw away the per-turn
    pointers that make the map recallable. ``render`` is folded to a bounded
    character budget and its host-specific preamble is sliced off in favour
    of Creator's own recall guidance.

    A standalone plugin install, and a host render whose banner no longer
    marks the body boundary, both fall back to Creator's flat
    ``seq . headline`` list; either way the returned text already carries the
    ``[context compressed]`` preamble, so the caller never wraps it again.
    """
    addressable = [
        item for item in archived if isinstance(item.get("seq"), int)
    ]
    if not addressable:
        return "", None, None
    seqs = [int(item["seq"]) for item in addressable]
    lo, hi = min(seqs), max(seqs)

    if _HOST_EVICTION_INDEX_AVAILABLE and _HostEvictionIndex is not None:
        leaves = [
            _HostEvictionLeaf(
                seq=int(item["seq"]),
                headline=_record_headline(item),
            )
            for item in addressable
        ]
        index = _HostEvictionIndex(session_id="creator")
        step = max(_ARCHIVED_INDEX_MAX_LINES, 1)
        for start in range(0, len(leaves), step):
            block = leaves[start : start + step]
            block_seqs = [leaf.seq for leaf in block]
            index.add_eviction(
                block,
                seq_lo=min(block_seqs),
                seq_hi=max(block_seqs),
            )
        rendered = index.render(
            include_envelope=False,
            include_live_banner=False,
            detail_char_budget=ARCHIVED_INDEX_CHAR_BUDGET,
        )
        body = _split_host_map_body(rendered)
        if body is not None:
            return f"{_ARCHIVED_MAP_PREAMBLE}\n{body}", lo, hi
        # A host upgrade that drops the banner leaves no boundary between
        # its preamble and its body. Fall through to Creator's own map:
        # echoing the whole render would repeat the compression notice and
        # describe a live-turn banner this call deliberately omits.

    lines: list[str] = []
    shown = addressable
    if len(shown) > _ARCHIVED_INDEX_MAX_LINES:
        overflow = len(shown) - _ARCHIVED_INDEX_MAX_LINES + 1
        early_hi = seqs[overflow - 1]
        lines.append(
            f"{lo}-{early_hi} ... ({overflow} older turns "
            "archived; recall by seq)",
        )
        shown = shown[overflow:]
    for item in shown:
        lines.append(
            f"{item['seq']} . " f"\u27e6{_record_headline(item)}\u27e7",
        )
    return (
        f"{_ARCHIVED_MAP_PREAMBLE}\n" + "\n".join(lines),
        lo,
        hi,
    )


#: Metadata keys a turn keeps through compaction. Everything else on a
#: durable message is streaming/raw argument diagnostics that belong to
#: tracing, not context. ``demotedMedia`` stays because a pointer is the only
#: place a demoted attachment can be found from afterwards.
_COMPACTION_METADATA_KEYS: Final = frozenset(
    {
        "toolName",
        "tool",
        "resultKind",
        "transactionId",
        "reviewId",
        "status",
        DEMOTED_MEDIA_METADATA_KEY,
    },
)


def plan_history_compaction(
    history: list[dict[str, Any]],
    *,
    max_bytes: int = HISTORY_BYTES,
    max_tokens: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compact the history view and hand back the turns it archived.

    Split out of ``compact_conversation_history`` so an async caller can read
    the dropped slice (via ``render_archived_evidence``) and ask the model for
    a continuation summary before the compacted view is serialized, without
    re-walking the budget by hand and risking drift against it.

    Cost is bounded by the budget, not by the history. Measuring a turn means
    serializing it, and the field's largest conversation is 640 MB over 3.4k
    turns: a whole-history measurement holds the GIL for seconds on every
    model turn, which is the stall the home page used to sit behind. The fit
    probe stops as soon as the running total passes ``max_bytes``, and the cut
    is found from the newest end, so turns older than it are never serialized
    at all -- they are classified from dict fields alone.
    """
    result = deepcopy(history)
    for item in result:
        item["metadata"] = {
            key: value
            for key, value in (item.get("metadata") or {}).items()
            if key in _COMPACTION_METADATA_KEYS
        }
    # The newest project view must survive, and older views are receipts by
    # the time they reach here, so the first hit walking from the end is the
    # one to protect: a history that ends with a snapshot never walks the
    # rest of itself.
    latest_snapshot: int | None = None
    for index in range(len(result) - 1, -1, -1):
        for part in result[index].get("content") or []:
            if isinstance(part, dict) and _snapshot_content(part.get("text")):
                latest_snapshot = index
                break
        if latest_snapshot is not None:
            break
    total = len(result)
    # Serialized size and token cost are both plain sums over list items, so
    # the budget can be walked turn by turn; archiving one turn replaces it
    # with a ``null`` (four bytes) and leaves the separating commas alone.
    # Neither measurement is repeated: whatever the probe or the cut looks at
    # is cached for the other.
    measured: dict[int, tuple[int, int, int]] = {}

    def measure(index: int) -> tuple[int, int, int]:
        cached = measured.get(index)
        if cached is None:
            item = result[index]
            cached = (
                json_bytes(item),
                _inline_media_relief(item, budget_bytes=max_bytes),
                0 if max_tokens is None else estimate_input_tokens(item),
            )
            measured[index] = cached
        return cached

    # Prove the whole view fits, stopping the moment it cannot: nothing after
    # an over-budget running total can bring it back down. A short history
    # pays the full walk it must pay anyway; a huge one pays one turn of it.
    spent = 2 + max(total - 1, 0)
    spent_tokens = 0
    for index in range(total):
        item_bytes, relief_bytes, item_tokens = measure(index)
        spent += item_bytes - relief_bytes
        spent_tokens += item_tokens
        if spent > max_bytes or (
            max_tokens is not None and spent_tokens > max_tokens
        ):
            break
    else:
        return result, []
    # Preserve every human goal/constraint and the newest state. Runtime
    # feedback also uses the user role; retaining every old review would make
    # a long production exceed the hard budget even after all tools are gone.
    # The current request/notification batch is outside this history view.
    keeps = [
        (
            item.get("role") == "user"
            and item.get("source") not in _AUTOMATED_HISTORY_SOURCES
        )
        or index == latest_snapshot
        for index, item in enumerate(result)
    ]
    archiveable = [index for index in range(total) if not keeps[index]]
    # The loop this replaces archived the oldest turns in order and stopped
    # at the first one that would leave the view above ``max_bytes - 256``;
    # that is exactly the longest suffix that still fits. Walking that suffix
    # in from the newest end is what keeps the cost bounded, and the null
    # placeholders the archived prefix leaves behind are carried as overhead.
    spent = 2 + max(total - 1, 0) + 4 * len(archiveable)
    spent_tokens = 0
    for index in range(total):
        if not keeps[index]:
            continue
        item_bytes, relief_bytes, item_tokens = measure(index)
        spent += item_bytes - relief_bytes
        spent_tokens += item_tokens
    for index in reversed(archiveable):
        item_bytes, relief_bytes, item_tokens = measure(index)
        kept_bytes = spent + item_bytes - relief_bytes - 4
        kept_tokens = spent_tokens + item_tokens
        if kept_bytes > max_bytes - 256 or (
            max_tokens is not None and kept_tokens > max_tokens
        ):
            break
        spent = kept_bytes
        spent_tokens = kept_tokens
        keeps[index] = True
    archived: list[dict[str, Any]] = []
    for index in archiveable:
        if keeps[index]:
            continue
        item = result[index]
        seq = item.get("messageSeq")
        archived.append(
            {
                "seq": seq if isinstance(seq, int) else None,
                "role": item.get("role"),
                "source": item.get("source"),
                "content": item.get("content"),
            },
        )
    elision: dict[str, Any] = {
        "role": "system",
        "source": "context_compaction",
        "elidedMessageCount": len(archived),
    }
    history_map, seq_lo, seq_hi = _render_archived_index(archived)
    if history_map:
        # The dropped turns are not gone: they stay durable in the session
        # store under the seqs listed here. _render_archived_index already
        # carries the ``[context compressed]`` preamble and the recall
        # guidance - the platform odometer map when the host scroll is
        # importable, Creator's flat fallback otherwise - so the caller
        # assigns it verbatim rather than wrapping it a second time.
        elision["archivedHistoryMap"] = history_map
        elision["recoverableSeqRange"] = [seq_lo, seq_hi]
    return [
        elision,
        *(result[index] for index in range(total) if keeps[index]),
    ], archived


# A continuation summary is a state cache over the *archived* slice, so its
# prompt carries a bounded preview of exactly those turns, not the whole
# window. The platform fits that preview with a binary search over
# ``model.count_tokens``; Creator has no such hook on the compaction path, so
# it caps the preview by characters instead. The durable pointers, not this
# preview, stay authoritative — the prompt already says so.
ARCHIVED_EVIDENCE_MAX_CHARS = 16_000
ARCHIVED_EVIDENCE_TURN_MAX_CHARS = 1_500


def _archived_turn_text(item: Mapping[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"]
            for part in content
            if isinstance(part, Mapping) and isinstance(part.get("text"), str)
        )
    return ""


def render_archived_evidence(
    archived: Sequence[Mapping[str, Any]],
    *,
    max_chars: int = ARCHIVED_EVIDENCE_MAX_CHARS,
) -> tuple[str, tuple[int | None, int | None]]:
    """Render the archived slice into a bounded prompt preview and its range.

    The returned ``(lo, hi)`` spans every addressable archived turn even when
    ``max_chars`` truncates the body: the model is told the covered range, so
    a preview that stops early must not shrink what the summary may claim to
    cover. Turns with no durable ``seq`` are skipped, matching the recall map.
    """
    addressable = [
        item for item in archived if isinstance(item.get("seq"), int)
    ]
    if not addressable:
        return "", (None, None)
    seqs = [int(item["seq"]) for item in addressable]
    bounds: tuple[int | None, int | None] = (min(seqs), max(seqs))
    lines: list[str] = []
    used = 0
    for item in addressable:
        body = " ".join(
            _archived_turn_text(item).split(),
        )[:ARCHIVED_EVIDENCE_TURN_MAX_CHARS]
        role = str(item.get("role") or "message")
        source = str(item.get("source") or "").strip()
        line = f"[seq:{item['seq']}] {role} {source}: {body}".strip()
        # Always keep the first turn, however long, so a tiny budget still
        # yields some evidence; only later turns are dropped once the cap is
        # reached. The covered bounds stay the full range regardless.
        if lines and used + len(line) + 1 > max_chars:
            break
        used += len(line) + 1
        lines.append(line)
    return "\n".join(lines), bounds


def compact_conversation_history(
    history: list[dict[str, Any]],
    *,
    max_bytes: int = HISTORY_BYTES,
    max_tokens: int | None = None,
    continuation_summary: str = "",
) -> list[dict[str, Any]]:
    """Compact the history view, optionally carrying a continuation summary.

    The summary is the platform scroll's fourth relief lever: a prose state
    cache that reads beside the seq recall map. It rides on the compaction
    marker only when the caller actually produced one (the async driver asks
    the model); serialization itself stays synchronous here.
    """
    compacted, _archived = plan_history_compaction(
        history,
        max_bytes=max_bytes,
        max_tokens=max_tokens,
    )
    if (
        continuation_summary
        and compacted
        and compacted[0].get("source") == "context_compaction"
    ):
        compacted[0]["continuationSummary"] = continuation_summary
    return compacted


def _shrink_continuation(
    content: str,
    max_bytes: int,
    latest_snapshot: Mapping[str, Any] | None,
    max_tokens: int | None = None,
) -> str:
    marker = "CONVERSATION_HISTORY_JSON="
    ending = "\n\nCURRENT_USER_REQUEST=\n"
    if marker not in content or ending not in content:
        return content
    opening, rest = content.split(marker, 1)
    raw, request = rest.split(ending, 1)
    try:
        history = json.loads(raw)
    except ValueError:
        return content
    if not isinstance(history, list):
        return content
    if latest_snapshot:
        for item in history:
            # Human messages may contain JSON too; never rewrite them.
            if item.get("role") != "tool":
                continue
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                previous = _snapshot_content(part.get("text"))
                if previous and _snapshot_supersedes(
                    latest_snapshot,
                    previous,
                ):
                    part["text"] = json_text(
                        {
                            "resultKind": "project_change_receipt",
                            "projectId": previous["project"]["project_id"],
                            "generation": previous.get("generation"),
                            "etag": previous.get("etag"),
                            "note": "A newer Project view is in this run.",
                        },
                    )
    return (
        opening
        + marker
        + json_text(
            compact_conversation_history(
                history,
                max_bytes=max_bytes,
                max_tokens=max_tokens,
            ),
        )
        + ending
        + request
    )


def _snapshot_supersedes(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
) -> bool:
    current_generation = current.get("generation")
    previous_generation = previous.get("generation")
    return (
        current["project"]["project_id"] == previous["project"]["project_id"]
        and isinstance(current_generation, int)
        and isinstance(previous_generation, int)
        and current_generation >= previous_generation
    )


def _carried_view_snapshot(
    result: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Parse the newest carried project view an earlier compaction reattached.

    When the tool scan above finds no snapshot, the run is resuming from
    a shape the prior turn sent back. Without this fallback the loop below
    would strip the only survivor and skip re-attaching it because
    ``carried_snapshot`` stayed ``None``, leaving the model without project
    state (the reviewer's second-compression path).
    """
    for item in reversed(list(result)):
        if not is_carried_project_view(item):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        if not content.startswith(PROJECT_MODEL_VIEW_PREFIX):
            continue
        payload = _snapshot_content(
            content[len(PROJECT_MODEL_VIEW_PREFIX) :],
        )
        if payload:
            return payload
    return None


# Preserve complete protocol groups throughout each compaction stage.
# pylint: disable-next=too-many-branches
def prepare_model_messages(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    *,
    max_bytes: int = MODEL_INPUT_BYTES,
    max_tokens: int | None = None,
) -> list[dict[str, Any]]:
    """Drop completed tool exchanges as units; retain user/system contracts.

    Large completed calls include their arguments, so deleting just an old
    tool result is insufficient. Both call and results leave together. A
    removed latest Project view is reattached separately for reconstruction.
    """
    result = deepcopy([dict(item) for item in messages])
    latest_snapshot = None
    for item in result:
        content = item.get("content")
        if item.get("role") != "tool":
            continue
        parts = (
            [{"type": "text", "text": content}]
            if isinstance(content, str)
            else content
        )
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "text":
                continue
            payload = _snapshot_content(part.get("text"))
            if payload:
                part["text"] = json_text(
                    project_snapshot_view(
                        payload,
                        max_bytes=min(64 * 1024, max_bytes // 4),
                    ),
                )
                latest_snapshot = json.loads(part["text"])
        if isinstance(content, str):
            item["content"] = parts[0]["text"]

    # ``latest_snapshot`` is normally seeded from the tool scan above.  When
    # the caller resumes from a compressed shape (a carried view the prior
    # turn reattached) the run may have no tool snapshot at all, and the
    # loop below would then strip the only survivor without a replacement.
    # Fall back to parsing the newest carried view so the guard at the
    # eviction site has something to compare against.
    if latest_snapshot is None:
        latest_snapshot = _carried_view_snapshot(result)

    # A prior-run snapshot must not be pinned alongside its replacement.
    # That duplicate can evict the script, skills and references just read,
    # trapping long productions in repeated reconstruction instead of work.
    for item in result:
        content = item.get("content")
        if item.get("role") == "user" and isinstance(content, str):
            item["content"] = _shrink_continuation(
                content,
                min(HISTORY_BYTES, max_bytes // 4),
                latest_snapshot,
                None if max_tokens is None else max_tokens // 4,
            )

    def request_payload() -> dict[str, Any]:
        return {"messages": result, "tools": tools}

    def size() -> int:
        # Inline media is charged as vision tokens, not as Base64 text, so a
        # media-bearing contract message can fit alongside the tools schema.
        return _media_aware_bytes(request_payload(), budget_bytes=max_bytes)

    def over_budget() -> bool:
        if size() > max_bytes:
            return True
        # Bytes miss the mistake in both directions: a screenshot is megabytes
        # of Base64 for a few thousand vision tokens, while dense text is the
        # reverse. The token window resolved via ``context_window()`` is the
        # second guard; when available it is the primary rejection criterion,
        # with the byte transport floor acting only as a safety ceiling.
        return max_tokens is not None and (
            estimate_input_tokens(request_payload()) > max_tokens
        )

    carried_snapshot = None
    while over_budget():
        removable = None
        for start, item in enumerate(result):
            if item.get("role") != "assistant":
                continue
            calls = item.get("tool_calls") or []
            end = start + 1
            if calls:
                while end < len(result) and result[end].get("role") == "tool":
                    end += 1
                wanted = {call.get("id") for call in calls}
                results_start = start + 1
                received = {
                    row.get("tool_call_id")
                    for row in result[results_start:end]
                }
                if wanted != received:
                    continue  # Never split an outstanding native tool group.
            removable = (start, end)
            break
        if removable is None:
            raise ModelContextBudgetError(
                "模型必要输入仍超过单次上下文预算；请缩小单次请求或分段读取项目。",
                diagnostics=budget_diagnostics(
                    result,
                    tools,
                    max_bytes=max_bytes,
                    max_tokens=max_tokens,
                ),
            )
        start, end = removable
        for item in result[start:end]:
            payload = _snapshot_content(item.get("content"))
            if payload:
                carried_snapshot = latest_snapshot
        del result[start:end]
        # Keep only the newest carried view, and count it in the next check.
        # A previous turn's view reaches here too, because a run may resume
        # from the shape it last sent instead of rebuilding from durable
        # rows.  Strip it only when this iteration has a replacement to
        # attach; otherwise the newest view is the one already on the list
        # and evicting it would leave the model without any project state
        # (the reviewer's "second compression triggered by a plain text
        # tool result" path).
        if carried_snapshot:
            result = [
                item for item in result if not is_carried_project_view(item)
            ]
            result.append(
                {
                    "role": "user",
                    "_context_snapshot": True,
                    "content": PROJECT_MODEL_VIEW_PREFIX
                    + json_text(carried_snapshot),
                },
            )
    for item in result:
        item.pop("_context_snapshot", None)
    return result
