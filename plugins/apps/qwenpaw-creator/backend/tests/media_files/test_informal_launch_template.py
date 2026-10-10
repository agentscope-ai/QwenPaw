# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Launch captions preserve expressive designs and optional preset support."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from domain.errors import ValidationError
from services.media_files import motion_design
from services.media_files import local_execution
from services.media_files import informal_launch_timing
from services.media_files.informal_launch_template import (
    compile_informal_launch_captions,
    informal_launch_caption_skill,
    informal_launch_copy_matches,
    informal_launch_frame_windows,
    informal_launch_screen_copy,
    informal_launch_uses_uploaded_bgm,
    normalize_informal_launch_html,
    render_informal_launch_caption,
)
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaInput,
    _edit_overlays,
    _motion_document_matches_text,
)
from services.media_files.motion_overlay import MotionDocumentProbe
from services.project_files.assets import AssetFileStore
from services.media_files.video_templates import (
    apply_video_template_to_project,
    get_video_template,
    list_video_templates,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    AudioCreation,
    EditCreation,
    ElementLocation,
    ElementOutput,
    ElementOutputRenderSource,
    IndexedFile,
    MotionGraphic,
    OverlayCreation,
    Project,
    R2VCreation,
    SourceAssetVersion,
    TimelineElement,
    TimelineSpan,
)
from services.runtime_files.models import ChangeOrigin, ReviewPolicy


def caption(text="正式登场\nTakes the Stage", **options):
    return TimelineElement(
        element_id="caption",
        span=TimelineSpan(start_tick=0, duration_tick=3000),
        creation=OverlayCreation(
            text=text,
            prompt=json.dumps({"template": "informal_launch", **options}),
        ),
        location=ElementLocation(x=0.25, y=0.5, width=0.34, height=0.26),
    )


def test_official_template_is_available_without_user_files():
    template = get_video_template("informal_launch")
    assert template.name == "非正式发布会"
    assert list_video_templates()[0] is template
    assert get_video_template("user:cat_launch_v1") is template
    assert "一次视频模型调用" in template.design_floor.opening


@pytest.mark.asyncio
@pytest.mark.parametrize("caption_style", ["varied", "uniform"])
async def test_r2v_timeline_uses_fixed_document_without_model_or_edit(
    tmp_path,
    monkeypatch,
    caption_style,
):
    services = CreatorFileServices.create(tmp_path)
    project = apply_video_template_to_project(
        Project.new(project_id="fixed-launch", name="固定字幕测试"),
        get_video_template("informal_launch"),
    )
    project.timelines.items["timeline:main"].elements_by_id[
        "caption"
    ] = caption(recipe="hero")
    services.projects.create(project)
    model = AsyncMock(
        side_effect=AssertionError(
            "Fixed template must not call a design model",
        ),
    )
    monkeypatch.setattr(motion_design, "_design_document", model)
    monkeypatch.setattr(motion_design.vlm_model, "chat_completion", model)
    result = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments={"captionStyle": caption_style},
        idempotency_key="fixed-caption",
    )
    assert result["designedCount"] == 1
    current = services.projects.read(project.project_id).project
    element = current.timelines.items["timeline:main"].elements_by_id[
        "caption"
    ]
    motion = element.creation.motion
    assert motion.format == "html_css" and motion.template_version == 4
    assert element.location.width == element.location.height == 1
    assert element.location.x == element.location.y == 0.5
    file = current.assets.files_by_id[motion.html_file_id]
    html = (
        services.projects.project_root(project.project_id) / file.relative_uri
    ).read_text()
    assert _motion_document_matches_text(html, element.creation.text)
    assert 'data-motion="slide"' in html
    assert 'class="group accent"' in html
    model.assert_not_called()
    second = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments={},
        idempotency_key="preserve-caption",
    )
    assert second["designedCount"] == 0
    assert second["textOverlays"][0]["status"] == "already_styled"


def test_collection_keeps_every_translation_and_escapes_copy():
    text = (
        "四款造型\nFour Looks\n米白针织\nCream Knit\n"
        "灰蓝围巾\nBlue-Grey Scarf\n浅灰外套\nGrey <Jacket>\n"
        "深紫领结\nPurple Bow Tie"
    )
    motion, location = render_informal_launch_caption(
        caption(text, recipe="look_labels"),
        ticks_per_second=1000,
        canvas_size=(1920, 1080),
        card_index=8,
        card_count=10,
    )
    assert motion.html.count('class="group label center"') == 4
    assert "&lt;Jacket&gt;" in motion.html and "<Jacket>" not in motion.html
    assert _motion_document_matches_text(motion.html, text)
    assert location.width == 1


def test_portrait_sizes_only_a_transparent_text_band():
    motion, location = render_informal_launch_caption(
        caption(recipe="hero"),
        ticks_per_second=1000,
        canvas_size=(1080, 1920),
        card_index=0,
        card_count=10,
    )
    assert location.width == 1 and location.height <= 0.4
    assert "background:transparent" in motion.html


@pytest.mark.parametrize(
    "options",
    [{"region": [0, 0, 100, 100]}, {"accent": "red;display:none"}],
)
def test_invalid_style_slots_fail_instead_of_falling_back(options):
    with pytest.raises(ValidationError):
        render_informal_launch_caption(
            caption(**options),
            ticks_per_second=1000,
            canvas_size=(1920, 1080),
            card_index=0,
            card_count=10,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("externalized", [False, True])
async def test_version_four_does_not_preserve_corrupt_css(
    tmp_path,
    monkeypatch,
    externalized,
):
    services = CreatorFileServices.create(tmp_path)
    project = apply_video_template_to_project(
        Project.new(project_id="corrupt-launch", name="转义回归"),
        get_video_template("informal_launch"),
    )
    overlay = caption(recipe="hero")
    motion, location = render_informal_launch_caption(
        overlay,
        ticks_per_second=1000,
        canvas_size=(1280, 720),
        card_index=0,
        card_count=1,
    )
    motion.html = motion.html.replace("\n", "\\n")
    overlay.creation.motion = motion
    overlay.location = location
    project.timelines.items["timeline:main"].elements_by_id[
        "caption"
    ] = overlay
    services.projects.create(project)
    if externalized:
        stored, indexed = motion_design._externalized_motion(
            motion,
            AssetFileStore(services.projects.project_root(project.project_id)),
        )
        snapshot = services.projects.read(project.project_id)
        candidate = snapshot.project.model_dump(mode="json")
        candidate["assets"]["files_by_id"][
            indexed.file_id
        ] = indexed.model_dump(mode="json")
        candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
            "caption"
        ]["creation"]["motion"] = stored.model_dump(mode="json")
        services.commits.commit(
            base=snapshot,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id="corrupt-fixture",
        )
    model = AsyncMock(
        side_effect=AssertionError("No model needed for fixed captions"),
    )
    monkeypatch.setattr(motion_design.vlm_model, "chat_completion", model)
    result = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments={},
        idempotency_key="repair-version-four",
    )
    assert result["designedCount"] == 1
    current = services.projects.read(project.project_id).project
    fixed = (
        current.timelines.items["timeline:main"]
        .elements_by_id["caption"]
        .creation.motion
    )
    indexed = current.assets.files_by_id[fixed.html_file_id]
    html = (
        services.projects.project_root(project.project_id)
        / indexed.relative_uri
    ).read_text()
    assert "\\n" not in html
    assert "\n@keyframes" in html
    model.assert_not_called()


@pytest.mark.parametrize("official", [False, True])
def test_compose_repairs_only_official_template_encoding(
    official,
):
    project = Project.new(project_id="compose-launch", name="合成入口")
    if official:
        project = apply_video_template_to_project(
            project,
            get_video_template("informal_launch"),
        )
    timeline = project.timelines.items["timeline:main"]
    overlay = caption(recipe="hero")
    motion, location = render_informal_launch_caption(
        overlay,
        ticks_per_second=1000,
        canvas_size=(1280, 720),
        card_index=0,
        card_count=1,
    )
    motion.html = motion.html.replace("\n", "\\n")
    overlay.creation.motion = motion
    overlay.location = location
    timeline.elements_by_id["caption"] = overlay
    video = TimelineElement(
        element_id="video",
        span=TimelineSpan(start_tick=0, duration_tick=3000),
        creation=R2VCreation(),
        location=ElementLocation(x=0.5, y=0.5, width=1, height=1),
    )
    frozen = _edit_overlays(project, timeline, video)[0]
    if official:
        assert frozen["caption_template"] == "informal_launch"
        assert "\\n" not in frozen["motion"]["html"]
        assert "\n@keyframes" in frozen["motion"]["html"]
        assert frozen["location"]["width"] == frozen["location"]["height"] == 1
    else:
        assert "caption_template" not in frozen
        assert frozen["motion"]["html"] == motion.html


@pytest.mark.parametrize(
    "failure",
    ["copy", "probe", "capture", "composite", "missing"],
)
def test_official_caption_never_silently_falls_back(
    tmp_path,
    monkeypatch,
    failure,
):
    overlay = caption(recipe="hero")
    motion, location = render_informal_launch_caption(
        overlay,
        ticks_per_second=1000,
        canvas_size=(1280, 720),
        card_index=0,
        card_count=1,
    )
    segment = tmp_path / "segment.mp4"
    segment.write_bytes(b"original")
    item = LocalMediaInput(
        version_id="video",
        file_id=None,
        checksum="0" * 64,
        path=segment,
        media_type="video/mp4",
        source_ref="element:video",
        duration_seconds=3,
        overlays=(
            {
                "kind": "interview_summary",
                "caption_template": "informal_launch",
                "element_id": "caption",
                "text": overlay.creation.text,
                "motion": None
                if failure == "missing"
                else {
                    "html": "wrong copy" if failure == "copy" else motion.html,
                },
                "location": location.model_dump(mode="json"),
                "duration": 3,
            },
        ),
    )
    monkeypatch.setattr(
        FfmpegLocalMediaRunner,
        "_probe_video_size",
        lambda *a: (1280, 720),
    )
    monkeypatch.setattr(
        local_execution,
        "probe_motion_document",
        lambda *a, **kw: MotionDocumentProbe(
            ok=failure != "probe",
            error="probe rejected",
            edge_contact=0,
            text_occlusion=0,
        ),
    )
    monkeypatch.setattr(
        local_execution,
        "prepare_motion_layer",
        lambda **kw: SimpleNamespace(
            layer=None if failure == "capture" else object(),
            error="capture rejected",
        ),
    )
    monkeypatch.setattr(
        local_execution,
        "composite_motion_layers",
        lambda **kw: SimpleNamespace(
            success=False,
            error="composite rejected",
        ),
    )

    def no_fallback(*args, **kwargs):
        raise AssertionError(
            "Official captions must not enter generic fallback",
        )

    monkeypatch.setattr(
        local_execution,
        "render_caption_template",
        no_fallback,
    )
    monkeypatch.setattr(
        local_execution,
        "render_interview_summary_overlay",
        no_fallback,
    )
    with pytest.raises(ValidationError, match="未替换为基础字幕"):
        FfmpegLocalMediaRunner(executable="ffmpeg")._apply_overlay(
            item,
            segment,
        )
    assert segment.read_bytes() == b"original"


CUSTOM_LETTERING = """<!doctype html><html><head><style>
html,body{margin:0;width:100%;height:100%;background:transparent}
.caption{position:absolute;left:9%;top:18%;color:#663399}
.title{font:700 6vw/1.25 'PingFang SC',sans-serif;margin:0;
 -webkit-text-stroke:.04vw #332244;letter-spacing:.04em}
.title span{display:inline-block;animation:boing .7s both}
.title span:nth-child(2){animation-delay:.1s}
.english{font:400 2.5vw/1.4 Arial,sans-serif;margin-top:1vw}
@keyframes boing{from{opacity:.4;transform:scale(.85) rotate(-4deg)}
 to{opacity:1;transform:scale(1) rotate(0deg)}}
</style></head><body><div class="caption"><h2 class="title">
<span>正式</span><span>登场</span></h2>
<div class="english">Takes the Stage</div></div></body></html>"""


def launch_with_selected_video():
    project = apply_video_template_to_project(
        Project.new(project_id="generated-launch", name="自动花字"),
        get_video_template("informal_launch"),
    )
    stamp = datetime.now(UTC)
    project.assets.files_by_id["file-video"] = IndexedFile(
        file_id="file-video",
        kind="artifact_payload",
        relative_uri="assets/artifacts/video.mp4",
        sha256="0" * 64,
        size_bytes=1,
        media_type="video/mp4",
        created_at=stamp,
    )
    for version_id in ("older-video", "selected-video"):
        project.assets.artifact_versions_by_id[version_id] = ArtifactVersion(
            version_id=version_id,
            slot_id="video-slot",
            kind="element_video",
            owner_ref="element:video",
            name=version_id,
            file_id="file-video",
            checksum="0" * 64,
            based_on_generation=0,
            created_at=stamp,
        )
    project.assets.artifact_slots_by_id["video-slot"] = ArtifactSlot(
        slot_id="video-slot",
        kind="element_video",
        owner_ref="element:video",
        version_ids=["older-video", "selected-video"],
        selected_version_id="selected-video",
    )
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id["video"] = TimelineElement(
        element_id="video",
        span=TimelineSpan(start_tick=0, duration_tick=30000),
        location=ElementLocation(x=0.5, y=0.5, width=1, height=1),
        creation=R2VCreation(),
        outputs={"main": ElementOutput(slot_id="video-slot")},
        render_source=ElementOutputRenderSource(
            element_id="video",
            output_name="main",
        ),
    )
    timeline.elements_by_id["caption"] = caption()
    return project


def test_shot_ranges_accept_variable_count_and_reject_gaps():
    parse = informal_launch_timing.planned_shot_ranges
    assert parse("镜头 1｜0–4s\n第2镜（4–9 秒）\n镜头3（9–30秒）", 30) == [
        (0, 4),
        (4, 9),
        (9, 30),
    ]
    assert not parse("镜头1（0–4秒）\n镜头2（5–30秒）", 30)


@pytest.mark.asyncio
async def test_new_caption_design_uses_and_commits_actual_cut_timing(
    tmp_path,
    monkeypatch,
):
    project = launch_with_selected_video()
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id[
        "video"
    ].creation.narrative = "镜头1（0–3秒）亮相\n镜头2（3–30秒）展示"
    timeline.elements_by_id["caption"].creation.prompt = "按实片做花字"
    services = CreatorFileServices.create(tmp_path)
    services.projects.create(project)
    frames = []

    def keyframe(_root, **kwargs):
        frames.append(kwargs["timestamp_seconds"])
        return SimpleNamespace(path=tmp_path / f"{len(frames)}.jpg")

    for module in (motion_design, informal_launch_timing):
        monkeypatch.setattr(
            module,
            "verified_indexed_path",
            lambda *_: tmp_path / "video.mp4",
        )
    monkeypatch.setattr(
        informal_launch_timing,
        "detect_hard_cuts",
        lambda *_: [4.2],
    )
    monkeypatch.setattr(motion_design, "materialize_keyframe", keyframe)
    designer = AsyncMock(
        return_value=(
            MotionGraphic(html=CUSTOM_LETTERING, loop=False),
            ElementLocation(x=0.5, y=0.5, width=1, height=1),
            "实片花字",
        ),
    )
    monkeypatch.setattr(motion_design, "_design_document", designer)
    result = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments={},
        idempotency_key="actual-cuts",
    )
    assert result["captionTiming"]["sourceVersionId"] == "selected-video"
    assert frames == pytest.approx([0.504, 1.596, 2.604, 3.696])
    context = json.loads(designer.call_args.kwargs["task_text"])
    assert context["actualTimeRangeSeconds"] == [0, 4.2]
    current = services.projects.read(project.project_id).project
    assert (
        current.timelines.items["timeline:main"]
        .elements_by_id["caption"]
        .span.duration_tick
        == 4200
    )


def test_cut_alignment_keeps_authored_timing_and_declines_ambiguous_cuts(
    tmp_path,
    monkeypatch,
):
    project = launch_with_selected_video()
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id[
        "video"
    ].creation.narrative = "镜头1（0–3秒）亮相\n镜头2（3–30秒）展示"
    overlay = timeline.elements_by_id["caption"]
    monkeypatch.setattr(
        informal_launch_timing,
        "verified_indexed_path",
        lambda *_: tmp_path / "video.mp4",
    )
    monkeypatch.setattr(
        informal_launch_timing,
        "detect_hard_cuts",
        lambda *_: [4.2, 12],
    )
    spans, report = informal_launch_timing.align_launch_caption_spans(
        project,
        timeline,
        [overlay],
        tmp_path,
        "ffmpeg",
    )
    assert not spans and report["status"] == "unverified"
    overlay.span = TimelineSpan(start_tick=1000, duration_tick=2000)
    spans, report = informal_launch_timing.align_launch_caption_spans(
        project,
        timeline,
        [overlay],
        tmp_path,
        "ffmpeg",
    )
    assert not spans and report["status"] == "kept_authored_timing"
    overlay.span = TimelineSpan(start_tick=0, duration_tick=3000)
    overlay.creation.motion = MotionGraphic(html=CUSTOM_LETTERING)
    spans, report = informal_launch_timing.align_launch_caption_spans(
        project,
        timeline,
        [overlay],
        tmp_path,
        "ffmpeg",
    )
    assert not spans and report["status"] == "kept_authored_timing"


def test_only_selected_launch_bgm_replaces_native_audio():
    project = launch_with_selected_video()
    timeline = project.timelines.items["timeline:main"]
    project.assets.source_versions_by_id["music"] = SourceAssetVersion(
        version_id="music",
        logical_asset_id="music",
        name="用户音乐",
        file_id="file-video",
        checksum="0" * 64,
        media_kind="audio",
        media_type="audio/mpeg",
        created_at=datetime.now(UTC),
    )
    bgm = TimelineElement(
        element_id="bgm",
        span=TimelineSpan(start_tick=0, duration_tick=30000),
        creation=AudioCreation(source_asset_version_id="music", role="bgm"),
    )
    timeline.elements_by_id["bgm"] = bgm
    assert informal_launch_uses_uploaded_bgm(project, timeline)
    bgm.enabled = False
    assert not informal_launch_uses_uploaded_bgm(project, timeline)
    bgm.enabled = True
    timeline.edit_plan = None
    assert not informal_launch_uses_uploaded_bgm(project, timeline)


@pytest.mark.parametrize("replace_native", [False, True])
def test_template_music_replacement_omits_native_audio_from_mix(
    tmp_path,
    monkeypatch,
    replace_native,
):
    output = tmp_path / "output.mp4"
    output.write_bytes(b"premix")
    calls = []
    monkeypatch.setattr(
        FfmpegLocalMediaRunner,
        "_probe_has_audio",
        lambda *_: True,
    )
    monkeypatch.setattr(
        FfmpegLocalMediaRunner,
        "_run",
        lambda self, args, **kwargs: calls.append(args),
    )
    spec = local_execution.LocalMediaExecutionSpec(
        command=local_execution.CreatorCommandType.COMPOSE_FINAL_VIDEO,
        target_ref="timeline:main",
        task_id="test",
        work_dir=tmp_path,
        output_path=output,
        inputs=(),
        transitions=(),
        audio_plan="",
        expected_duration_seconds=30,
        canvas_size=(1280, 720),
        audio_tracks=(
            {
                "path": tmp_path / "music.mp3",
                "role": "bgm",
                "max_duration_seconds": 30,
            },
        ),
        replace_native_audio=replace_native,
    )
    FfmpegLocalMediaRunner(executable="ffmpeg")._mix_audio_tracks(spec)
    filters = calls[0][calls[0].index("-filter_complex") + 1]
    assert ("[0:a]" in filters) is not replace_native
    assert ("sidechaincompress" in filters) is not replace_native
    assert "[1:a]" in filters


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    ["按亮相动作做灵动花字", '{"template":"informal_launch","mode":"custom"}'],
)
async def test_lettering_uses_template_skill_and_selected_r2v_frames(
    tmp_path,
    monkeypatch,
    prompt,
):
    project = launch_with_selected_video()
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id["caption"].creation.prompt = prompt
    timeline.elements_by_id["caption"].creation.text = "正式登场 / Takes the Stage"
    services = CreatorFileServices.create(tmp_path)
    services.projects.create(project)
    frames = []

    def keyframe(_root, **kwargs):
        frames.append(kwargs)
        return SimpleNamespace(path=tmp_path / f"frame-{len(frames)}.jpg")

    monkeypatch.setattr(motion_design, "materialize_keyframe", keyframe)
    monkeypatch.setattr(
        motion_design,
        "verified_indexed_path",
        lambda *_: tmp_path / "video.mp4",
    )
    designer = AsyncMock(
        return_value=(
            MotionGraphic(html=CUSTOM_LETTERING, loop=False),
            ElementLocation(x=0.5, y=0.5, width=1, height=1),
            "按实片设计的错峰花字",
        ),
    )
    monkeypatch.setattr(motion_design, "_design_document", designer)
    result = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments={"captionStyle": "uniform"},
        idempotency_key="generate-lettering",
    )
    assert result["designedCount"] == 1
    assert [frame["timestamp_seconds"] for frame in frames] == pytest.approx(
        [0.36, 1.14, 1.86, 2.64],
    )
    assert {frame["source_identity"] for frame in frames} == {"selected-video"}
    arguments = designer.call_args.kwargs
    assert len(arguments["frame_paths"]) == 4
    assert arguments["system_prompt"] == informal_launch_caption_skill()
    assert arguments["full_canvas_overlay"] is True
    assert json.loads(arguments["task_text"])["designIntent"] == prompt
    assert json.loads(arguments["task_text"])["screenCopy"] == (
        "正式登场\nTakes the Stage"
    )
    current = services.projects.read(project.project_id).project
    motion = (
        current.timelines.items["timeline:main"]
        .elements_by_id["caption"]
        .creation.motion
    )
    indexed = current.assets.files_by_id[motion.html_file_id]
    assert (
        services.projects.project_root(project.project_id)
        / indexed.relative_uri
    ).read_text() == CUSTOM_LETTERING


def test_caption_frames_follow_trimmed_edit_timing_and_selected_version():
    project = launch_with_selected_video()
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id["video"].enabled = False
    timeline.elements_by_id["edit"] = TimelineElement(
        element_id="edit",
        span=TimelineSpan(start_tick=1000, duration_tick=5000),
        location=ElementLocation(x=0.5, y=0.5, width=1, height=1),
        creation=EditCreation(),
        render_source=ElementOutputRenderSource(
            element_id="video",
            output_name="main",
            source_in_tick=8000,
            source_out_tick=18000,
            playback_rate=2,
        ),
    )
    overlay = timeline.elements_by_id["caption"]
    overlay.span = TimelineSpan(start_tick=2000, duration_tick=3000)
    assert informal_launch_frame_windows(project, timeline, overlay) == [
        ("selected-video", 10, 16),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["text", "prompt", "motion", "location", "span", "source", "trim", "name"],
)
async def test_pending_caption_design_preserves_newer_edits(
    tmp_path,
    monkeypatch,
    change,
):
    project = launch_with_selected_video()
    services = CreatorFileServices.create(tmp_path)
    services.projects.create(project)
    monkeypatch.setattr(
        motion_design,
        "materialize_keyframe",
        lambda *_args, **_kwargs: SimpleNamespace(path=tmp_path / "frame.jpg"),
    )
    monkeypatch.setattr(
        motion_design,
        "verified_indexed_path",
        lambda *_: tmp_path / "video.mp4",
    )
    newer = None

    async def finish_after_edit(**_kwargs):
        nonlocal newer
        snapshot = services.projects.read(project.project_id)
        candidate = snapshot.project.model_dump(mode="json")
        elements = candidate["timelines"]["items"]["timeline:main"][
            "elements_by_id"
        ]
        overlay = elements["caption"]
        if change in {"text", "prompt"}:
            overlay["creation"][change] = "后续人工修改"
        elif change == "motion":
            overlay["creation"]["motion"] = MotionGraphic(
                html=CUSTOM_LETTERING.replace("#663399", "#00aabb"),
            ).model_dump(mode="json")
        elif change == "location":
            overlay["location"]["x"] = 0.6
        elif change == "span":
            overlay["span"]["duration_tick"] = 2500
        elif change == "source":
            candidate["assets"]["artifact_slots_by_id"]["video-slot"][
                "selected_version_id"
            ] = "older-video"
        elif change == "trim":
            elements["video"]["render_source"]["source_in_tick"] = 1000
        else:
            candidate["name"] = "只修改项目名称"
        newer = services.commits.commit(
            base=snapshot,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id="newer-edit",
        ).snapshot
        return (
            MotionGraphic(html=CUSTOM_LETTERING, loop=False),
            ElementLocation(x=0.5, y=0.5, width=1, height=1),
            "旧输入的花字设计",
        )

    monkeypatch.setattr(
        motion_design,
        "_design_document",
        finish_after_edit,
    )
    operation = motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments={},
        idempotency_key="pending-design",
    )
    if change == "name":
        result = await operation
        assert result["designedCount"] == 1
        assert services.projects.read(project.project_id).project.name == (
            "只修改项目名称"
        )
    else:
        with pytest.raises(ValidationError, match="字幕设计期间"):
            await operation
        current = services.projects.read(project.project_id)
        assert current.generation == newer.generation
        assert current.project == newer.project


@pytest.mark.asyncio
async def test_missing_footage_does_not_fill_a_preset(
    tmp_path,
):
    project = launch_with_selected_video()
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id["video"].render_source = None
    services = CreatorFileServices.create(tmp_path)
    services.projects.create(project)
    with pytest.raises(ValidationError, match="已生成并选中"):
        await motion_design.design_motion_overlays(
            services,
            project_id=project.project_id,
            target_ref="timeline:main",
            arguments={},
            idempotency_key="no-footage",
        )
    with pytest.raises(ValidationError, match="不会自动改用预设"):
        compile_informal_launch_captions(timeline, (1920, 1080))


def test_full_canvas_preserves_geometry_and_alpha():
    html = CUSTOM_LETTERING.replace(
        "animation-delay:.1s",
        "animation-delay:.1s;opacity:0",
    )
    motion, _, _ = motion_design._validated_design(
        {
            "html": html,
            "concept": "竖屏花字",
            "location": {"x": 0.5, "y": 0.5, "width": 1, "height": 1},
        },
        required_text="正式登场\nTakes the Stage",
        canvas_size=(1080, 1920),
        full_canvas_overlay=True,
    )
    assert motion.html == html


@pytest.mark.asyncio
async def test_generated_lettering_retries_occlusion_before_composition(
    monkeypatch,
):
    answer = json.dumps(
        {
            "html": CUSTOM_LETTERING,
            "concept": "错峰标题",
            "location": {"x": 0.5, "y": 0.5, "width": 1, "height": 1},
        },
    )
    model = AsyncMock(return_value=answer)
    monkeypatch.setattr(motion_design.vlm_model, "chat_completion", model)
    probes = iter(
        [
            MotionDocumentProbe(ok=True, text_occlusion=0.12),
            MotionDocumentProbe(ok=True, text_occlusion=0.0),
        ],
    )
    monkeypatch.setattr(
        motion_design,
        "probe_motion_document",
        lambda *_args, **_kwargs: next(probes),
    )
    motion, _, _ = await motion_design._design_document(
        system_prompt="模板专属设计",
        task_text="当前字幕",
        frame_paths=[],
        canvas_size=(1920, 1080),
        required_text="正式登场\nTakes the Stage",
        full_canvas_overlay=True,
    )
    assert model.call_count == 2
    assert "遮挡" in model.call_args.args[0][-1]["text"]
    assert motion.html == CUSTOM_LETTERING


def test_template_rejects_unrequested_stamp_copy():
    with pytest.raises(ValidationError, match="额外字样"):
        motion_design._validated_design(
            {
                "html": CUSTOM_LETTERING.replace(
                    "</body>",
                    "<div>OK</div></body>",
                ),
                "concept": "额外图章",
                "location": {"x": 0.5, "y": 0.5, "width": 1, "height": 1},
            },
            required_text="正式登场\nTakes the Stage",
            full_canvas_overlay=True,
        )


@pytest.mark.parametrize(
    ("text", "visible", "accepted"),
    [
        (
            "布丁 正式登场 / Pudding Has Arrived",
            "布丁正式登场<br>Pudding Has Arrived",
            True,
        ),
        (
            "布丁 正式登场 / Pudding Has Arrived",
            "布丁正式登场 / Pudding Has Arrived",
            True,
        ),
        (
            "碎花 / 日常 / Floral Bib\n领结 / 晚宴 / Bow Tie",
            "碎花<br>日常 / Floral Bib<br>领结<br>晚宴<br>Bow Tie",
            True,
        ),
        ("24/7 / AC/DC", "24/7<br>AC/DC", True),
        ("24/7 / AC/DC", "247<br>ACDC", False),
        ("原装大眼睛 / Factory Eyes", "原装大眼睛<br>Factory", False),
        ("原装大眼睛 / Factory Eyes", "原装大眼睛<br>Factory Eyes<div>OK</div>", False),
        (
            "原装大眼睛 / Factory Eyes",
            "原装大眼睛<br>Factory Eyes<div>原装大眼睛</div>",
            False,
        ),
        ("原装大眼睛 / Factory Eyes", "Factory Eyes<br>原装大眼睛", False),
        ("功能，正常 / Working as Intended", "功能正常<br>Working as Intended", False),
        ("主题 / Launch", "主题 / / Launch", False),
    ],
)
def test_launch_copy_allows_only_authored_group_separators(
    text,
    visible,
    accepted,
):
    document = f"<!doctype html><html><body>{visible}</body></html>"
    assert informal_launch_copy_matches(document, text) is accepted


def test_launch_separator_normalization_preserves_literal_slashes():
    assert informal_launch_screen_copy("全天 24/7 / AC/DC\n原装 / Original") == (
        "全天 24/7\nAC/DC\n原装\nOriginal"
    )


def test_launch_multilingual_layout_passes_generation_copy_gate():
    motion, _, _ = motion_design._validated_design(
        {
            "html": CUSTOM_LETTERING,
            "concept": "中英文分行花字",
            "location": {"x": 0.5, "y": 0.5, "width": 1, "height": 1},
        },
        required_text="正式登场 / Takes the Stage",
        canvas_size=(1920, 1080),
        full_canvas_overlay=True,
    )
    assert motion.html == CUSTOM_LETTERING


@pytest.mark.asyncio
@pytest.mark.parametrize("externalized", [False, True])
@pytest.mark.parametrize("separator", ["\n", " / "])
async def test_custom_lettering_survives_design_and_compose(
    tmp_path,
    monkeypatch,
    externalized,
    separator,
):
    services = CreatorFileServices.create(tmp_path)
    project = apply_video_template_to_project(
        Project.new(project_id="custom-launch", name="自定义花字"),
        get_video_template("informal_launch"),
    )
    overlay = caption(
        text=f"正式登场{separator}Takes the Stage",
        mode="custom",
        recipe="not-a-preset",
    )
    overlay.location = ElementLocation(x=0.5, y=0.5, width=1, height=1)
    motion = MotionGraphic(html=CUSTOM_LETTERING, loop=False, fps=30)
    project_root = services.projects.project_root(project.project_id)
    overlay.creation.motion = motion
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id["caption"] = overlay
    services.projects.create(project)
    if externalized:
        motion, indexed = motion_design._externalized_motion(
            motion,
            AssetFileStore(project_root),
        )
        project.assets.files_by_id[indexed.file_id] = indexed
        overlay.creation.motion = motion
        services.commits.commit(
            base=services.projects.read(project.project_id),
            candidate=project.model_dump(mode="json"),
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id="custom-fixture",
        )
    model = AsyncMock(
        side_effect=AssertionError("Do not redesign custom text"),
    )
    monkeypatch.setattr(motion_design, "_design_document", model)
    result = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        # Even an explicit style request must not flatten existing artwork.
        arguments={"captionStyle": "uniform", "elementIds": ["caption"]},
        idempotency_key="preserve-custom-lettering",
    )
    assert result["designedCount"] == 0
    assert result["textOverlays"][0]["status"] == "already_styled"
    current = services.projects.read(project.project_id).project
    timeline = current.timelines.items["timeline:main"]
    assert timeline.elements_by_id["caption"].creation.motion == motion
    video = TimelineElement(
        element_id="video",
        span=TimelineSpan(start_tick=0, duration_tick=3000),
        creation=R2VCreation(),
        location=ElementLocation(x=0.5, y=0.5, width=1, height=1),
    )
    frozen = _edit_overlays(current, timeline, video)[0]
    materialized = local_execution._materialized_overlay(
        current,
        AssetFileStore(project_root),
        frozen,
    )
    assert materialized["motion"]["html"] == CUSTOM_LETTERING
    assert informal_launch_copy_matches(
        materialized["motion"]["html"],
        materialized["text"],
    )
    assert materialized["location"] == overlay.location.model_dump(mode="json")
    model.assert_not_called()


def test_encoding_repair_preserves_css_string_escapes():
    html = CUSTOM_LETTERING.replace("\n", r"\n")
    html = html.replace("</style>", r'.literal::before{content:"\\n"}</style>')
    repaired = normalize_informal_launch_html(html)
    assert "\n@keyframes boing" in repaired
    assert r'content:"\\n"' in repaired
    assert "rotate(-4deg)" in repaired
    assert "-webkit-text-stroke:.04vw" in repaired


def test_custom_request_without_document_does_not_become_a_preset():
    with pytest.raises(ValidationError, match="不会自动改用预设"):
        render_informal_launch_caption(
            caption(mode="custom"),
            ticks_per_second=1000,
            canvas_size=(1920, 1080),
            card_index=0,
            card_count=1,
        )


def test_collection_delay_and_top_center_use_template_slots():
    collection = caption(
        "两款造型\nTwo looks\n米白围巾\nCream scarf\n灰蓝卫衣\nSlate hoodie",
        recipe="look_labels",
        label_delay=1.5,
        label_stagger=0.1,
    )
    collection.span.duration_tick = 5500
    motion, _ = render_informal_launch_caption(
        collection,
        ticks_per_second=1000,
        canvas_size=(1920, 1080),
        card_index=0,
        card_count=1,
    )
    assert "--delay:1.5s" in motion.html and "--delay:1.6s" in motion.html
    motion, _ = render_informal_launch_caption(
        caption(recipe="detail", layout="top_center"),
        ticks_per_second=1000,
        canvas_size=(1920, 1080),
        card_index=0,
        card_count=1,
    )
    assert "--align:center" in motion.html and "--x:34%" in motion.html
