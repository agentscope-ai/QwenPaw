# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import io

from PIL import Image

from services import object_grounding


def _png_bytes(size=(100, 200), color="white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color=color).save(output, format="PNG")
    return output.getvalue()


def test_parse_object_grounding_maps_aliases_and_rejects_bad_boxes():
    detections = object_grounding.parse_object_grounding(
        """```json
        {"objects":[
          {"label":"car","bbox_2d":[100,200,900,800]},
          {"name":"cat","bounding_box":[0,0,500,1000]},
          {"name":"invalid","bbox":[900,0,100,1000]},
          {"name":"outside","bbox":[0,0,1001,1000]}
        ]}
        ```""",
        80,
        40,
    )

    assert [d["label"] for d in detections] == ["car", "cat"]
    assert detections[0]["bbox_normalized"] == [100, 200, 900, 800]
    assert detections[0]["bbox_pixel"] == [8, 8, 72, 32]
    assert detections[1]["bbox_pixel"] == [0, 0, 40, 40]


def test_parse_object_grounding_supports_ref_box_fallback():
    detections = object_grounding.parse_object_grounding(
        "<ref>red car</ref><box>(10, 20), (500, 600)</box>",
        1000,
        500,
    )

    assert detections[0]["label"] == "red car"
    assert detections[0]["bbox_pixel"] == [10, 10, 500, 300]


def test_render_object_grounding_annotation_returns_source_sized_png():
    annotated = object_grounding.render_object_grounding_annotation(
        _png_bytes(),
        [
            {
                "label": "car",
                "bbox_normalized": [100, 100, 900, 900],
                "bbox_pixel": [10, 20, 90, 180],
            },
        ],
    )

    with Image.open(io.BytesIO(annotated)) as image:
        assert image.format == "PNG"
        assert image.size == (100, 200)
        assert image.getpixel((10, 20)) != (255, 255, 255)


def test_ground_image_objects_uses_creator_vlm_and_returns_raw_response(
    tmp_path,
    monkeypatch,
):
    captured = {}
    url = "/generated/projects/project-1/task-work/request-1/input.png"
    image_path = tmp_path / "project-1/runtime/task-work/request-1/input.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(_png_bytes())
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))

    async def fake_chat_completion(content, **kwargs):
        captured["content"] = content
        captured["kwargs"] = kwargs
        return '[{"label":"person","bbox_2d":[100,100,800,900]}]'

    vm, mc = object_grounding.vlm_model, object_grounding.model_config
    monkeypatch.setattr(vm, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(mc, "get_vlm_model_name", lambda: "qwen-test-vl")

    result = asyncio.run(
        object_grounding.ground_image_objects(_png_bytes(), url, "all people"),
    )

    assert captured["content"][0] == {
        "type": "image_url",
        "image_url": {"url": url},
    }
    assert captured["kwargs"]["temperature"] == 0.0
    assert result["model"] == "qwen-test-vl"
    assert result["imageSize"] == {"width": 100, "height": 200}
    assert result["detections"][0]["bbox_pixel"] == [10, 20, 80, 180]
    assert result["rawResponse"].startswith("[")
