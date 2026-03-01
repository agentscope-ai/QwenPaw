# -*- coding: utf-8 -*-
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request

from ...agents.model_factory import create_model_and_formatter
from .manager import CronManager
from .models import CronJobSpec, CronJobView, CronParseRequest, CronParseResponse
from .parser import parse_with_rules, validate_cron, cron_to_human

router = APIRouter(prefix="/cron", tags=["cron"])


def get_cron_manager(request: Request) -> CronManager:
    mgr = getattr(request.app.state, "cron_manager", None)
    if mgr is None:
        raise HTTPException(
            status_code=503,
            detail="cron manager not initialized",
        )
    return mgr


@router.get("/jobs", response_model=list[CronJobSpec])
async def list_jobs(mgr: CronManager = Depends(get_cron_manager)):
    return await mgr.list_jobs()


@router.get("/jobs/{job_id}", response_model=CronJobView)
async def get_job(job_id: str, mgr: CronManager = Depends(get_cron_manager)):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return CronJobView(spec=job, state=mgr.get_state(job_id))


@router.post("/jobs", response_model=CronJobSpec)
async def create_job(
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
):
    # server generates id; ignore client-provided spec.id
    job_id = str(uuid.uuid4())
    created = spec.model_copy(update={"id": job_id})
    await mgr.create_or_replace_job(created)
    return created


@router.put("/jobs/{job_id}", response_model=CronJobSpec)
async def replace_job(
    job_id: str,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
):
    if spec.id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    await mgr.create_or_replace_job(spec)
    return spec


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    ok = await mgr.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": True}


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, mgr: CronManager = Depends(get_cron_manager)):
    try:
        await mgr.pause_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"paused": True}


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    try:
        await mgr.resume_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"resumed": True}


@router.post("/jobs/{job_id}/run")
async def run_job(job_id: str, mgr: CronManager = Depends(get_cron_manager)):
    try:
        await mgr.run_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"started": True}


@router.get("/jobs/{job_id}/state")
async def get_job_state(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return mgr.get_state(job_id).model_dump(mode="json")


@router.post("/parse-cron", response_model=CronParseResponse)
async def parse_cron_expression(request: CronParseRequest):
    """
    Parse natural language to cron expression.

    - First tries local rule-based parsing (fast)
    - Falls back to LLM if rules don't match (smart)
    """
    text = request.text.strip()

    # 1. Try local rule-based parsing (fast)
    local_result = parse_with_rules(text)
    if local_result:
        return CronParseResponse(
            cron=local_result,
            source="rules",
            description=cron_to_human(local_result),
        )

    # 2. Try LLM parsing (smart fallback)
    try:
        llm_result = await _parse_with_llm(text)
        return CronParseResponse(
            cron=llm_result,
            source="llm",
            description=cron_to_human(llm_result),
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"无法解析表达式: {text}. 请使用标准 cron 格式或更清晰的自然语言描述。错误: {str(e)}",
        ) from e


async def _parse_with_llm(text: str) -> str:
    """Use LLM to parse complex/ambiguous natural language."""
    prompt = f"""将自然语言转换为标准 cron 表达式（5个字段）。

规则：
- 只输出 cron 表达式，不要其他内容
- 格式：分钟 小时 日 月 星期
- 如果有歧义，选择最合理的解释

示例：
"每天下午2点" → 0 14 * * *
"每周一上午9点" → 0 9 * * 1
"每小时" → 0 * * * *
"每30分钟" → */30 * * * *
"工作日早上9点" → 0 9 * * 1-5

输入：{text}
输出（只输出cron表达式）："""

    model, _ = create_model_and_formatter()
    response = await model([{"role": "user", "content": prompt}])

    # Extract cron from response
    cron = response.text.strip()

    # Clean up potential extra text
    lines = cron.split("\n")
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("//"):
            parts = line.split()
            if len(parts) == 5:
                cron = line
                break

    # Validate
    validate_cron(cron)
    return cron
