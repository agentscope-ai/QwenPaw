# -*- coding: utf-8 -*-
"""ReMeLight-backed memory manager for agents."""
import importlib.metadata
import json
import logging
import platform
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock, ToolResultBlock, ToolUseBlock
from agentscope.tool import Toolkit, ToolResponse

from .base_memory_manager import BaseMemoryManager, memory_registry
from .prompts import (
    MEMORY_GUIDANCE_ZH,
    MEMORY_GUIDANCE_EN,
    DREAM_OPTIMIZATION_ZH,
    DREAM_OPTIMIZATION_EN,
)
from ..model_factory import create_model_and_formatter
from ..utils import get_token_counter
from ...config import load_config
from ...config.config import load_agent_config
from ...config.context import (
    set_current_workspace_dir,
    set_current_recent_max_bytes,
)
from ...constant import EnvVarLoader

logger = logging.getLogger(__name__)

_REME_STORE_VERSION = "v1"
_EXPECTED_REME_VERSION = "0.3.1.8"
# Maximum number of tokens from query splitting
MAX_QUERY_TOKENS = 50


def _detect_memory_manager_backend() -> str:
    """Detect the memory store backend from environment variables.

    Resolves ``MEMORY_STORE_BACKEND`` with the following priority:
    - ``local``: always used on Windows
    - ``chroma``: used when ``chromadb`` is importable (non-Windows)
    - falls back to ``local`` when ``chromadb`` is unavailable

    Returns:
        Backend name string: ``"local"``, ``"chroma"``, or any explicitly
        configured value.
    """
    backend_env = EnvVarLoader.get_str("MEMORY_STORE_BACKEND", "auto")
    if backend_env != "auto":
        return backend_env

    if platform.system() == "Windows":
        return "local"

    try:
        import chromadb  # noqa: F401 pylint: disable=unused-import

        return "chroma"
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
        return "local"


@memory_registry.register("remelight")
class ReMeLightMemoryManager(BaseMemoryManager):
    """Memory manager backed by ReMeLight.

    Delegates lifecycle, search, and compaction to a ``ReMeLight`` instance
    (``self._reme``).
    """

    def __init__(self, working_dir: str, agent_id: str):
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._reme_version_ok: bool = self._check_reme_version()
        self._reme = None

        logger.info(
            f"ReMeLightMemoryManager init: "
            f"agent_id={agent_id}, working_dir={working_dir}",
        )

        memory_manager_backend = _detect_memory_manager_backend()

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
        reme_cfg = agent_config.running.reme_light_memory_config
        rebuild_on_start = reme_cfg.rebuild_memory_index_on_start

        store_name = "memory"
        effective_rebuild = self._resolve_rebuild_on_start(
            working_dir=working_dir,
            store_version=_REME_STORE_VERSION,
            rebuild_on_start=rebuild_on_start,
        )

        recursive_file_watcher = reme_cfg.recursive_file_watcher

        self._reme = ReMeLight(
            working_dir=working_dir,
            default_embedding_model_config=emb_config,
            default_file_store_config={
                "backend": memory_manager_backend,
                "store_name": store_name,
                "vector_enabled": vector_enabled,
                "fts_enabled": fts_enabled,
            },
            default_file_watcher_config={
                "rebuild_index_on_start": effective_rebuild,
                "recursive": recursive_file_watcher,
            },
        )

        self.summary_toolkit = Toolkit()
        from qwenpaw.agents.tools import (
            read_file,
            write_file,
            edit_file,
        )  # noqa: PLC0415

        self.summary_toolkit.register_tool_function(read_file)
        self.summary_toolkit.register_tool_function(write_file)
        self.summary_toolkit.register_tool_function(edit_file)

    @staticmethod
    def _mask_key(key: str) -> str:
        """Mask an API key, showing only the first 5 characters."""
        return key[:5] + "*" * (len(key) - 5) if len(key) > 5 else key

    @staticmethod
    def _check_reme_version() -> bool:
        """Return ``False`` (and warn) when the installed reme-ai version
        does not match the expected version."""
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

    def get_embedding_config(self) -> dict:
        """Return embedding config: config > env var > default."""
        self._warn_if_version_mismatch()
        cfg = load_agent_config(
            self.agent_id,
        ).running.reme_light_memory_config.embedding_model_config
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

    @staticmethod
    def _resolve_rebuild_on_start(
        working_dir: str,
        store_version: str,
        rebuild_on_start: bool,
    ) -> bool:
        """Return effective ``rebuild_index_on_start`` value.

        Uses a sentinel file ``.reme_store_{store_version}`` to detect whether
        the current store version has been initialized. Forces a one-time
        rebuild when the sentinel is absent. Bump *_REME_STORE_VERSION* to
        trigger another one-time rebuild on next start.
        """
        sentinel_name = f".reme_store_{store_version}"
        sentinel_path = Path(working_dir) / sentinel_name

        if sentinel_path.exists():
            return rebuild_on_start

        logger.info(
            f"Sentinel '{sentinel_name}' not found, forcing rebuild.",
        )

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
            f"ReMeLightMemoryManager closed: agent_id={self.agent_id}, "
            f"result={result}",
        )
        return result

    def get_memory_prompt(self, language: str = "zh") -> str:
        """Return the memory guidance prompt for the system prompt."""
        prompts = {"zh": MEMORY_GUIDANCE_ZH, "en": MEMORY_GUIDANCE_EN}
        return prompts.get(language, MEMORY_GUIDANCE_EN)

    def list_memory_tools(self):
        """Return memory tool functions to register with the agent toolkit."""
        return [
            self.memory_search,
            self.add_memory,
            self.delete_memory,
            self.update_memory,
        ]

    @staticmethod
    def _is_cjk(char: str) -> bool:
        """Check if a character is CJK (Chinese/Japanese/Korean)."""
        cp = ord(char)
        return (
            (0x4E00 <= cp <= 0x9FFF)
            or (0x3400 <= cp <= 0x4DBF)  # CJK Unified Ideographs
            or (  # CJK Extension A
                0xF900 <= cp <= 0xFAFF
            )  # CJK Compatibility Ideographs
        )

    def tokenize_query(
        self,
        query: str,
        max_tokens: int = MAX_QUERY_TOKENS,
    ) -> list[str]:
        """Tokenize query: CJK chars as 1-gram, non-CJK split by whitespace.

        Args:
            query: The search query string (non-empty)
            max_tokens: Maximum number of tokens to return

        Returns:
            List of tokens, limited to max_tokens
        """
        tokens = []

        for word in query.split():
            if not word:
                continue

            # Fast path: pure non-CJK word, add directly
            if not any(self._is_cjk(c) for c in word):
                tokens.append(word)
                if len(tokens) >= max_tokens:
                    break
                continue

            # Mixed CJK/non-CJK: iterate chars within the word
            non_cjk_buffer = []
            for char in word:
                if self._is_cjk(char):
                    if non_cjk_buffer:
                        tokens.append("".join(non_cjk_buffer))
                        non_cjk_buffer = []
                    tokens.append(char)
                else:
                    non_cjk_buffer.append(char)

                if len(tokens) >= max_tokens:
                    break

            if non_cjk_buffer and len(tokens) < max_tokens:
                tokens.append("".join(non_cjk_buffer))

            if len(tokens) >= max_tokens:
                break

        return tokens[:max_tokens]

    async def _rewrite_query(self, query: str) -> str:
        """Rewrite the query using LLM to improve retrieval recall.

        Expands the original query with related keywords and clarifies
        the intent for better semantic and keyword matching.
        """
        if not query or len(query) < 4:
            return query

        try:
            from ..model_factory import create_model_and_formatter

            chat_model, formatter = create_model_and_formatter(self.agent_id)
            agent_config = load_agent_config(self.agent_id)
            language = getattr(agent_config, "language", "zh")

            rewrite_prompt = (
                "You are a search query optimizer. "
                f"Rewrite the following user query to improve retrieval recall. "
                f"Extract key entities and expand with relevant technical terms or synonyms. "
                f"Output ONLY the optimized query string, no explanations.\n\n"
                f"Original query: {query}\n"
                f"Language: {language}\n"
                f"Optimized query:"
            )

            from agentscope.message import Msg, TextBlock

            response = await chat_model(
                [Msg(name="user", role="user", content=[TextBlock(type="text", text=rewrite_prompt)])]
            )

            optimized = response.content[0].get("text", "").strip() if isinstance(response.content, list) else str(response.content).strip()
            if optimized:
                logger.info(f"Query rewritten: '{query}' -> '{optimized}'")
                return optimized
        except Exception as e:
            logger.warning(f"Query rewrite failed, using original: {e}")

        return query

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
        rewrite: bool = True,
    ) -> ToolResponse:
        """
        Search MEMORY.md and memory/*.md files semantically.

        Use this tool before answering questions about prior work,
        decisions, dates, people, preferences, or todos. Returns top
        relevant snippets with file paths and line numbers.

        Args:
            query (`str`):
                The semantic search query to find relevant memory snippets.
            max_results (`int`, optional):
                Maximum number of search results to return. Defaults to 5.
            min_score (`float`, optional):
                Minimum similarity score for results. Defaults to 0.1.
            rewrite (`bool`, optional):
                Whether to rewrite the query for better recall. Defaults to True.

        Returns:
            `ToolResponse`:
                Search results formatted with paths, line numbers, and
                content.
        """
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

        try:
            if rewrite:
                query = await self._rewrite_query(query)
            query_final = " ".join(self.tokenize_query(query))
            logger.info(f"Tokenized query: {query_final}")
        except Exception as e:
            logger.exception(f"Failed to tokenize query: {e} query={query}")
            query_final = query

        return await self._reme.memory_search(
            query=query_final,
            max_results=max_results,
            min_score=min_score,
        )

    async def add_memory(
        self,
        content: str,
        when_to_use: str = "",
        score: float = 0.5,
    ) -> ToolResponse:
        """Add a new memory entry to the vector store.

        Use this tool to save important decisions, user preferences,
        project context, or lessons learned. This automatically indexes
        the content for future semantic search.

        Args:
            content (`str`): The memory content to store.
            when_to_use (`str`, optional): When this memory should be used.
            score (`float`, optional): Importance score (0.0-1.0). Defaults to 0.5.

        Returns:
            `ToolResponse`: Confirmation with the new memory ID.
        """
        self._warn_if_version_mismatch()
        if self._reme is None or not getattr(self._reme, "_started", False):
            return ToolResponse(
                content=[TextBlock(type="text", text="ReMe is not started.")],
            )
        try:
            node = await self._reme.add_memory(
                memory_content=content,
                when_to_use=when_to_use,
                score=score,
            )
            memory_id = getattr(node, "memory_id", "unknown")
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Memory added successfully. ID: {memory_id}",
                    ),
                ],
            )
        except Exception as e:
            logger.exception(f"add_memory failed: {e}")
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Failed to add memory: {e}")],
            )

    async def delete_memory(self, memory_id: str) -> ToolResponse:
        """Delete a memory entry by its ID.

        Use this to remove outdated or incorrect memories from the store.

        Args:
            memory_id (`str`): The ID of the memory to delete.

        Returns:
            `ToolResponse`: Confirmation of deletion.
        """
        self._warn_if_version_mismatch()
        if self._reme is None or not getattr(self._reme, "_started", False):
            return ToolResponse(
                content=[TextBlock(type="text", text="ReMe is not started.")],
            )
        try:
            await self._reme.delete_memory(memory_id)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Memory {memory_id} deleted successfully.",
                    ),
                ],
            )
        except Exception as e:
            logger.exception(f"delete_memory failed: {e}")
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Failed to delete memory: {e}")],
            )

    async def update_memory(
        self,
        memory_id: str,
        content: str | None = None,
        when_to_use: str | None = None,
        score: float | None = None,
    ) -> ToolResponse:
        """Update an existing memory entry.

        Use this to correct or expand previously stored memories.
        Only provide fields you want to change.

        Args:
            memory_id (`str`): The ID of the memory to update.
            content (`str`, optional): New memory content.
            when_to_use (`str`, optional): New usage description.
            score (`float`, optional): New importance score.

        Returns:
            `ToolResponse`: Confirmation of update.
        """
        self._warn_if_version_mismatch()
        if self._reme is None or not getattr(self._reme, "_started", False):
            return ToolResponse(
                content=[TextBlock(type="text", text="ReMe is not started.")],
            )
        try:
            await self._reme.update_memory(
                memory_id=memory_id,
                memory_content=content,
                when_to_use=when_to_use,
                score=score,
            )
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Memory {memory_id} updated successfully.",
                    ),
                ],
            )
        except Exception as e:
            logger.exception(f"update_memory failed: {e}")
            return ToolResponse(
                content=[
                    TextBlock(type="text", text=f"Failed to update memory: {e}"),
                ],
            )

    async def summarize(self, messages: list[Msg], **_kwargs) -> str:
        """Generate a summary of the given messages and persist to memory."""
        agent_config = load_agent_config(self.agent_id)
        light_ctx = agent_config.running.light_context_config
        cc = light_ctx.context_compact_config
        chat_model, formatter = create_model_and_formatter(self.agent_id)

        set_current_workspace_dir(Path(self.working_dir))
        pruning_cfg = light_ctx.tool_result_pruning_config
        recent_max_bytes = pruning_cfg.pruning_recent_msg_max_bytes
        set_current_recent_max_bytes(recent_max_bytes)

        return await self._reme.summary_memory(
            messages=messages,
            as_llm=chat_model,
            as_llm_formatter=formatter,
            as_token_counter=get_token_counter(agent_config),
            toolkit=self.summary_toolkit,
            language=agent_config.language,
            max_input_length=agent_config.running.max_input_length,
            compact_ratio=cc.compact_threshold_ratio,
            timezone=load_config().user_timezone or None,
            add_thinking_block=cc.compact_with_thinking_block,
        )

    async def retrieve(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **_kwargs,
    ) -> dict | None:
        """Retrieve relevant memory and return updated kwargs dict.

        Args:
            messages: One or more conversation messages used as the query.
            agent_name: Agent name for constructing Msg.

        Returns:
            None: No relevant memory found, caller should not update kwargs.
            dict: {"msg": msgs + [assistant_msg, tool_result_msg]} to merge
                with kwargs via {**kwargs, **result}.
        """
        msgs: list[Msg] = (
            [messages] if isinstance(messages, Msg) else list(messages)
        )

        # Build query from the newest messages, preserving tail.
        query_parts: list[str] = []
        total = 0
        for msg in reversed(msgs):
            remaining = 100 - total
            if remaining <= 0:
                break

            text = (msg.get_text_content() or "").strip()
            if not text:
                continue

            chunk = text[:remaining]
            query_parts.insert(0, chunk)
            total += len(chunk)

        query = " ".join(query_parts).strip()
        if not query:
            return None

        agent_config = load_agent_config(self.agent_id)
        reme_cfg = agent_config.running.reme_light_memory_config
        ms = reme_cfg.auto_memory_search_config
        max_results = ms.max_results
        min_score = ms.min_score

        try:
            result = await self.memory_search(
                query=query,
                max_results=max_results,
                min_score=min_score,
                rewrite=False,  # Already processed query from conversation context
            )
            content_blocks = result.content

            text_content = "\n".join(
                b.get("text", "")
                for b in content_blocks
                if isinstance(b, dict) and b.get("text")
            )
            if not text_content:
                return None

            # Construct assistant_msg and tool_result_msg
            _id = uuid.uuid4().hex
            tool_use_input = {
                "query": query,
                "max_results": max_results,
                "min_score": min_score,
            }

            assistant_msg = Msg(
                name=agent_name,
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="Searching memory for relevant context...",
                    ),
                    ToolUseBlock(
                        type="tool_use",
                        id=_id,
                        name="memory_search",
                        input=tool_use_input,
                        raw_input=json.dumps(
                            tool_use_input,
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )

            tool_result_msg = Msg(
                name=agent_name,
                role="system",
                content=[
                    ToolResultBlock(
                        type="tool_result",
                        id=_id,
                        name="memory_search",
                        output=[TextBlock(type="text", text=text_content)],
                    ),
                ],
            )

            return {"msg": msgs + [assistant_msg, tool_result_msg]}

        except Exception as e:
            logger.exception(f"memory_search failed: {e}")
            return None

    async def dream(self, **kwargs) -> None:
        """Run one dream-based memory optimization pass."""
        logger.info("running dream-based memory optimization")

        agent_config = load_agent_config(self.agent_id)
        light_ctx = agent_config.running.light_context_config
        chat_model, formatter = create_model_and_formatter(self.agent_id)

        set_current_workspace_dir(Path(self.working_dir))
        pruning_cfg = light_ctx.tool_result_pruning_config
        recent_max_bytes = pruning_cfg.pruning_recent_msg_max_bytes
        set_current_recent_max_bytes(recent_max_bytes)

        language = getattr(agent_config, "language", "zh")
        current_date = datetime.now().strftime("%Y-%m-%d")

        prompts = {"zh": DREAM_OPTIMIZATION_ZH, "en": DREAM_OPTIMIZATION_EN}
        template = prompts.get(language, DREAM_OPTIMIZATION_EN)
        query_text = template.format(current_date=current_date)

        if not query_text.strip():
            logger.debug("dream optimization skipped: empty query")
            return

        backup_path = Path(self.working_dir).absolute() / "backup"
        backup_path.mkdir(parents=True, exist_ok=True)

        memory_file = Path(self.working_dir) / "MEMORY.md"
        if memory_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"memory_backup_{timestamp}.md"
            backup_file = backup_path / backup_filename
            try:
                shutil.copyfile(memory_file, backup_file)
                logger.info(f"Created MEMORY.md backup: {backup_file}")
            except Exception as e:
                logger.error(f"Failed to create MEMORY.md backup: {e}")
        else:
            logger.debug("No existing MEMORY.md file to backup")

        dream_agent = ReActAgent(
            name="DreamOptimizer",
            model=chat_model,
            sys_prompt="You are a Dream Memory Organizer specialized"
            " in optimizing long-term memory files.",
            toolkit=self.summary_toolkit,
            formatter=formatter,
        )
        dream_agent.set_console_output_enabled(False)

        user_msg = Msg(
            name="dream",
            role="user",
            content=[TextBlock(type="text", text=query_text)],
        )

        try:
            response = await dream_agent.reply(user_msg)
            logger.info(f"Dream agent response: {response.get_text_content()}")
        except Exception as e:
            logger.exception(f"dream-based memory optimization failed: {e}")
            raise
