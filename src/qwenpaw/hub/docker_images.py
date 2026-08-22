# -*- coding: utf-8 -*-
"""In-memory Docker image pull coordination for QwenPaw Hub."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace

from .database import utc_now
from .docker_provisioner import DockerRuntimeProvisioner


@dataclass(frozen=True)
class DockerImagePull:
    """Describe one asynchronous Docker image pull."""

    pull_id: str
    reference: str
    status: str
    progress: int
    message: str
    error: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible pull status."""
        return asdict(self)


class DockerImagePullStore:
    """Deduplicate image pulls and expose lightweight progress state."""

    def __init__(self, provisioner: DockerRuntimeProvisioner) -> None:
        self.provisioner = provisioner
        self._lock = threading.Lock()
        self._pulls: dict[str, DockerImagePull] = {}
        self._active_by_reference: dict[str, str] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="qwenpaw-docker-pull",
        )

    def submit(self, reference: str) -> DockerImagePull:
        """Start or reuse an active pull for one normalized image."""
        normalized = self.provisioner.validate_config(
            {"image": reference},
        )["image"]
        with self._lock:
            active_id = self._active_by_reference.get(str(normalized))
            if active_id:
                return self._pulls[active_id]
            now = utc_now()
            pull = DockerImagePull(
                pull_id=uuid.uuid4().hex,
                reference=str(normalized),
                status="queued",
                progress=0,
                message="Waiting to pull image",
                error=None,
                created_at=now,
                updated_at=now,
            )
            self._pulls[pull.pull_id] = pull
            self._active_by_reference[pull.reference] = pull.pull_id
            self._executor.submit(self._run, pull.pull_id)
            return pull

    def get(self, pull_id: str) -> DockerImagePull:
        """Return one pull or raise KeyError."""
        with self._lock:
            pull = self._pulls.get(pull_id)
        if pull is None:
            raise KeyError(pull_id)
        return pull

    def list(self) -> list[DockerImagePull]:
        """Return recent pulls in reverse creation order."""
        with self._lock:
            return sorted(
                self._pulls.values(),
                key=lambda pull: pull.created_at,
                reverse=True,
            )

    def close(self) -> None:
        """Stop accepting work and wait for active pulls."""
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _run(self, pull_id: str) -> None:
        pull = self.get(pull_id)
        self._save(
            replace(
                pull,
                status="pulling",
                message="Pulling image",
                updated_at=utc_now(),
            ),
        )

        def progress(percent: int, message: str) -> None:
            current = self.get(pull_id)
            self._save(
                replace(
                    current,
                    progress=percent,
                    message=message,
                    updated_at=utc_now(),
                ),
            )

        try:
            self.provisioner.pull_image(pull.reference, progress)
            current = self.get(pull_id)
            final = replace(
                current,
                status="completed",
                progress=100,
                message="Image pull complete",
                updated_at=utc_now(),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            current = self.get(pull_id)
            final = replace(
                current,
                status="failed",
                message="Image pull failed",
                error=str(exc),
                updated_at=utc_now(),
            )
        self._save(final, finished=True)

    def _save(self, pull: DockerImagePull, *, finished: bool = False) -> None:
        with self._lock:
            self._pulls[pull.pull_id] = pull
            if finished:
                self._active_by_reference.pop(pull.reference, None)
