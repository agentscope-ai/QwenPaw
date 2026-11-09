# -*- coding: utf-8 -*-
"""Publish complete credentials before atomically switching their source.

The card replacement is the commit point. A crash before it may leave an
unreferenced credential, but never an active card pointing at an empty one.
Storage uses the same single-process locks as ordinary configuration writers.
"""

# pylint: disable=protected-access
from collections.abc import Callable, Collection, Mapping

from .contracts import DriverCard, iter_credential_refs
from .credentials.store import AsyncCredentialStore
from .credentials.types import CredentialRecord
from .errors import CredentialNotFoundError, DriverCardError
from .storage import (
    AsyncDriverCardStore,
    dump_card,
    load_card,
    list_card_paths,
)
from ..utils.io_utils import run_sync_io


async def commit_credential_binding(
    card_store: AsyncDriverCardStore,
    credential_store: AsyncCredentialStore,
    *,
    expected_card: DriverCard | None,
    expected_credentials: Mapping[str, int | None],
    candidate_card: DriverCard,
    candidate_record: CredentialRecord | None,
    guard: Callable[[], None],
) -> None:
    """Reject stale owners and publish a new record without overwriting."""
    previous = (
        set(iter_credential_refs(expected_card).values())
        if expected_card is not None
        else set()
    )
    bindings = set(iter_credential_refs(candidate_card).values())
    fresh = {
        ref for ref in bindings - previous if not ref.ref.startswith("env:")
    }
    if candidate_record is not None:
        valid_record = (
            len(fresh) == 1
            and any(
                ref.ref == candidate_record.ref
                and ref.kind == candidate_record.kind
                for ref in fresh
            )
            and candidate_record.ref not in expected_credentials
        )
    else:
        valid_record = not fresh
    if not valid_record or (
        expected_card is not None
        and (
            candidate_card.name != expected_card.name
            or candidate_card.protocol != expected_card.protocol
        )
    ):
        raise DriverCardError("Invalid credential binding candidate")

    def commit():
        # All composed operations take these existing locks in this order.
        with card_store._lock, credential_store._lock:
            guard()
            if (
                expected_card is not None
                and card_store._load_sync(
                    expected_card.name,
                    expected_card.protocol,
                )
                != expected_card
            ):
                raise DriverCardError("Driver source changed")
            for ref, expected in expected_credentials.items():
                try:
                    _, revision = credential_store.get_versioned_sync(ref)
                except CredentialNotFoundError:
                    revision = None
                if revision != expected:
                    raise DriverCardError("Driver credential changed")
            if (
                candidate_record is not None
                and not credential_store.put_if_absent_sync(candidate_record)
            ):
                raise DriverCardError("Credential candidate already exists")
            guard()
            if expected_card is None:
                if not card_store._save_if_absent_sync(candidate_card):
                    raise DriverCardError("Driver source already exists")
            else:
                dump_card(
                    candidate_card,
                    card_store.path_for(
                        candidate_card.name,
                        protocol=candidate_card.protocol,
                    ),
                )

    # A cancelled caller cannot clean up while this worker is still writing.
    await run_sync_io(commit)


async def cleanup_credential_candidates(
    card_store: AsyncDriverCardStore,
    credential_store: AsyncCredentialStore,
    *,
    owner: str,
    now: float,
    retained_refs: Collection[str] = (),
    discarded_refs: Collection[str] = (),
) -> None:
    """Collect expired, unreferenced owned records; fail closed on YAML."""

    def cleanup():
        with card_store._lock, credential_store._lock:
            referenced = {
                ref.ref
                for path in list_card_paths(card_store.cards_dir)
                for ref in iter_credential_refs(load_card(path)).values()
            }
            referenced.update(retained_refs)
            for ref in credential_store.list_refs_sync():
                record = credential_store.get_sync(ref)
                if ref not in referenced and (
                    ref in discarded_refs
                    or (
                        record.meta.get("candidate_owner") == owner
                        and float(record.meta.get("candidate_expires_at", 0))
                        <= now
                    )
                ):
                    credential_store.delete_sync(ref)

    await run_sync_io(cleanup)
