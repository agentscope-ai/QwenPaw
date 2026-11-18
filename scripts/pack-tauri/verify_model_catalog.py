# -*- coding: utf-8 -*-
"""Verify the bundled model catalog without importing runtime dependencies."""

import hashlib
import json
import sys
from pathlib import Path


def main() -> None:
    """Check the index and every referenced provider shard before packaging."""
    data_dir = Path(sys.argv[1]).resolve()
    index = json.loads((data_dir / f"index.json").read_text(encoding=f"utf-8"))
    for entry in index[f"providers"].values():
        shard = (data_dir / entry[f"path"]).resolve()
        if not shard.is_relative_to(data_dir):
            raise ValueError(f"Catalog shard escapes its directory: {shard}")
        digest = hashlib.sha256(shard.read_bytes()).hexdigest()
        if digest != entry[f"sha256"]:
            raise ValueError(f"Catalog shard checksum mismatch: {shard}")


if __name__ == f"__main__":
    main()
