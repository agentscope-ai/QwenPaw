from copaw.agents.vision_prepass import (
    build_vlm_prepass_prompt,
    format_vlm_prepass_context,
    normalize_vlm_prepass_output,
)


def test_build_prompt_is_free_form() -> None:
    prompt = build_vlm_prepass_prompt("read the chart", 2)
    assert "Describe" in prompt
    assert "Number of images: 2" in prompt
    assert "read the chart" in prompt


def test_build_prompt_single_image_no_count() -> None:
    prompt = build_vlm_prepass_prompt("describe it", 1)
    assert "Number of images" not in prompt


def test_normalize_vlm_output_passthrough() -> None:
    desc = "A cat on a keyboard. Text visible: Hello World."
    normalized = normalize_vlm_prepass_output(desc)
    assert normalized == desc


def test_normalize_vlm_output_trims_long() -> None:
    long_text = "x" * 600
    normalized = normalize_vlm_prepass_output(long_text)
    assert len(normalized) <= 500
    assert normalized.endswith("...")


def test_normalize_vlm_output_empty() -> None:
    assert normalize_vlm_prepass_output("") == ""
    assert normalize_vlm_prepass_output("   ") == ""


def test_format_vlm_prepass_context_readable() -> None:
    desc = "An invoice showing Total: 42 with a company logo."
    readable = format_vlm_prepass_context(
        "image",
        desc,
        user_text="check this invoice",
    )
    assert "[Image]" in readable
    assert "User text:" in readable
    assert "Description:" in readable
    assert "invoice" in readable


def test_format_vlm_prepass_context_audio() -> None:
    desc = "A person saying hello world."
    readable = format_vlm_prepass_context("audio", desc)
    assert "[Audio]" in readable
    assert "Transcript:" in readable


def test_format_vlm_prepass_context_empty() -> None:
    assert format_vlm_prepass_context("image", "") == ""
    assert format_vlm_prepass_context("image", "   ") == ""
