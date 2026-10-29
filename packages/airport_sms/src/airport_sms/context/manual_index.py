"""手册条款索引。"""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANUALS_DIR = PACKAGE_ROOT / "assets" / "manuals"


class ManualNotFoundError(Exception):
    """手册文件或目录缺失，失败关闭。"""


def parse_clauses(text: str) -> dict[str, str]:
    """从 markdown 解析 `## CLAUSE-ID` 条款正文。"""
    clauses: dict[str, str] = {}
    current_id: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_id is not None:
                clauses[current_id] = "\n".join(body).strip()
            current_id = line[3:].strip().split()[0]
            body = []
        elif current_id is not None:
            body.append(line)
    if current_id is not None:
        clauses[current_id] = "\n".join(body).strip()
    return clauses


class ManualIndex:
    """从 assets/manuals 加载条款。"""

    def __init__(self, manuals_dir: Path | None = None) -> None:
        self._dir = manuals_dir or DEFAULT_MANUALS_DIR
        self._clauses: dict[str, str] = {}

    def load_file(self, filename: str) -> dict[str, str]:
        """加载指定手册。文件不存在则抛出 ManualNotFoundError。"""
        path = self._dir / filename
        if not path.is_file():
            raise ManualNotFoundError(str(path))
        clauses = parse_clauses(path.read_text(encoding="utf-8"))
        self._clauses.update(clauses)
        return clauses

    def load_all(self) -> dict[str, str]:
        """加载目录下全部 markdown。目录不存在则失败关闭。"""
        if not self._dir.is_dir():
            raise ManualNotFoundError(str(self._dir))
        for path in sorted(self._dir.glob("*.md")):
            self.load_file(path.name)
        return dict(self._clauses)

    def get(self, clause_id: str) -> str | None:
        """按条款 id 取正文。"""
        return self._clauses.get(clause_id)

    def texts(self, clause_ids: tuple[str, ...]) -> dict[str, str]:
        """按引用顺序返回条款正文。"""
        out: dict[str, str] = {}
        for cid in clause_ids:
            text = self._clauses.get(cid)
            if text is not None:
                out[cid] = text
        return out


__all__ = [
    "DEFAULT_MANUALS_DIR",
    "ManualIndex",
    "ManualNotFoundError",
    "parse_clauses",
]
