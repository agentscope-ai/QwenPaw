import json

from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultBlock
from qwenpaw.loop.gates import StopAction
from qwenpaw.agents.file_delivery_guard import FileDeliveryGuard, requested_file_types
import pytest


@pytest.mark.parametrize(
    "text,expected",
    [
        ("生成一份PDF报告并发送给我", {"application/pdf"}),
        (
            "帮我制作PPT演示文稿",
            {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            },
        ),
        (
            "帮我生成Word文档",
            {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ),
        (
            "制作Excel表格",
            {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        ),
        ("只要海报文案，不要生成图片", set()),
        ("解释这份PDF", set()),
        ("如何生成PDF报告", set()),
        (
            "把PDF转换成PPT",
            {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            },
        ),
        ("用Word内容生成PDF报告", {"application/pdf"}),
        ("修改这张图片的背景", {"image/"}),
    ],
)
def test_only_actual_file_generation_requests_require_delivery(text, expected):
    assert requested_file_types(text) == expected


def test_text_or_wrong_file_cannot_complete_pdf_request():
    guard = FileDeliveryGuard({"application/pdf"})
    final = Msg(name="assistant", role="assistant", content=[TextBlock(text="PDF已生成")])
    assert guard.check(final).action == StopAction.INTERRUPT_AND_CONTINUE
    for state, mime in [("error", "application/pdf"), ("success", "image/png")]:
        guard.observe(
            [
                Msg(
                    name="tool",
                    role="assistant",
                    content=[
                        ToolResultBlock(
                            id="send",
                            name="send_file_to_user",
                            state=state,
                            output=[
                                TextBlock(
                                    text=json.dumps(
                                        [
                                            {
                                                "type": "data",
                                                "source": {"media_type": mime},
                                            }
                                        ]
                                    )
                                )
                            ],
                        )
                    ],
                )
            ]
        )
    assert not guard.delivered
    guard.observe(
        [
            Msg(
                name="tool",
                role="assistant",
                content=[
                    ToolCallBlock(id="pdf", name="send_file_to_user", input="{}"),
                    ToolResultBlock(
                        id="pdf",
                        name="send_file_to_user",
                        state="success",
                        output=[
                            TextBlock(
                                text=json.dumps(
                                    [
                                        {
                                            "type": "data",
                                            "source": {"media_type": "application/pdf"},
                                        }
                                    ]
                                )
                            )
                        ],
                    ),
                ],
            )
        ]
    )
    guard.observe([])
    assert guard.check(final).action == StopAction.BYPASS


def test_failed_generation_has_honest_finite_terminal_response():
    guard = FileDeliveryGuard({"application/pdf"})
    final = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(text="报告已生成 https://invented.example/report.pdf")],
    )
    guard.check(final)
    guard.check(final)
    result = guard.check(final)
    assert result.action == StopAction.TERMINATE
    assert "未完成" in result.final_message.get_text_content()
    assert "invented.example" not in result.final_message.get_text_content()


def test_permanent_child_authorization_failure_ends_delivery_retries():
    guard = FileDeliveryGuard(requested_file_types("生成 PPT"))
    error = ToolResultBlock(
        id="spawn", name="spawn_subagent", state="error",
        output=[TextBlock(text="1. ERROR: 子任务未获授权（HTTP 401）。")],
    )
    guard.observe([Msg(name="tool", role="assistant", content=[error])])
    result = guard.check(Msg(name="assistant", role="assistant", content=[TextBlock(text="准备重试")]))
    assert result.action == StopAction.TERMINATE
    assert result.reason == "subtask_authorization_failed"
    assert "文件尚未交付" in result.final_message.get_text_content()


@pytest.mark.parametrize(
    "text,action",
    [
        ("请确认大纲和视觉风格，批准后我再生成PPT。", StopAction.BYPASS),
        ("请提供招标文件和投标大纲后继续。", StopAction.BYPASS),
        ("PPT已生成，请确认是否下载。", StopAction.INTERRUPT_AND_CONTINUE),
        ("大纲已完成，请确认大纲后再生成PPT。", StopAction.BYPASS),
        ("已生成大纲，请确认后继续。", StopAction.BYPASS),
    ],
)
def test_approval_and_missing_inputs_are_not_overridden_as_delivery_failure(
    text, action
):
    guard = FileDeliveryGuard(
        {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    )
    assert (
        guard.check(
            Msg(name="assistant", role="assistant", content=[TextBlock(text=text)])
        ).action
        == action
    )
