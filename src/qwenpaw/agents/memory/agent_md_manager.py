# -*- coding: utf-8 -*-
"""Agent Markdown manager for reading and writing markdown files in working
and memory directories."""

from datetime import datetime, timezone
from pathlib import Path

from ..utils.file_handling import read_text_file_with_encoding_fallback
from ...config.config import load_agent_config


class AgentMdManager:
    """Manager for reading and writing markdown files in working and memory
    directories."""

    def __init__(
        self,
        working_dir: str | Path,
        agent_id: str | None = None,
    ):
        """Initialize directories for working and memory markdown files.

        Args:
            working_dir: Path to agent's working directory
            agent_id: Optional agent ID for loading memory_dir from config.
                      If None, uses default "memory" directory.
        """
        self.working_dir: Path = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)

        digest_dir_name = "digest"

        # Dynamically get memory_dir from config if agent_id provided
        if agent_id:
            agent_config = load_agent_config(agent_id)
            reme_config = agent_config.running.reme_light_memory_config
            memory_dir_name = reme_config.daily_dir
            digest_dir_name = reme_config.digest_dir
        else:
            memory_dir_name = "memory"

        self.memory_dir: Path = self.working_dir / memory_dir_name
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.digest_dir: Path = self.working_dir / digest_dir_name
        self.digest_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_md_name(md_name: str) -> str:
        """Normalize *md_name* to a plain filename (no path components).

        Rejects names that contain path separators or ``..`` traversal
        sequences so that callers cannot escape the intended directory.

        Raises:
            ValueError: If the name contains illegal path components.
        """
        # Normalise Windows-style backslashes before any other check
        normalized = md_name.replace("\\", "/")

        # Reject any component that looks like directory traversal
        parts = normalized.split("/")
        for part in parts:
            if part == "..":
                raise ValueError(
                    f"Invalid md_name '{md_name}':"
                    " path traversal is not allowed",
                )

        # Keep only the final component so that any remaining "/" is stripped
        filename = parts[-1]

        if not filename:
            raise ValueError(f"Invalid md_name '{md_name}': filename is empty")

        return filename

    @staticmethod
    def _normalize_md_path(md_path: str) -> str:
        """Normalize a markdown path relative to a managed memory root."""
        normalized = md_path.replace("\\", "/").strip("/")
        parts = normalized.split("/")
        if not normalized or any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"Invalid md_path '{md_path}'")
        if not parts[-1].endswith(".md"):
            parts[-1] += ".md"
        return "/".join(parts)

    @staticmethod
    def _assert_within_dir(file_path: Path, base_dir: Path) -> None:
        """Raise *ValueError* if *file_path* resolves outside *base_dir*.

        Uses :meth:`Path.resolve` so that symlinks are followed before the
        comparison, which closes any remaining bypass vectors.
        """
        try:
            file_path.resolve().relative_to(base_dir.resolve())
        except ValueError:
            raise ValueError(
                f"Resolved path '{file_path}' escapes"
                f" the allowed directory '{base_dir}'",
            ) from None

    def list_working_mds(self) -> list[dict]:
        """List all markdown files with metadata in the working dir.

        Returns files sorted by modification time descending (newest first).

        Returns:
            list[dict]: A list of dictionaries, each containing:
                - filename: name of the file (with .md extension)
                - size: file size in bytes
                - created_time: file creation timestamp
                - modified_time: file modification timestamp
        """
        md_files = list(self.working_dir.glob("*.md"))
        # Sort by modification time descending (newest first)
        md_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        result = []
        for f in md_files:
            if f.is_file():
                stat = f.stat()
                result.append(
                    {
                        "filename": f.name,
                        "size": stat.st_size,
                        "path": str(f),
                        "created_time": datetime.fromtimestamp(
                            stat.st_ctime,
                            tz=timezone.utc,
                        ).isoformat(),
                        "modified_time": datetime.fromtimestamp(
                            stat.st_mtime,
                            tz=timezone.utc,
                        ).isoformat(),
                    },
                )
        return result

    def read_working_md(self, md_name: str) -> str:
        """Read markdown file content from the working directory.

        Returns:
            str: The file content as string
        """
        md_name = self._sanitize_md_name(md_name)
        if not md_name.endswith(".md"):
            md_name += ".md"
        file_path = self.working_dir / md_name
        self._assert_within_dir(file_path, self.working_dir)
        if not file_path.exists():
            raise FileNotFoundError(f"Working md file not found: {md_name}")

        return read_text_file_with_encoding_fallback(file_path).strip()

    def write_working_md(self, md_name: str, content: str):
        """Write markdown content to a file in the working directory."""
        md_name = self._sanitize_md_name(md_name)
        if not md_name.endswith(".md"):
            md_name += ".md"
        file_path = self.working_dir / md_name
        self._assert_within_dir(file_path, self.working_dir)
        file_path.write_text(content, encoding="utf-8")

    def _memory_path_for_read_write(self, md_path: str) -> Path:
        rel_path = self._normalize_md_path(md_path)
        digest_prefix = self.digest_dir.name
        if rel_path == f"{digest_prefix}.md":
            base_dir = self.memory_dir
            target = self.memory_dir / rel_path
        elif rel_path.startswith(f"{digest_prefix}/"):
            base_dir = self.digest_dir
            target = self.digest_dir / rel_path[len(digest_prefix) + 1 :]
        else:
            base_dir = self.memory_dir
            target = self.memory_dir / rel_path
        self._assert_within_dir(target, base_dir)
        return target

    def _memory_file_info(
        self,
        file_path: Path,
        filename: str,
        stat_result=None,
    ) -> dict:
        stat = stat_result or file_path.stat()
        return {
            "filename": filename,
            "size": stat.st_size,
            "path": str(file_path),
            "created_time": datetime.fromtimestamp(
                stat.st_ctime,
                tz=timezone.utc,
            ).isoformat(),
            "modified_time": datetime.fromtimestamp(
                stat.st_mtime,
                tz=timezone.utc,
            ).isoformat(),
        }

    def list_memory_mds(self) -> list[dict]:
        """List all markdown files with metadata in the memory dir.

        Returns files sorted by modification time descending (newest first).

        Returns:
            list[dict]: A list of dictionaries, each containing:
                - filename: name of the file (with .md extension)
                - size: file size in bytes
                - created_time: file creation timestamp
                - modified_time: file modification timestamp
        """
        result = []
        for root_dir, prefix in (
            (self.memory_dir, ""),
            (self.digest_dir, f"{self.digest_dir.name}/"),
        ):
            for file_path in root_dir.rglob("*.md"):
                if not file_path.is_file():
                    continue
                stat = file_path.stat()
                filename = (
                    f"{prefix}{file_path.relative_to(root_dir).as_posix()}"
                )
                result.append(
                    self._memory_file_info(file_path, filename, stat),
                )
        result.sort(key=lambda x: x["modified_time"], reverse=True)
        return result

    def read_memory_md(self, md_name: str) -> str:
        """Read markdown file content from the memory directory.

        Returns:
            str: The file content as string
        """
        file_path = self._memory_path_for_read_write(md_name)
        if not file_path.exists():
            raise FileNotFoundError(f"Memory md file not found: {md_name}")

        return read_text_file_with_encoding_fallback(file_path).strip()

    def write_memory_md(self, md_name: str, content: str):
        """Write markdown content to a file in the memory directory."""
        file_path = self._memory_path_for_read_write(md_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
