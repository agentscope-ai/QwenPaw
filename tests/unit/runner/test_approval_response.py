"""Test that query_handler handles mcp_approval_response from frontend buttons."""
from copaw.app.runner.runner import _extract_approval_response


def test_extract_approval_response_from_data_content():
    """Should extract approve=True from a DataContent-style message."""
    msgs = [
        {
            "role": "user",
            "content": [
                {
                    "type": "data",
                    "data": {
                        "approve": True,
                        "id": "call_789",
                        "approval_request_id": "call_789",
                        "reason": None,
                    },
                }
            ],
        }
    ]
    result = _extract_approval_response(msgs)
    assert result is not None
    assert result["approve"] is True
    assert result["id"] == "call_789"


def test_extract_approval_response_denied():
    """Should extract approve=False when user cancels."""
    msgs = [
        {
            "role": "user",
            "content": [
                {
                    "type": "data",
                    "data": {
                        "approve": False,
                        "id": "call_999",
                        "approval_request_id": "call_999",
                        "reason": "too dangerous",
                    },
                }
            ],
        }
    ]
    result = _extract_approval_response(msgs)
    assert result is not None
    assert result["approve"] is False
    assert result["reason"] == "too dangerous"


def test_extract_approval_response_normal_text():
    """Normal text messages should return None."""
    msgs = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Hello world",
                }
            ],
        }
    ]
    result = _extract_approval_response(msgs)
    assert result is None


def test_extract_approval_response_empty():
    """Empty msgs should return None."""
    assert _extract_approval_response([]) is None
    assert _extract_approval_response(None) is None
