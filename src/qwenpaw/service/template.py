# -*- coding: utf-8 -*-
"""无凭据的实例配置模板。"""

import sys
from pathlib import Path


def example_config(platform=None):
    platform = platform or sys.platform
    windows = platform == "win32"
    root = "C:/ProgramData/QwenPaw" if windows else "/var/lib/qwenpaw"
    return {
        "python": sys.executable,
        "project_dir": str(Path.cwd().resolve()),
        "host": "127.0.0.1",
        "port": 18089,
        "timeout": 120,
        "working_dir": f"{root}/working",
        "secret_dir": f"{root}/secrets",
        "backup_dir": f"{root}/backups",
        "state_dir": f"{root}/run",
        "log_dir": f"{root}/logs" if windows else "/var/log/qwenpaw",
        "environment": {
            "QWENPAW_MULTI_USER_ENABLED": "true",
            "QWENPAW_STORAGE_MODE": "postgres",
            "QWENPAW_DATABASE_URL": "postgresql://qwenpaw:CHANGE_ME@127.0.0.1:5432/qwenpaw",
            "QWENPAW_DATABASE_SCHEMA": "qwenpaw",
            "QWENPAW_CUTOVER_VALIDATED_DOMAINS": "",
            "QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS": "",
            "QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS": "",
        },
    }
