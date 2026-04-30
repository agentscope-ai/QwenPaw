# -*- coding: utf-8 -*-

import asyncio
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from qwenpaw.app.knowledge import parsing, retrieval, storage, vector_config
from qwenpaw.app.knowledge.soul import save_soul_knowledge_config
from qwenpaw.app.knowledge import paths as knowledge_paths
from qwenpaw.app.routers.knowledge import upload_document


class KnowledgeBackendTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_workspace = Path(self._temp_dir.name)
        self.original_working_dir = knowledge_paths.WORKING_DIR
        self.original_secret_dir = knowledge_paths.SECRET_DIR
        self.original_load_agent_config = vector_config.load_agent_config
        knowledge_paths.WORKING_DIR = self.temp_workspace
        knowledge_paths.SECRET_DIR = self.temp_workspace / ".secret"

    def tearDown(self) -> None:
        knowledge_paths.WORKING_DIR = self.original_working_dir
        knowledge_paths.SECRET_DIR = self.original_secret_dir
        vector_config.load_agent_config = self.original_load_agent_config
        self._temp_dir.cleanup()

    def test_save_store_uses_knowledge_base_layout(self) -> None:
        now = storage.utc_now()
        store = {
            "knowledge_bases": [
                {
                    "id": "customer-support-kb",
                    "name": "Customer Support",
                    "slug": "customer-support",
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                    "documents": [
                        {
                            "id": "doc-1",
                            "name": "faq.docx",
                            "char_count": 12,
                            "uploaded_at": now,
                            "updated_at": now,
                            "enabled": True,
                            "status": "enabled",
                            "content": "hello world!",
                            "chunks": [
                                {
                                    "id": "chunk-1",
                                    "name": "Chunk 1",
                                    "content": "hello world!",
                                    "char_count": 12,
                                    "enabled": True,
                                    "created_at": now,
                                    "updated_at": now,
                                    "assets": [],
                                }
                            ],
                            "source_filename": "faq.docx",
                            "chunk_config": {
                                "granularity": "balanced",
                                "chunk_size": 1024,
                                "chunk_overlap": 50,
                            },
                            "vector_model_summary": {},
                            "assets": [],
                            "retrieval_config": {},
                        }
                    ],
                }
            ]
        }

        storage.save_store(self.temp_workspace, store)

        self.assertTrue((self.temp_workspace / "knowledge_base" / "meta.json").is_file())
        self.assertTrue(
            (
                self.temp_workspace
                / "knowledge_base"
                / "customer-support-kb"
                / "documents"
                / "doc-1"
                / "meta.json"
            ).is_file()
        )
        self.assertTrue(
            (
                self.temp_workspace
                / "knowledge_base"
                / "customer-support-kb"
                / "documents"
                / "doc-1"
                / "chunks.json"
            ).is_file()
        )

        loaded = storage.load_store(self.temp_workspace)
        self.assertEqual(loaded["knowledge_bases"][0]["id"], "customer-support-kb")
        self.assertEqual(loaded["knowledge_bases"][0]["documents"][0]["chunks"][0]["id"], "chunk-1")

    def test_save_vector_config_splits_conf_and_secret(self) -> None:
        stub_config = SimpleNamespace(
            running=SimpleNamespace(
                reme_light_memory_config=SimpleNamespace(
                    embedding_model_config=SimpleNamespace(
                        model_dump=lambda: {
                            "backend": "custom",
                            "base_url": "",
                            "model_name": "",
                            "dimensions": 1536,
                            "enable_cache": True,
                            "use_dimensions": True,
                            "max_cache_size": 1000,
                            "max_input_length": 8192,
                            "max_batch_size": 16,
                        },
                        api_key="",
                    )
                )
            )
        )
        vector_config.load_agent_config = lambda _agent_id: stub_config

        saved = vector_config.save_knowledge_vector_config(
            "default",
            {
                "embedding_model_config": {
                    "backend": "custom",
                    "api_key": "secret-key",
                    "base_url": "https://embed.example.com",
                    "model_name": "text-embedding-3-large",
                    "dimensions": 1024,
                    "enable_cache": True,
                    "use_dimensions": True,
                    "max_cache_size": 2048,
                    "max_input_length": 4096,
                    "max_batch_size": 32,
                },
                "default_chunk_config": {
                    "granularity": "sentence",
                    "chunk_size": 600,
                    "chunk_overlap": 80,
                },
                "retrieval_config": {
                    "indexing_technique": "high_quality",
                    "search_method": "hybrid",
                    "top_k": 5,
                    "score_threshold_enabled": True,
                    "score_threshold": 0.4,
                    "weights": {
                        "vector_weight": 0.8,
                        "keyword_weight": 0.2,
                    },
                },
            },
        )

        conf_text = (self.temp_workspace / "knowledge_base" / "conf.json").read_text(encoding="utf-8")
        secret_text = (self.temp_workspace / ".secret" / ".knowledge_api_key").read_text(encoding="utf-8")

        self.assertNotIn("secret-key", conf_text)
        self.assertEqual(secret_text, "secret-key")
        self.assertEqual(saved["embedding_model_config"]["api_key"], "")
        self.assertTrue(saved["embedding_model_config"]["api_key_configured"])
        self.assertEqual(saved["embedding_model_config"]["model_name"], "text-embedding-3-large")
        self.assertEqual(saved["default_chunk_config"]["granularity"], "sentence")
        self.assertEqual(saved["default_chunk_config"]["separator"], "\\n\\n")
        self.assertEqual(saved["retrieval_config"]["search_method"], "hybrid")

        updated = vector_config.save_knowledge_vector_config(
            "default",
            {
                "embedding_model_config": {
                    "base_url": "https://embed.example.com/v2",
                    "model_name": "text-embedding-3-large",
                    "api_key": "",
                },
                "default_chunk_config": {},
                "retrieval_config": {},
            },
        )

        self.assertEqual(updated["embedding_model_config"]["api_key"], "")
        self.assertTrue(updated["embedding_model_config"]["api_key_configured"])
        self.assertEqual(
            (self.temp_workspace / ".secret" / ".knowledge_api_key").read_text(encoding="utf-8"),
            "secret-key",
        )

    def test_economy_mode_forces_general_chunk_mode(self) -> None:
        stub_config = SimpleNamespace(
            running=SimpleNamespace(
                reme_light_memory_config=SimpleNamespace(
                    embedding_model_config=SimpleNamespace(
                        model_dump=lambda: {
                            "backend": "custom",
                            "base_url": "",
                            "model_name": "",
                            "dimensions": 1536,
                            "enable_cache": True,
                            "use_dimensions": True,
                            "max_cache_size": 1000,
                            "max_input_length": 8192,
                            "max_batch_size": 16,
                        },
                        api_key="",
                    )
                )
            )
        )
        vector_config.load_agent_config = lambda _agent_id: stub_config

        saved = vector_config.save_knowledge_vector_config(
            "default",
            {
                "embedding_model_config": {},
                "default_chunk_config": {
                    "mode": "parent_child",
                    "parent_chunk_size": 2200,
                    "child_chunk_size": 300,
                },
                "retrieval_config": {
                    "indexing_technique": "economy",
                    "search_method": "keyword",
                },
            },
        )

        self.assertEqual(saved["retrieval_config"]["indexing_technique"], "economy")
        self.assertEqual(saved["default_chunk_config"]["mode"], "general")

    def test_chunk_text_uses_custom_separator(self) -> None:
        first = "a" * 40
        second = "b" * 40
        third = "c" * 40
        chunks = parsing.chunk_text(
            f"{first}<sep>{second}<sep>{third}",
            {
                "mode": "general",
                "granularity": "balanced",
                "separator": "<sep>",
                "chunk_size": 100,
                "chunk_overlap": 0,
            },
        )

        self.assertEqual([chunk["content"] for chunk in chunks], [f"{first}<sep>{second}", third])

        def test_extract_docx_text_includes_table_and_header_content(self) -> None:
                document_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
    <w:body>
        <w:p><w:r><w:t>正文段落</w:t></w:r></w:p>
        <w:tbl>
            <w:tr>
                <w:tc><w:p><w:r><w:t>表格单元格</w:t></w:r></w:p></w:tc>
            </w:tr>
        </w:tbl>
    </w:body>
</w:document>
""".encode("utf-8")
                header_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<w:hdr xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
    <w:p><w:r><w:t>页眉内容</w:t></w:r></w:p>
</w:hdr>
""".encode("utf-8")
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    archive.writestr("word/document.xml", document_xml)
                    archive.writestr("word/header1.xml", header_xml)

                payload = parsing.extract_upload_payload(
                        SimpleNamespace(filename="sample.docx"),
                        buffer.getvalue(),
                        "kb-123456",
                )

                self.assertIn("正文段落", payload["content"])
                self.assertIn("表格单元格", payload["content"])
                self.assertIn("页眉内容", payload["content"])

    def test_retrieval_uses_chunk_embedding_when_available(self) -> None:
        now = storage.utc_now()
        store = {
            "knowledge_bases": [
                {
                    "id": "kb-123456",
                    "name": "Product Docs",
                    "slug": "product-docs",
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                    "documents": [
                        {
                            "id": "doc-1",
                            "name": "faq.md",
                            "char_count": 100,
                            "uploaded_at": now,
                            "updated_at": now,
                            "enabled": True,
                            "status": "enabled",
                            "content": "faq",
                            "chunks": [
                                {
                                    "id": "chunk-a",
                                    "name": "Chunk A",
                                    "content": "refund policy details",
                                    "char_count": 21,
                                    "enabled": True,
                                    "created_at": now,
                                    "updated_at": now,
                                    "assets": [],
                                    "embedding": [1.0, 0.0],
                                },
                                {
                                    "id": "chunk-b",
                                    "name": "Chunk B",
                                    "content": "shipping address update",
                                    "char_count": 23,
                                    "enabled": True,
                                    "created_at": now,
                                    "updated_at": now,
                                    "assets": [],
                                    "embedding": [0.0, 1.0],
                                },
                            ],
                            "source_filename": "faq.md",
                            "chunk_config": {
                                "granularity": "balanced",
                                "chunk_size": 1024,
                                "chunk_overlap": 50,
                            },
                            "vector_model_summary": {},
                            "retrieval_config": {},
                            "assets": [],
                        }
                    ],
                }
            ]
        }
        storage.save_store(self.temp_workspace, store)
        vector_config.save_knowledge_vector_config(
            "default",
            {
                "embedding_model_config": {
                    "backend": "custom",
                    "api_key": "key",
                    "base_url": "https://embed.example.com/v1",
                    "model_name": "text-embedding-test",
                },
                "default_chunk_config": {},
                "retrieval_config": {
                    "indexing_technique": "high_quality",
                    "search_method": "semantic",
                    "top_k": 1,
                },
            },
        )
        save_soul_knowledge_config(
            self.temp_workspace,
            [
                {
                    "id": "kb-123456",
                    "priority": 1,
                    "trigger": "always",
                    "retrieval_top_k": 1,
                    "usage_rule": "Use matching chunks.",
                    "keywords": [],
                }
            ],
        )

        original_embed_texts = retrieval.embed_texts
        retrieval.embed_texts = lambda _config, _texts: [[1.0, 0.0]]
        try:
            context = retrieval.build_retrieval_context(self.temp_workspace, "How do refunds work?")
        finally:
            retrieval.embed_texts = original_embed_texts

        self.assertIsNotNone(context)
        self.assertIn("refund policy details", context or "")
        self.assertNotIn("shipping address update", context or "")

    def test_upload_document_uses_tuned_chunk_and_retrieval_config(self) -> None:
        now = storage.utc_now()
        store = {
            "knowledge_bases": [
                {
                    "id": "kb-123456",
                    "name": "Product Docs",
                    "slug": "product-docs",
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                    "documents": [],
                }
            ]
        }
        storage.save_store(self.temp_workspace, store)
        vector_config.save_knowledge_vector_config(
            "default",
            {
                "embedding_model_config": {
                    "backend": "custom",
                    "api_key": "key",
                    "base_url": "https://embed.example.com/v1",
                    "model_name": "text-embedding-test",
                },
                "default_chunk_config": {
                    "mode": "general",
                    "granularity": "balanced",
                    "separator": "<p>",
                    "chunk_size": 1024,
                    "chunk_overlap": 50,
                },
                "retrieval_config": {
                    "indexing_technique": "high_quality",
                    "search_method": "hybrid",
                    "top_k": 3,
                    "score_threshold_enabled": False,
                    "score_threshold": 0.35,
                    "weights": {
                        "vector_weight": 0.7,
                        "keyword_weight": 0.3,
                    },
                },
            },
        )

        request = SimpleNamespace(state=SimpleNamespace(agent=SimpleNamespace(agent_id="default", workspace_dir=self.temp_workspace)))
        upload_file = SimpleNamespace(filename="faq.md", read=None)
        first = "first block " * 8
        second = "second block " * 8
        third = "third block " * 8
        content = f"{first}<p>{second}<p>{third}"

        async def fake_read() -> bytes:
            return content.encode("utf-8")

        upload_file.read = fake_read

        scheduled: list[object] = []

        def fake_create_task(coro):
            scheduled.append(coro)
            return SimpleNamespace()

        async def run_test() -> None:
            with (
                patch("qwenpaw.app.routers.knowledge.get_agent_for_request", return_value=request.state.agent),
                patch(
                    "qwenpaw.app.routers.knowledge.extract_upload_payload",
                    return_value={"content": content, "assets": []},
                ),
                patch(
                    "qwenpaw.app.routers.knowledge.embed_texts",
                    return_value=[[1.0, 0.0], [0.0, 1.0]],
                ),
                patch(
                    "qwenpaw.app.routers.knowledge.chunk_text_with_model",
                    return_value=[
                        {
                            "id": "chunk-1",
                            "name": "Chunk 1",
                            "content": "first block",
                            "char_count": 11,
                            "enabled": True,
                            "assets": [],
                        },
                        {
                            "id": "chunk-2",
                            "name": "Chunk 2",
                            "content": "second block",
                            "char_count": 12,
                            "enabled": True,
                            "assets": [],
                        },
                    ],
                ) as chunk_mock,
                patch("qwenpaw.app.routers.knowledge.asyncio.create_task", side_effect=fake_create_task),
            ):
                response = await upload_document(
                    "kb-123456",
                    request,
                    file=upload_file,
                    indexing_technique="high_quality",
                    search_method="semantic",
                    top_k=5,
                    score_threshold_enabled=True,
                    score_threshold=0.42,
                    vector_weight=0.6,
                    keyword_weight=0.4,
                    mode="general",
                    granularity="balanced",
                    separator="<p>",
                    chunk_size=100,
                    chunk_overlap=0,
                    parent_separator="\\n\\n",
                    parent_chunk_size=1600,
                    parent_chunk_overlap=160,
                    child_separator="\\n",
                    child_chunk_size=400,
                    child_chunk_overlap=40,
                )
                self.assertEqual(response["document"]["status"], "processing")
                self.assertEqual(len(scheduled), 1)
                await scheduled[0]
                chunk_mock.assert_awaited_once()

        asyncio.run(run_test())

        loaded = storage.load_store(self.temp_workspace)
        document = loaded["knowledge_bases"][0]["documents"][0]
        self.assertEqual(document["retrieval_config"]["search_method"], "semantic")
        self.assertEqual(document["retrieval_config"]["top_k"], 5)
        self.assertTrue(document["retrieval_config"]["score_threshold_enabled"])
        self.assertEqual(document["retrieval_config"]["score_threshold"], 0.42)
        self.assertEqual(document["chunk_config"]["chunk_size"], 100)
        self.assertGreater(len(document["chunks"]), 0)
        self.assertEqual(document["status"], "enabled")

    def test_upload_document_marks_failed_when_ai_chunking_fails(self) -> None:
        now = storage.utc_now()
        store = {
            "knowledge_bases": [
                {
                    "id": "kb-123456",
                    "name": "Product Docs",
                    "slug": "product-docs",
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                    "documents": [],
                }
            ]
        }
        storage.save_store(self.temp_workspace, store)
        vector_config.save_knowledge_vector_config(
            "default",
            {
                "embedding_model_config": {
                    "backend": "custom",
                    "api_key": "key",
                    "base_url": "https://embed.example.com/v1",
                    "model_name": "text-embedding-test",
                },
                "default_chunk_config": {},
                "retrieval_config": {},
            },
        )

        request = SimpleNamespace(
            state=SimpleNamespace(
                agent=SimpleNamespace(agent_id="default", workspace_dir=self.temp_workspace)
            )
        )
        upload_file = SimpleNamespace(filename="faq.md", read=None)

        async def fake_read() -> bytes:
            return b"hello"

        upload_file.read = fake_read
        scheduled: list[object] = []

        def fake_create_task(coro):
            scheduled.append(coro)
            return SimpleNamespace()

        async def run_test() -> None:
            with (
                patch("qwenpaw.app.routers.knowledge.get_agent_for_request", return_value=request.state.agent),
                patch(
                    "qwenpaw.app.routers.knowledge.extract_upload_payload",
                    return_value={"content": "hello", "assets": []},
                ),
                patch(
                    "qwenpaw.app.routers.knowledge.chunk_text_with_model",
                    side_effect=RuntimeError("llm chunk failed"),
                ),
                patch("qwenpaw.app.routers.knowledge.asyncio.create_task", side_effect=fake_create_task),
            ):
                response = await upload_document(
                    "kb-123456",
                    request,
                    file=upload_file,
                    indexing_technique="high_quality",
                    search_method="hybrid",
                    top_k=3,
                    score_threshold_enabled=False,
                    score_threshold=0.35,
                    reranking_enable=False,
                    vector_weight=0.7,
                    keyword_weight=0.3,
                    mode="general",
                    granularity="balanced",
                    separator="\n\n",
                    chunk_size=1024,
                    chunk_overlap=50,
                    parent_separator="\n\n",
                    parent_chunk_size=1600,
                    parent_chunk_overlap=160,
                    child_separator="\n",
                    child_chunk_size=400,
                    child_chunk_overlap=40,
                )
                self.assertEqual(response["document"]["status"], "processing")
                self.assertEqual(len(scheduled), 1)
                await scheduled[0]

        asyncio.run(run_test())

        loaded = storage.load_store(self.temp_workspace)
        document = loaded["knowledge_bases"][0]["documents"][0]
        self.assertEqual(document["status"], "failed")
        self.assertFalse(document["enabled"])
        self.assertIn("llm chunk failed", document["error_message"])

    def test_chunk_text_with_model_uses_llm_boundaries(self) -> None:
        async def run_test() -> None:
            with patch(
                "qwenpaw.app.knowledge.parsing.create_model_and_formatter",
                return_value=(object(), object()),
            ), patch(
                "qwenpaw.app.knowledge.parsing.ReActAgent"
            ) as agent_cls:
                agent = agent_cls.return_value
                agent.reply = AsyncMock(return_value=SimpleNamespace(
                    get_text_content=lambda: '{"split_after": [2, 3]}'
                ))

                chunks = await parsing.chunk_text_with_model(
                    "alpha\n\n beta\n\n gamma",
                    {
                        "mode": "general",
                        "granularity": "paragraph",
                        "separator": "\\n\\n",
                        "chunk_size": 1024,
                        "chunk_overlap": 50,
                    },
                    agent_id="default",
                )

                self.assertEqual([chunk["content"] for chunk in chunks], ["alpha\n\nbeta", "gamma"])

        asyncio.run(run_test())

    def test_chunk_text_with_model_falls_back_on_invalid_llm_output(self) -> None:
        async def run_test() -> None:
            with patch(
                "qwenpaw.app.knowledge.parsing.create_model_and_formatter",
                return_value=(object(), object()),
            ), patch(
                "qwenpaw.app.knowledge.parsing.ReActAgent"
            ) as agent_cls:
                agent = agent_cls.return_value
                agent.reply = AsyncMock(return_value=SimpleNamespace(
                    get_text_content=lambda: '{"split_after": [99]}'
                ))

                chunks = await parsing.chunk_text_with_model(
                    "alpha\n\n beta\n\n gamma",
                    {
                        "mode": "general",
                        "granularity": "paragraph",
                        "separator": "\\n\\n",
                        "chunk_size": 1024,
                        "chunk_overlap": 50,
                    },
                    agent_id="default",
                )

                self.assertEqual(
                    [chunk["content"] for chunk in chunks],
                    ["alpha\n\nbeta\n\ngamma"],
                )

        asyncio.run(run_test())

    def test_chunk_text_with_model_raises_without_fallback(self) -> None:
        async def run_test() -> None:
            with patch(
                "qwenpaw.app.knowledge.parsing.create_model_and_formatter",
                return_value=(object(), object()),
            ), patch(
                "qwenpaw.app.knowledge.parsing.ReActAgent"
            ) as agent_cls:
                agent = agent_cls.return_value
                agent.reply = AsyncMock(return_value=SimpleNamespace(
                    get_text_content=lambda: '{"split_after": [99]}'
                ))

                with self.assertRaises(parsing.KnowledgeChunkModelError):
                    await parsing.chunk_text_with_model(
                        "alpha\n\n beta\n\n gamma",
                        {
                            "mode": "general",
                            "granularity": "paragraph",
                            "separator": "\\n\\n",
                            "chunk_size": 1024,
                            "chunk_overlap": 50,
                        },
                        agent_id="default",
                        fallback_to_heuristic=False,
                    )

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()