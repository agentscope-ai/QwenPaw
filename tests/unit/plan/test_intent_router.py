# -*- coding: utf-8 -*-
from types import SimpleNamespace

from qwenpaw.plan.hints import should_skip_auto_continue, set_plan_auto_execute
from qwenpaw.plan.intent_router import PlanIntentRouter


def test_complex_ppt_imagegen_request_auto_routes_to_plan():
    route = PlanIntentRouter().route(
        "根据这个文档帮我生成一个ppt，大概25-30页，要求所有页面都通过 "
        "imagegen 来生成，最后通过 pptx 生成ppt。"
    )

    assert route is not None
    assert route.reason == "complex_task"
    assert "imagegen_ppt_pipeline" in route.matched


def test_single_image_request_does_not_auto_route_to_plan():
    route = PlanIntentRouter().route("我想画一张小猫的图片")

    assert route is None


def test_plan_auto_disabled_does_not_route():
    route = PlanIntentRouter(auto_enabled=False).route(
        "先分析文档，然后生成25页ppt，最后导出pptx"
    )

    assert route is None


def test_user_negative_plan_wording_does_not_route():
    route = PlanIntentRouter().route(
        "不用计划，直接根据文档生成25页ppt并导出pptx"
    )

    assert route is None


def test_auto_execute_does_not_skip_auto_continue_after_plan_mutation():
    notebook = SimpleNamespace(_plan_just_mutated=True)
    set_plan_auto_execute(notebook, enabled=True)

    assert should_skip_auto_continue(notebook) is False
    assert notebook._plan_just_mutated is False


def test_explicit_plan_still_skips_auto_continue_after_plan_mutation():
    notebook = SimpleNamespace(_plan_just_mutated=True)
    set_plan_auto_execute(notebook, enabled=False)

    assert should_skip_auto_continue(notebook) is True
    assert notebook._plan_just_mutated is False
