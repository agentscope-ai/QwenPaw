"""兼容各平台的路径链接检测，不把普通云盘占位文件视为目录链接。"""

from pathlib import Path
import stat


def is_link_or_junction(path: Path) -> bool:
    """使用 lstat 保留 Windows Python 3.11 的 junction 信息。"""
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", None) in {
        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003),
        getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
    }
