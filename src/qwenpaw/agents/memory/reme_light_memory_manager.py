# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
# mypy: ignore-errors
"""ReMeLight-backed memory manager for agents."""
import asyncio
import importlib.metadata
import json
import logging
import os
import platform
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock
from agentscope.tool import Toolkit, ToolResponse

from qwenpaw.agents.memory.base_memory_manager import BaseMemoryManager
from qwenpaw.agents.model_factory import create_model_and_formatter
from qwenpaw.agents.tools import read_file, write_file, edit_file
from qwenpaw.agents.utils import get_token_counter
from qwenpaw.config import load_config
from qwenpaw.config.config import load_agent_config
from qwenpaw.config.context import (
    set_current_workspace_dir,
    set_current_recent_max_bytes,
)
from qwenpaw.constant import EnvVarLoader

if TYPE_CHECKING:
    from reme.memory.file_based.reme_in_memory_memory import ReMeInMemoryMemory

logger = logging.getLogger(__name__)

_EXPECTED_REME_VERSION = "0.3.1.8"
_REME_STORE_VERSION = "v1"


class ReMeLightMemoryManager(BaseMemoryManager):
    """Memory manager that wraps ReMeLight for agents via composition.

    Holds a ``ReMeLight`` instance (``self._reme``) and delegates all
    lifecycle / search / compaction calls to it.

    Capabilities:
    - Conversation compaction via compact_memory()
    - Memory summarization with file tools via summary_memory()
    - Vector and full-text search via memory_search()
    """

    def __init__(self, working_dir: str, agent_id: str):
        """Initialize with ReMeLight.

        Args:
            working_dir: Working directory for memory storage.
            agent_id: Agent ID for config loading.

        Embedding priority: config > env var (EMBEDDING_API_KEY /
        EMBEDDING_BASE_URL / EMBEDDING_MODEL_NAME).
        Backend: MEMORY_STORE_BACKEND env var (auto/local/chroma,
        default auto).
        """
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._reme_version_ok: bool = self._check_reme_version()
        self._reme = None

        logger.info(
            f"ReMeLightMemoryManager init: "
            f"agent_id={agent_id}, working_dir={working_dir}",
        )

        backend_env = EnvVarLoader.get_str("MEMORY_STORE_BACKEND", "auto")
        if backend_env == "auto":
            if platform.system() == "Windows":
                memory_backend = "local"
            else:
                try:
                    import chromadb  # noqa: F401 pylint: disable=unused-import

                    memory_backend = "chroma"
                except Exception as e:
                    logger.warning(
                        f"""
chromadb import failed, falling back to `local` backend.
This is often caused by an outdated system SQLite (requires >= 3.35).
Please upgrade your system SQLite to >= 3.35.
See: https://docs.trychroma.com/docs/overview/troubleshooting#sqlite
| Error: {e}
                        """,
                    )
                    memory_backend = "local"
        else:
            memory_backend = backend_env

        from reme.reme_light import ReMeLight

        emb_config = self.get_embedding_config()
        vector_enabled = bool(emb_config["base_url"]) and bool(
            emb_config["model_name"],
        )

        log_cfg = {
            **emb_config,
            "api_key": self._mask_key(emb_config["api_key"]),
        }
        logger.info(
            f"Embedding config: {log_cfg}, vector_enabled={vector_enabled}",
        )

        fts_enabled = EnvVarLoader.get_bool("FTS_ENABLED", True)

        agent_config = load_agent_config(self.agent_id)
        rebuild_on_start = (
            agent_config.running.memory_summary.rebuild_memory_index_on_start
        )

        store_name = "memory"
        effective_rebuild = self._resolve_rebuild_on_start(
            working_dir=working_dir,
            store_version=_REME_STORE_VERSION,
            rebuild_on_start=rebuild_on_start,
        )

        self._reme = ReMeLight(
            working_dir=working_dir,
            default_embedding_model_config=emb_config,
            default_file_store_config={
                "backend": memory_backend,
                "store_name": store_name,
                "vector_enabled": vector_enabled,
                "fts_enabled": fts_enabled,
            },
            default_file_watcher_config={
                "rebuild_index_on_start": effective_rebuild,
            },
        )

        self.summary_toolkit = Toolkit()
        self.summary_toolkit.register_tool_function(read_file)
        self.summary_toolkit.register_tool_function(write_file)
        self.summary_toolkit.register_tool_function(edit_file)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_key(key: str) -> str:
        """Mask API key, showing first 5 chars only."""
        return key[:5] + "*" * (len(key) - 5) if len(key) > 5 else key

    @staticmethod
    def _resolve_rebuild_on_start(
        working_dir: str,
        store_version: str,
        rebuild_on_start: bool,
    ) -> bool:
        """Return effective rebuild_index_on_start value.

        Uses a sentinel file ``.reme_store_{store_version}`` to track whether
        the current store version has already been initialized.  If the
        sentinel is absent a one-time rebuild is forced and the sentinel is
        created.  On subsequent starts the sentinel exists and the
        caller-supplied *rebuild_on_start* is used as-is.

        To trigger a future one-time rebuild, bump *_REME_STORE_VERSION*.
        """
        sentinel_name = f".reme_store_{store_version}"
        sentinel_path = Path(working_dir) / sentinel_name

        if sentinel_path.exists():
            return rebuild_on_start

        logger.info(
            f"Sentinel '{sentinel_name}' not found, forcing rebuild.",
        )

        # Remove stale sentinels left by previous versions.
        try:
            for old in Path(working_dir).glob(".reme_store_*"):
                old.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Failed to remove old sentinels: {e}")

        try:
            sentinel_path.touch()
        except Exception as e:
            logger.warning(f"Failed to create sentinel '{sentinel_name}': {e}")

        return True

    @staticmethod
    def _check_reme_version() -> bool:
        """Return False (and warn) when installed reme-ai version
        mismatches."""
        try:
            installed = importlib.metadata.version("reme-ai")
        except importlib.metadata.PackageNotFoundError:
            return True
        if installed != _EXPECTED_REME_VERSION:
            logger.warning(
                f"reme-ai version mismatch: installed={installed}, "
                f"expected={_EXPECTED_REME_VERSION}. "
                f"Run `pip install reme-ai=={_EXPECTED_REME_VERSION}`"
                " to align.",
            )
            return False
        return True

    def _warn_if_version_mismatch(self) -> None:
        """Warn once per call if the cached version check failed."""
        if not self._reme_version_ok:
            logger.warning(
                "reme-ai version mismatch, "
                f"expected={_EXPECTED_REME_VERSION}. "
                f"Run `pip install reme-ai=={_EXPECTED_REME_VERSION}`"
                " to align.",
            )

    def _prepare_model_formatter(self) -> None:
        """Lazily initialize chat_model and formatter if not already set."""
        self._warn_if_version_mismatch()
        if self.chat_model is None or self.formatter is None:
            self.chat_model, self.formatter = create_model_and_formatter(
                self.agent_id,
            )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_embedding_config(self) -> dict:
        """Return embedding config with priority:
        config > env var > default."""
        self._warn_if_version_mismatch()
        cfg = load_agent_config(self.agent_id).running.embedding_config
        return {
            "backend": cfg.backend,
            "api_key": cfg.api_key
            or EnvVarLoader.get_str("EMBEDDING_API_KEY"),
            "base_url": cfg.base_url
            or EnvVarLoader.get_str("EMBEDDING_BASE_URL"),
            "model_name": cfg.model_name
            or EnvVarLoader.get_str("EMBEDDING_MODEL_NAME"),
            "dimensions": cfg.dimensions,
            "enable_cache": cfg.enable_cache,
            "use_dimensions": cfg.use_dimensions,
            "max_cache_size": cfg.max_cache_size,
            "max_input_length": cfg.max_input_length,
            "max_batch_size": cfg.max_batch_size,
        }

    async def restart_embedding_model(self):
        """Restart the embedding model with current config."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return
        await self._reme.restart(
            restart_config={
                "embedding_models": {"default": self.get_embedding_config()},
            },
        )

    # ------------------------------------------------------------------
    # BaseMemoryManager interface
    # ------------------------------------------------------------------

    async def start(self):
        """Start the ReMeLight lifecycle."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        return await self._reme.start()

    async def close(self) -> bool:
        """Close ReMeLight and perform cleanup."""
        self._warn_if_version_mismatch()
        logger.info(
            f"ReMeLightMemoryManager closing: agent_id={self.agent_id}",
        )
        if self._reme is None:
            return True
        result = await self._reme.close()
        logger.info(
            f"ReMeLightMemoryManager closed: "
            f"agent_id={self.agent_id}, result={result}",
        )
        return result

    async def compact_tool_result(self, **kwargs):
        """Compact tool results by truncating large outputs."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        return await self._reme.compact_tool_result(**kwargs)

    async def check_context(self, **kwargs):
        """Check context size and determine if compaction is needed."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        return await self._reme.check_context(**kwargs)

    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
        **_kwargs,
    ) -> str:
        """Compact messages into a condensed summary.

        Returns the compacted string, or empty string on failure.
        """
        self._prepare_model_formatter()

        agent_config = load_agent_config(self.agent_id)
        cc = agent_config.running.context_compact

        if extra_instruction:
            result = await self._reme.compact_memory(
                messages=messages,
                as_llm=self.chat_model,
                as_llm_formatter=self.formatter,
                as_token_counter=get_token_counter(agent_config),
                language=agent_config.language,
                max_input_length=agent_config.running.max_input_length,
                compact_ratio=cc.memory_compact_ratio,
                previous_summary=previous_summary,
                return_dict=True,
                add_thinking_block=cc.compact_with_thinking_block,
                extra_instruction=extra_instruction,
            )
        else:
            # Compatible with older versions of ReMe
            result = await self._reme.compact_memory(
                messages=messages,
                as_llm=self.chat_model,
                as_llm_formatter=self.formatter,
                as_token_counter=get_token_counter(agent_config),
                language=agent_config.language,
                max_input_length=agent_config.running.max_input_length,
                compact_ratio=cc.memory_compact_ratio,
                previous_summary=previous_summary,
                return_dict=True,
                add_thinking_block=cc.compact_with_thinking_block,
            )

        if isinstance(result, str):
            logger.error(
                "compact_memory returned str instead of dict, "
                f"result: {result[:200]}... "
                "Please install the latest reme package.",
            )
            return result

        if not result.get("is_valid", True):
            unique_id = uuid.uuid4().hex[:8]
            filepath = os.path.join(
                agent_config.workspace_dir,
                f"compact_invalid_{unique_id}.json",
            )
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                logger.error(
                    f"Invalid compact result saved to {filepath}. "
                    f"user_msg: {result.get('user_message', '')[:200]}..., "
                    "history_compact: "
                    f"{result.get('history_compact', '')[:200]}...",
                )
                logger.error(
                    "Please upload the log to github issues",
                )
            except Exception as _e:
                logger.error(f"Failed to save invalid compact result: {_e}")
            return ""

        return result.get("history_compact", "")

    async def summary_memory(self, messages: list[Msg], **_kwargs) -> str:
        """Generate a comprehensive summary of the given messages."""
        self._prepare_model_formatter()

        agent_config = load_agent_config(self.agent_id)
        cc = agent_config.running.context_compact

        set_current_workspace_dir(Path(self.working_dir))
        recent_max_bytes = (
            agent_config.running.tool_result_compact.recent_max_bytes
        )
        set_current_recent_max_bytes(recent_max_bytes)

        return await self._reme.summary_memory(
            messages=messages,
            as_llm=self.chat_model,
            as_llm_formatter=self.formatter,
            as_token_counter=get_token_counter(agent_config),
            toolkit=self.summary_toolkit,
            language=agent_config.language,
            max_input_length=agent_config.running.max_input_length,
            compact_ratio=cc.memory_compact_ratio,
            timezone=load_config().user_timezone or None,
            add_thinking_block=cc.compact_with_thinking_block,
        )

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        """Search stored memories for relevant content."""
        self._warn_if_version_mismatch()
        if self._reme is None or not getattr(self._reme, "_started", False):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="ReMe is not started, report github issue!",
                    ),
                ],
            )
        return await self._reme.memory_search(
            query=query,
            max_results=max_results,
            min_score=min_score,
        )

    def get_in_memory_memory(self, **_kwargs) -> "ReMeInMemoryMemory | None":
        """Retrieve the in-memory memory object with token counting support."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        agent_config = load_agent_config(self.agent_id)
        return self._reme.get_in_memory_memory(
            as_token_counter=get_token_counter(agent_config),
        )

    # ------------------------------------------------------------------
    # Dream-based memory optimization
    # ------------------------------------------------------------------

    async def dream_memory(self, **kwargs) -> None:
        """
        Run one dream-based memory optimization: execute dream task as
        agent query.
        """
        logger.info("running dream-based memory optimization")

        self.dream_path = Path(self.working_dir).absolute() / "dream"
        self.dream_path.mkdir(parents=True, exist_ok=True)

        self._prepare_model_formatter()

        # Load agent config to get model configuration
        agent_config = load_agent_config(self.agent_id)

        set_current_workspace_dir(Path(self.working_dir))
        recent_max_bytes = (
            agent_config.running.tool_result_compact.recent_max_bytes
        )
        set_current_recent_max_bytes(recent_max_bytes)

        # Determine language based on agent config
        language = getattr(agent_config, "language", "zh")

        # Get current date in YYYY-MM-DD format
        current_date = datetime.now().strftime("%Y-%m-%d")

        # Build the dream prompt with working directory and current date
        query_text = self._get_dream_prompt(
            language,
            current_date,
        )

        if not query_text.strip():
            logger.debug("dream optimization skipped: empty query")
            return

        # Ensure model and formatter are prepared
        self._prepare_model_formatter()

        # Create a minimal ReActAgent for dream functionality
        dream_agent = ReActAgent(
            name="DreamOptimizer",
            model=self.chat_model,
            sys_prompt="You are a Dream Memory Organizer specialized"
            " in optimizing long-term memory files.",
            toolkit=self.summary_toolkit,
            formatter=self.formatter,
        )

        # Build request message
        user_msg = Msg(
            name="dream",
            role="user",
            content=[TextBlock(type="text", text=query_text)],
        )

        # Run the dream agent with the query
        async def _run_dream_agent() -> None:
            try:
                response = await dream_agent.reply(user_msg)
                logger.debug(
                    f"Dream agent response: {response.get_text_content()}",
                )
            except Exception as e:
                logger.error(f"Dream agent failed: {e}")
                raise

        try:
            await asyncio.wait_for(
                _run_dream_agent(),
                timeout=300,
            )  # 5 minutes timeout
            logger.info(
                "dream-based memory optimization completed successfully",
            )
        except asyncio.TimeoutError:
            logger.warning("dream-based memory optimization timed out")
        except Exception as e:
            logger.error("dream-based memory optimization failed: %s", repr(e))
            raise

    def _get_dream_prompt(
        self,
        language: str = "zh",
        current_date: str = "",
    ) -> str:
        """Get the dream prompt based on language."""
        prompts = {
            "zh": (
                "现在进入梦境状态，对长期记忆进行安全优化整理。请严格按照以下步骤操作，"
                "确保所有变更都有备份且可回滚。\n\n【核心概念】\n"
                "- DREAM.md：这是你自主管理的长期记忆沉淀文件，包含经过提炼的核心业务决策、用户偏好和高价值经验\n"
                "- MEMORY.md：这是用户可直接编辑的参考文件，包含初始配置和用户手动添加的记忆\n"
                "- 你的任务是维护和优化 DREAM.md，而不是直接修改 MEMORY.md\n\n"
                "【梦境优化原则】\n"
                "1. 极简去冗：严禁记录流水账、Bug修复细节或单次任务。"
                "仅保留“核心业务决策”、“确认的用户偏好”与“高价值可复用经验”。\n"
                "2. 状态覆写：若发现状态变更（如技术栈更改、配置更新），"
                "必须用新状态替换旧状态，严禁新旧矛盾信息并存。\n"
                "3. 归纳整合：主动将零碎的相似规则提炼、合并为通用性强的独立条目。"
                "\n4. 废弃剔除：主动删除已被证伪的假设或不再适用的陈旧条目。\n\n"
                "【安全操作流程】\n"
                "⚠️ 重要：所有操作必须在 `dream/` 目录下进行，严禁直接修改根目录文件！\n\n"
                f"当前日期: {current_date}\n\n"
                "步骤 1 [环境准备]：\n"
                "- 检查是否存在 `dream/` 目录，如果不存在则创建\n"
                "- 读取现有的 `dream/DREAM.md` 文件作为当前记忆基准（如果不存在则从模板创建）\n"
                "- 读取当天的日志文件 `memory/YYYY-MM-DD.md`\n"
                "- 可选：读取根目录的 `MEMORY.md` 作为用户参考信息\n\n"
                "步骤 2 [备份创建]：\n"
                "- 将当前 `dream/DREAM.md` 的内容备份到 "
                "`dream/DREAM_backup_YYYYMMDD_HHMMSS.md`\n\n"
                "步骤 3 [梦境提纯]：\n"
                "- 在梦境中对比新旧内容，严格按照【梦境优化原则】进行去重、替换、剔除和合并\n"
                "- 生成一份全新的记忆内容，并保存到 `dream/DREAM_new.md`\n\n"
                "步骤 4 [验证与提交]：\n"
                "- 仔细检查 `dream/DREAM_new.md` 的内容是否符合优化原则\n"
                "- 确认无误后，将 `dream/DREAM_new.md` 重命名为 `dream/DREAM.md`\n"
                "- 记录操作日志到 `dream/dream_log_YYYYMMDD_HHMMSS.md`\n\n"
                "步骤 5 [苏醒汇报]：\n"
                "从梦境中苏醒后，在对话中向我简短汇报：\n"
                "1) 新增/沉淀了哪些核心记忆\n"
                "2) 修正/删除了哪些过期内容\n"
                "3) 备份文件的位置和名称\n"
                "4) 最终的 DREAM.md 是否成功更新"
            ),
            "en": (
                "Enter dream state for safe memory optimization. Please "
                "strictly follow the steps below to ensure all changes are "
                "backed up and can be rolled back.\n\n"
                "[Core Concepts]\n"
                "- DREAM.md: This is your autonomously managed long-term "
                "memory consolidation file, containing distilled core "
                "business decisions, user preferences, and "
                "high-value experiences\n"
                "- MEMORY.md: This is a user-editable reference file "
                "containing initial configuration and manually added "
                "memories\n"
                "- Your task is to maintain and optimize DREAM.md, NOT "
                "to directly modify MEMORY.md\n\n"
                "[Dream Optimization Principles]\n"
                "1. Extreme Minimalism: Strictly forbid recording daily "
                "routines, specific bug-fix details, or one-off tasks. "
                "Retain ONLY 'core business decisions', 'confirmed user"
                " preferences', and 'high-value reusable experiences'.\n"
                "2. State Overwrite: If a state change is detected (e.g., "
                "tech stack changes, config updates), you MUST replace the "
                "old state with the new one. Contradictory old and new "
                "information must not coexist.\n"
                "3. Inductive Consolidation: Proactively distill and merge "
                "fragmented, similar rules into highly universal, independent "
                "entries.\n"
                "4. Deprecation: Proactively delete hypotheses that have been "
                "proven false or outdated entries that no longer apply.\n\n"
                "[Safe Operation Procedure]\n"
                "⚠️ Important: All operations MUST be performed in the "
                "`dream/` directory! Never modify root directory files "
                "directly!\n\n"
                f"Current date: {current_date}\n\n"
                "Step 1 [Environment Setup]:\n"
                "- Check if `dream/` directory exists, create it if not\n"
                "- Read existing `dream/DREAM.md` file as current memory"
                " baseline (create from template if it doesn't exist)\n"
                "- Read today's log file `memory/YYYY-MM-DD.md`\n"
                "- Optional: Read root directory `MEMORY.md` as user "
                "reference information\n\n"
                "Step 2 [Backup Creation]:\n"
                "- Backup current `dream/DREAM.md` content to "
                "`dream/DREAM_backup_YYYYMMDD_HHMMSS.md`\n\n"
                "Step 3 [Dream Purification]:\n"
                "- Compare old and new content in your dream state, strictly "
                "following [Dream Optimization Principles] to deduplicate, "
                "replace, remove, and merge\n"
                "- Generate entirely new memory content and save it to "
                "`dream/DREAM_new.md`\n\n"
                "Step 4 [Validation and Commit]:\n"
                "- Carefully review `dream/DREAM_new.md` content for "
                "compliance with principles\n"
                "- If confirmed correct, rename `dream/DREAM_new.md` to "
                "`dream/DREAM.md`\n"
                "- Record operation log to "
                "`dream/dream_log_YYYYMMDD_HHMMSS.md`\n\n"
                "Step 5 [Awake Report]:\n"
                "After waking from your dream, briefly report to me in the "
                "chat:\n"
                "1) What core memories were newly added/consolidated\n"
                "2) What outdated content was corrected/deleted\n"
                "3) Backup file locations and names\n"
                "4) Whether the final DREAM.md was successfully updated"
            ),
        }
        return prompts.get(language, prompts["en"])
