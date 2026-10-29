"""控制面 FastAPI 应用。"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from airport_sms.api.auth import AuthError, TokenStore
from airport_sms.governance.governor import Governor
from airport_sms.runtime.runtime import AgentRequest, Runtime
from airport_sms.session.case_repo import CaseNotFound


class LoginBody(BaseModel):
    """登录体。"""

    token: str


class ChatBody(BaseModel):
    """聊天体。"""

    session_id: str
    text: str = ""
    command: str | None = None


class ApprovalBody(BaseModel):
    """审批体。"""

    approval_id: str
    approve: bool


def create_app(runtime: Runtime | None = None) -> FastAPI:
    """工厂：默认鉴权开启。"""
    app = FastAPI(title="airport-sms")
    rt = runtime or Runtime.in_memory()
    tokens = TokenStore()
    app.state.runtime = rt
    app.state.tokens = tokens

    @app.middleware("http")
    async def add_trace(request: Request, call_next):
        """注入 trace / request id。"""
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
        response: Response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-trace-id"] = trace_id
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        """健康检查。"""
        return {"status": "ok"}

    @app.post("/login")
    def login(body: LoginBody) -> dict[str, str]:
        """用预置令牌登录。"""
        try:
            principal = tokens.resolve(f"Bearer {body.token}")
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {
            "token": body.token,
            "user_id": principal.user_id,
            "role": principal.role.value,
        }

    def _principal(authorization: str | None):
        try:
            return tokens.resolve(authorization)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.post("/chat")
    async def chat(
        body: ChatBody,
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        """SSE 聊天。必须鉴权。"""
        principal = _principal(authorization)

        async def gen() -> AsyncIterator[bytes]:
            for event in rt.run(
                AgentRequest(
                    session_id=body.session_id,
                    principal=principal,
                    text=body.text,
                    command=body.command,
                )
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/cases/{case_id}")
    def get_case(
        case_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """案件详情。跨租户 404。"""
        principal = _principal(authorization)
        try:
            case = rt.cases.get(principal, case_id)  # type: ignore[arg-type]
        except CaseNotFound as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        return {
            "id": str(case.id),
            "state": case.state.value,
            "audit": [
                {
                    "from": a.from_state.value,
                    "to": a.to_state.value,
                    "actor": a.actor.value,
                    "reason": a.reason,
                }
                for a in case.audit
            ],
        }

    @app.get("/cases")
    def list_cases(
        authorization: str | None = Header(default=None),
    ) -> list[dict]:
        """场站案件列表。"""
        principal = _principal(authorization)
        return [
            {"id": str(c.id), "state": c.state.value}
            for c in rt.cases.list_by_site(principal)
        ]

    @app.get("/approvals")
    def list_approvals(
        authorization: str | None = Header(default=None),
    ) -> list[dict]:
        """待审批。"""
        _principal(authorization)
        gov: Governor = rt.governor
        return [
            {
                "id": a.id,
                "tool_name": a.tool_name,
                "case_id": a.case_id,
                "status": a.status.value,
            }
            for a in gov.approvals.pending.values()
            if a.status.value == "pending"
        ]

    @app.post("/approvals/decide")
    def decide(
        body: ApprovalBody,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """批准或拒绝。"""
        principal = _principal(authorization)
        gov: Governor = rt.governor
        req, action = gov.approvals.decide(body.approval_id, approve=body.approve)
        case = None
        if body.approve and req.case_id:
            from airport_sms.domain.case import CaseState
            from airport_sms.domain.transitions import transition

            try:
                case = rt.cases.get(principal, req.case_id)  # type: ignore[arg-type]
                if req.tool_name == "submit_case" and case.state.value == "draft":
                    updated = transition(
                        case, CaseState.SUBMITTED, principal.role, "approved"
                    )
                    rt.cases.write(
                        principal, updated, expected_version=case.version
                    )
                    case = updated
            except CaseNotFound:
                case = None
        return {
            "action": action.value,
            "status": req.status.value,
            "case_state": case.state.value if case else None,
        }

    return app


__all__ = ["create_app"]
