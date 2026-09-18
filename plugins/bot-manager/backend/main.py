"""
Bot 管理器 - 后端统一 API
通过 channel 适配器支持多渠道，新增渠道只需在 channels.py 注册适配器。
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

try:
    from qwenpaw.plugins.api import PluginApi
except ImportError:
    PluginApi = None

from .channels import get_channel, list_channels

logger = logging.getLogger(__name__)
router = APIRouter()


# ============ 工具函数 ============

def get_working_dir() -> Path:
    """获取 QwenPaw working directory"""
    wd = os.environ.get("QWENPAW_WORKING_DIR")
    if wd:
        return Path(wd)
    return Path.home() / ".qwenpaw"


def get_agent_config_path(agent_id: str) -> Optional[Path]:
    """获取智能体的 agent.json 路径"""
    p = get_working_dir() / "workspaces" / agent_id / "agent.json"
    return p if p.exists() else None


def load_agent_config(agent_id: str) -> Optional[Dict]:
    """加载智能体配置"""
    p = get_agent_config_path(agent_id)
    if not p:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[bot-manager] load config {agent_id}: {e}")
        return None


def save_agent_config(agent_id: str, config: Dict) -> bool:
    """保存智能体配置"""
    p = get_agent_config_path(agent_id)
    if not p:
        return False
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"[bot-manager] saved config for {agent_id}")
        return True
    except Exception as e:
        logger.error(f"[bot-manager] save config {agent_id}: {e}")
        return False


def list_all_agents() -> List[str]:
    """列出所有智能体 ID"""
    wd = get_working_dir()
    # 优先从 config.json 读取
    cp = wd / "config.json"
    if cp.exists():
        try:
            with open(cp, "r", encoding="utf-8") as f:
                c = json.load(f)
            profiles = c.get("agents", {}).get("profiles", {})
            valid = [aid for aid, p in profiles.items() if p.get("enabled", False)]
            return sorted(valid)
        except Exception:
            pass
    # 回退到目录遍历
    wsd = wd / "workspaces"
    if not wsd.exists():
        return []
    return sorted(
        d.name for d in wsd.iterdir()
        if d.is_dir() and (d / "agent.json").exists()
    )


def _require_channel(ch_key: str):
    """获取适配器，不存在则 404"""
    adapter = get_channel(ch_key)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Unsupported channel: {ch_key}")
    return adapter


# ============ API Models ============

class ConfigUpdate(BaseModel):
    """通用配置更新 — 所有字段可选"""
    enabled: Optional[bool] = None
    bot_prefix: Optional[str] = None
    # 黄金字段
    bot_token: Optional[str] = None
    dm_policy: Optional[str] = None
    group_policy: Optional[str] = None
    # 钉钉字段
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    robot_code: Optional[str] = None
    message_type: Optional[str] = None
    cron_message_type: Optional[str] = None
    card_template_id: Optional[str] = None
    card_auto_layout: Optional[bool] = None
    at_sender_on_reply: Optional[bool] = None
    streaming_enabled: Optional[bool] = None
    share_session_in_group: Optional[bool] = None
    endpoint: Optional[str] = None


class BatchUpdateRequest(BaseModel):
    agent_ids: List[str]
    enabled: Optional[bool] = None
    bot_prefix: Optional[str] = None
    message_type: Optional[str] = None


# ============ API Routes ============

@router.get("/channels")
async def get_channels():
    """返回所有支持的渠道列表"""
    result = []
    for ch_key in list_channels():
        ad = get_channel(ch_key)
        result.append({
            "key": ad.channel_key,
            "name": ad.display_name,
            "binding_method": ad.binding_method,
        })
    return {"channels": result}


@router.get("/{channel}/agents")
async def list_agents(channel: str):
    """获取所有智能体的指定渠道配置"""
    ad = _require_channel(channel)
    agents = list_all_agents()
    result = []

    for aid in agents:
        cfg = load_agent_config(aid)
        if not cfg:
            continue
        ch_cfg = ad.get_config(cfg)
        entry = {
            "agent_id": aid,
            "name": cfg.get("name", aid),
            "enabled": ch_cfg.get("enabled", False),
            "has_credentials": ad.has_credentials(ch_cfg),
            "has_native_config": bool(ch_cfg),
        }
        entry.update(ad.get_status_fields(ch_cfg))
        result.append(entry)

    return {"agents": result, "total": len(result), "channel": channel}


@router.get("/{channel}/agents/{agent_id}")
async def get_agent(channel: str, agent_id: str):
    """获取单个智能体的渠道配置"""
    ad = _require_channel(channel)
    cfg = load_agent_config(agent_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    ch_cfg = ad.get_config(cfg)
    return {
        "agent_id": agent_id,
        "name": cfg.get("name", agent_id),
        "channel": channel,
        **ch_cfg,
        "enabled": ch_cfg.get("enabled", False),
        "has_credentials": ad.has_credentials(ch_cfg),
    }


@router.post("/{channel}/agents/{agent_id}/config")
async def update_agent_config(channel: str, agent_id: str, request: Request):
    """更新智能体渠道配置"""
    ad = _require_channel(channel)
    cfg = load_agent_config(agent_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 过滤掉 None 值，只更新提供的字段
    update = {k: v for k, v in body.items() if v is not None}
    logger.info(f"[bot-manager] update {channel}/{agent_id}: {list(update.keys())}")

    cfg = ad.update_config(cfg, update)
    if save_agent_config(agent_id, cfg):
        return {"success": True, "message": f"Updated {channel} config for {agent_id}"}
    raise HTTPException(status_code=500, detail="Failed to save config")


@router.post("/{channel}/agents/{agent_id}/toggle")
async def toggle_agent(channel: str, agent_id: str):
    """切换启用状态"""
    ad = _require_channel(channel)
    cfg = load_agent_config(agent_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    ch_cfg = ad.get_config(cfg)
    new_enabled = not ch_cfg.get("enabled", False)
    cfg = ad.update_config(cfg, {"enabled": new_enabled})

    if save_agent_config(agent_id, cfg):
        return {"success": True, "enabled": new_enabled}
    raise HTTPException(status_code=500, detail="Failed to save")


@router.post("/{channel}/agents/{agent_id}/clear-credentials")
async def clear_credentials(channel: str, agent_id: str):
    """清除凭据"""
    ad = _require_channel(channel)
    cfg = load_agent_config(agent_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    cfg = ad.clear_credentials(cfg)
    if save_agent_config(agent_id, cfg):
        return {"success": True, "message": "Credentials cleared"}
    raise HTTPException(status_code=500, detail="Failed to save")


@router.post("/{channel}/agents/batch-update")
async def batch_update(channel: str, request: BatchUpdateRequest):
    """批量更新"""
    ad = _require_channel(channel)
    results = []

    for aid in request.agent_ids:
        cfg = load_agent_config(aid)
        if not cfg:
            results.append({"agent_id": aid, "success": False, "error": "Not found"})
            continue

        update = {}
        if request.enabled is not None:
            update["enabled"] = request.enabled
        if request.bot_prefix is not None:
            update["bot_prefix"] = request.bot_prefix
        if request.message_type is not None:
            update["message_type"] = request.message_type

        cfg = ad.update_config(cfg, update)
        ok = save_agent_config(aid, cfg)
        results.append({"agent_id": aid, "success": ok})

    return {"results": results}


@router.get("/{channel}/status")
async def get_status(channel: str):
    """获取渠道统计"""
    ad = _require_channel(channel)
    agents = list_all_agents()
    configs = [load_agent_config(a) for a in agents]
    configs = [c for c in configs if c]
    return ad.get_status(configs)


# ============ Plugin Class ============

class BotManagerPlugin:
    """Bot 管理器插件"""

    def __init__(self):
        self.id = "bot-manager"
        self.name = "Bot 管理器"
        self.version = "1.0.0"
        self.router = router

    def register(self, api: PluginApi) -> None:
        api.register_http_router(
            self.router,
            prefix="/plugins/bot-manager",
            tags=["bot-manager"],
        )
        logger.info("[bot-manager] Plugin registered")


# REQUIRED: 模块级 plugin 实例
plugin = BotManagerPlugin()