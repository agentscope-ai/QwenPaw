"""Original inherited assertions through the actual bundled official factory."""  # noqa: E501

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def official_onebot_proxy(tmp_path):
    from qwenpaw.__version__ import __version__
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.plugins.official_channels import bundled_channel_source
    from qwenpaw.runtime.runtime import Runtime

    with bundled_channel_source("onebot") as source:
        description = describe_channel(
            source,
            PluginManifest.from_dict(
                json.loads((source / "plugin.json").read_bytes())
            ),
        )

        def construct(config, **kwargs):
            return description.create_proxy(
                Runtime.run,
                config,
                python_executable=sys.executable,
                support_root=ROOT / "src",
                instance_id="onebot-original-contract",
                generation=1,
                qwenpaw_version=__version__,
                workspace_dir=tmp_path / "workspace",
                **kwargs,
            )

        yield construct
