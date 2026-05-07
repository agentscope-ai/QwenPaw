"""记忆钩子 - 自动检索和存储记忆

功能：
- pre_reasoning: 自动搜索相关记忆注入上下文（带范围隔离）
- post_reply: LLM 智能提取 + 分类存储 + 遗忘清理
"""
import os
import json
import logging
import urllib.request
import shutil
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 最大记忆条数，超出后触发智能遗忘
MAX_MEMORIES = 200

# 敏感配置改为从环境变量或 agent 配置读取，不硬编码
def _get_emb_config(agent=None) -> dict:
    """获取 embedding 配置：agent.json > 环境变量 > 内置默认值"""
    config = {}
    # 1. 优先从 agent 的 embedding 配置读取
    if agent is not None:
        try:
            mgr = getattr(agent, "memory", None)
            if mgr is not None and hasattr(mgr, "get_embedding_config"):
                emb = mgr.get_embedding_config()
                config["api_key"] = emb.get("api_key", "")
                config["base_url"] = emb.get("base_url", "")
                config["model"] = emb.get("model_name", "")
                if config["api_key"] and config["base_url"] and config["model"]:
                    return config
        except Exception:
            pass
    # 2. 环境变量兜底
    config["api_key"] = os.environ.get("EMBEDDING_API_KEY", "")
    config["base_url"] = os.environ.get("EMBEDDING_BASE_URL", "")
    config["model"] = os.environ.get("EMBEDDING_MODEL_NAME", "")
    if config["api_key"] and config["base_url"] and config["model"]:
        return config
    # 3. 空配置（调用方自行处理缺失情况）
    return config


def _get_db_path(agent) -> str:
    """从 agent 获取工作区路径并拼接 LanceDB 数据库路径"""
    ws = getattr(agent, "_workspace_dir", None)
    if not ws:
        wd = getattr(agent, "working_dir", None)
        if wd:
            ws = str(wd)
    if not ws:
        ws = r"C:\Users\Administrator\.qwenpaw\workspaces\default"
    return os.path.join(str(ws), "projects", "Yunding_EA", "vector_memory")


def _get_scope(agent) -> dict:
    """获取当前范围信息（多范围隔离）"""
    agent_id = getattr(agent, "agent_id", "default")
    ws = _get_db_path(agent)
    return {
        "scope_type": "user",
        "scope_id": agent_id
    }


def _get_embedding(text: str, agent=None) -> list:
    """调百炼 API 获取向量（配置从 agent/环境变量读取，不硬编码）"""
    emb = _get_emb_config(agent)
    api_key = emb.get("api_key", "") or os.environ.get("EMBEDDING_API_KEY", "")
    base_url = emb.get("base_url", "") or os.environ.get("EMBEDDING_BASE_URL", "")
    model = emb.get("model", "") or os.environ.get("EMBEDDING_MODEL_NAME", "")
    if not api_key or not base_url or not model:
        logger.error("Embedding 配置缺失：请在 UI 运行配置中填写或设置环境变量 EMBEDDING_API_KEY/BASE_URL/MODEL_NAME")
        return []
    data = json.dumps({"model": model, "input": text}).encode()
    req = urllib.request.Request(
        f"{base_url}/embeddings",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )
    resp = urllib.request.urlopen(req, timeout=15)
    result = json.loads(resp.read())
    return result["data"][0]["embedding"]


# ===== LLM 智能提取 =====

_EXTRACT_PROMPT = """你是一个对话分析师。分析以下对话，提取出有价值的信息。

分类标准：
- profile: 个人信息、角色、身份
- preference: 偏好、习惯、风格
- entity: 项目名、工具名、版本号、路径等实体
- event: 已发生的事件、决策、变更
- case: 案例、经验教训、解决方案
- pattern: 行为模式、规则、工作流程

要求：
1. 只提取有价值、可复用的信息
2. 每条信息用一句话概括
3. 如果没有有价值的信息，返回空数组
4. 给每条信息的重要性打分 (0~1)，低于 0.6 的不要

按以下 JSON 格式返回（不要加 markdown 标记）：
{"items": [{"text": "...", "category": "profile|preference|entity|event|case|pattern", "importance": 0.8}]}

对话内容：
"""


def _llm_extract(dialog_text: str, agent=None) -> list | None:
    """用 LLM 提取对话中的有价值信息（配置从 agent/环境变量读取）"""
    try:
        emb = _get_emb_config(agent)
        api_key = emb.get("api_key", "") or os.environ.get("EMBEDDING_API_KEY", "")
        base_url = emb.get("base_url", "") or os.environ.get("EMBEDDING_BASE_URL", "")
        if not api_key or not base_url:
            logger.warning("LLM extract 配置缺失，跳过")
            return None
        prompt = _EXTRACT_PROMPT + dialog_text[-3000:]
        data = json.dumps({
            "model": "qwen-turbo",
            "messages": [
                {"role": "system", "content": "你是一个精准的对话分析师，只提取有价值的信息。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        return parsed.get("items", [])
    except Exception as e:
        logger.error(f"LLM extract failed: {e}")
        return None


# ===== 智能遗忘 =====

def _weibull_decay(importance: float, hours_aged: float) -> float:
    """Weibull 衰减：高 importance 衰减慢，低 importance 衰减快"""
    # shape 参数：importance 越高，shape 越大，衰减越慢
    shape = 1.0 + importance * 2.0  # 1.0 ~ 3.0
    scale = 72.0  # 特征寿命：3天
    from math import exp
    return importance * exp(-((hours_aged / scale) ** shape))


def _cleanup_old_memories(agent):
    """智能遗忘：删除低价值的老旧记忆"""
    import lancedb
    try:
        db_path = _get_db_path(agent)
        lance_path = os.path.join(db_path, "memories.lance")
        if not os.path.exists(lance_path):
            return
        db = lancedb.connect(db_path)
        tbl = db.open_table("memories")
        count = tbl.count_rows()
        if count <= MAX_MEMORIES:
            return

        # 读出所有数据
        all_data = tbl.search().limit(count).to_list()
        now = datetime.now()
        to_delete = []
        keep = []
        for item in all_data:
            ts_str = item.get("timestamp", "")
            importance = item.get("importance", 0.5)
            try:
                ts = datetime.fromisoformat(ts_str)
                hours = (now - ts).total_seconds() / 3600
                score = _weibull_decay(importance, hours)
            except Exception:
                score = importance

            if score < 0.3:
                to_delete.append(item.get("_rowid", 0))
            else:
                keep.append(item)

        if to_delete and keep:
            # 重建表（LanceDB 不支持直接删除行）
            tbl_name = "memories"
            db.drop_table(tbl_name)
            if keep:
                new_tbl = db.create_table(tbl_name, data=keep, mode="overwrite")
                logger.info(f"智能遗忘: 删除了 {len(to_delete)} 条低价值记忆，剩余 {len(keep)} 条")

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")


# ===== 存储与检索 =====

def _search_memory(agent, query: str, limit: int = 5) -> list:
    """搜索 LanceDB（带范围隔离和混合检索）"""
    import lancedb
    db_path = _get_db_path(agent)
    lance_path = os.path.join(db_path, "memories.lance")
    if not os.path.exists(lance_path):
        return []
    db = lancedb.connect(db_path)
    try:
        tbl = db.open_table("memories")
    except Exception:
        return []
    vector = _get_embedding(query, agent)

    # 向量搜索 + BM25 关键词匹配（混合检索简化版）
    results = tbl.search(vector).limit(limit * 2).to_list()

    # 用关键词 BM25 辅助排序
    query_words = set(query.lower().split())
    scored = []
    for r in results:
        vec_score = r.get("_score", 0)
        text = str(r.get("text", "")).lower()
        # BM25 简化：关键词命中率
        word_hits = sum(1 for w in query_words if w in text)
        bm25_score = word_hits / max(len(query_words), 1) * 0.3
        combined = vec_score * 0.7 + bm25_score
        scored.append((combined, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def _store_memory(agent, text: str, category: str = "auto", importance: float = 0.7):
    """存入 LanceDB（带范围隔离和重要性）"""
    import lancedb
    db_path = _get_db_path(agent)
    os.makedirs(db_path, exist_ok=True)
    db = lancedb.connect(db_path)
    vector = _get_embedding(text, agent)
    scope = _get_scope(agent)

    record = {
        "vector": vector,
        "text": text,
        "category": category,
        "importance": importance,
        "scope_type": scope["scope_type"],
        "scope_id": scope["scope_id"],
        "timestamp": datetime.now().isoformat()
    }

    try:
        tbl = db.open_table("memories")
        tbl.add([record])
    except Exception:
        db.create_table("memories", data=[record], mode="overwrite")


# ===== 管理 CLI（嵌入到钩子中） =====

def _backup_memories(agent, backup_dir: str = None) -> str:
    """备份 LanceDB 数据"""
    src = _get_db_path(agent)
    if not backup_dir:
        backup_dir = os.path.join(os.path.dirname(src), f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    if os.path.exists(src):
        shutil.copytree(src, backup_dir, dirs_exist_ok=True)
        return backup_dir
    return ""


def export_memories_json(agent) -> str:
    """导出记忆为 JSON"""
    import lancedb
    db_path = _get_db_path(agent)
    lance_path = os.path.join(db_path, "memories.lance")
    if not os.path.exists(lance_path):
        return "[]"
    db = lancedb.connect(db_path)
    try:
        tbl = db.open_table("memories")
        count = tbl.count_rows()
        data = tbl.search().limit(count).to_list()
        export_path = os.path.join(os.path.dirname(db_path), f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        clean = []
        for item in data:
            clean.append({
                "text": item.get("text", ""),
                "category": item.get("category", ""),
                "importance": item.get("importance", 0.5),
                "scope_type": item.get("scope_type", ""),
                "scope_id": item.get("scope_id", ""),
                "timestamp": item.get("timestamp", "")
            })
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        return export_path
    except Exception as e:
        return f"导出失败: {e}"


# ===== MemoryHook 类 =====

class MemoryHook:
    """自动记忆钩子"""

    def __init__(self):
        self.last_user_message = ""

    async def pre_reasoning(self, agent, kwargs: dict) -> dict | None:
        """自动搜索相关记忆注入上下文"""
        try:
            messages = kwargs.get("messages", [])
            if not messages:
                return None

            for msg in reversed(messages):
                if getattr(msg, "role", "") == "user":
                    self.last_user_message = str(getattr(msg, "content", ""))
                    break

            if not self.last_user_message:
                return None

            results = _search_memory(agent, self.last_user_message, limit=3)
            if not results:
                return None

            memory_lines = []
            for i, r in enumerate(results):
                memory_lines.append(f"[记忆 {i+1}] {r['text']}")
            memory_block = (
                "\n\n---\n"
                "以下是从长期记忆中检索到的相关信息：\n"
                + "\n".join(memory_lines) +
                "\n---\n"
            )

            for msg in reversed(messages):
                role = getattr(msg, "role", "")
                if role in ("system", "user"):
                    old_content = str(getattr(msg, "content", ""))
                    setattr(msg, "content", old_content + memory_block)
                    logger.info(f"Memory hook: 已注入 {len(results)} 条记忆")
                    break

        except Exception as e:
            logger.error(f"Memory hook pre_reasoning failed: {e}")

        return None

    async def post_reply(self, agent, kwargs: dict, output=None) -> dict | None:
        """用 LLM 智能提取 + 存储 + 遗忘清理"""
        try:
            memory = getattr(agent, "memory", None)
            if memory is None:
                return None

            messages = await memory.get_memory()
            if not messages:
                return None

            recent = messages[-6:]
            dialog_text = ""
            for msg in recent:
                role = getattr(msg, "role", "unknown")
                content = str(getattr(msg, "content", ""))
                if role == "user":
                    dialog_text += f"用户：{content}\n"
                elif role == "assistant":
                    dialog_text += f"助手：{content}\n"

            if len(dialog_text.strip()) < 60:
                return None

            # LLM 提取
            analysis = _llm_extract(dialog_text, agent)
            if analysis is None:
                return None

            # 存储
            for item in analysis:
                text = item.get("text", "").strip()
                category = item.get("category", "通用")
                importance = item.get("importance", 0.5)
                if text and len(text) > 10 and importance >= 0.6:
                    _store_memory(agent, text, category, importance)
                    logger.info(f"存储: {category} (重要性={importance})")

            # 智能遗忘：检查数据量，超了就清理
            try:
                import lancedb
                db_path = _get_db_path(agent)
                lance_path = os.path.join(db_path, "memories.lance")
                if os.path.exists(lance_path):
                    db = lancedb.connect(db_path)
                    tbl = db.open_table("memories")
                    if tbl.count_rows() > MAX_MEMORIES:
                        _cleanup_old_memories(agent)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Memory hook post_reply failed: {e}")

        return None
