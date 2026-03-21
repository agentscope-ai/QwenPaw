# -*- coding: utf-8 -*-
"""Agent markdown manager for reading and writing markdown files in working
and memory directories."""
from datetime import datetime
from pathlib import Path

from ...constant import WORKING_DIR


class AgentMdManager:
    """Manager for reading and writing markdown files in working and memory
    directories."""

    def __init__(self, working_dir: str | Path):
        """Initialize directories for working and memory markdown files."""
        self.working_dir: Path = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir: Path = self.working_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def list_working_mds(self) -> list[dict]:
        """List all markdown files with metadata in the working dir.

        Returns:
            list[dict]: A list of dictionaries, each containing:
                - filename: name of the file (with .md extension)
                - size: file size in bytes
                - created_time: file creation timestamp
                - modified_time: file modification timestamp
        """
        md_files = list(self.working_dir.glob("*.md"))
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
                        ).isoformat(),
                        "modified_time": datetime.fromtimestamp(
                            stat.st_mtime,
                        ).isoformat(),
                    },
                )
        return result

    def read_working_md(self, md_name: str) -> str:
        """Read markdown file content from the working directory.

        Returns:
            str: The file content as string
        """
        # Auto-append .md extension if not present
        if not md_name.endswith(".md"):
            md_name += ".md"
        file_path = self.working_dir / md_name
        if not file_path.exists():
            raise FileNotFoundError(f"Working md file not found: {md_name}")

        return file_path.read_text(encoding="utf-8")

    def write_working_md(self, md_name: str, content: str):
        """Write markdown content to a file in the working directory."""
        # Auto-append .md extension if not present
        if not md_name.endswith(".md"):
            md_name += ".md"
        file_path = self.working_dir / md_name
        file_path.write_text(content, encoding="utf-8")

    def list_memory_mds(self) -> list[dict]:
        """List all markdown files with metadata in the memory dir.

        Returns:
            list[dict]: A list of dictionaries, each containing:
                - filename: name of the file (with .md extension)
                - size: file size in bytes
                - created_time: file creation timestamp
                - modified_time: file modification timestamp
        """
        md_files = list(self.memory_dir.glob("*.md"))
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
                        ).isoformat(),
                        "modified_time": datetime.fromtimestamp(
                            stat.st_mtime,
                        ).isoformat(),
                    },
                )
        return result

    def read_memory_md(self, md_name: str) -> str:
        """Read markdown file content from the memory directory.

        Returns:
            str: The file content as string
        """
        # Auto-append .md extension if not present
        if not md_name.endswith(".md"):
            md_name += ".md"
        file_path = self.memory_dir / md_name
        if not file_path.exists():
            raise FileNotFoundError(f"Memory md file not found: {md_name}")

        return file_path.read_text(encoding="utf-8")

    def write_memory_md(self, md_name: str, content: str):
        """Write markdown content to a file in the memory directory."""
        # Auto-append .md extension if not present
        if not md_name.endswith(".md"):
            md_name += ".md"
        file_path = self.memory_dir / md_name
        file_path.write_text(content, encoding="utf-8")


AGENT_MD_MANAGER = AgentMdManager(working_dir=WORKING_DIR)
