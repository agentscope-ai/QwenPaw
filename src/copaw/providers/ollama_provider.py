# -*- coding: utf-8 -*-
"""An OpenAI provider implementation."""

from __future__ import annotations

import os
from typing import Any, List

try:
    import ollama
except ImportError:
    ollama = None  # type: ignore

from agentscope.model import ChatModelBase

from copaw.providers.provider import ModelInfo, Provider


class OllamaProvider(Provider):
    """Provider implementation for Ollama local LLM hosting platform."""

    def model_post_init(self, __context: Any) -> None:
        if not self.base_url:  # type: ignore
            self.base_url = (
                os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
            )
        if self.base_url.endswith("/v1"):
            # For backwards compatibility, if the URL ends with /v1,
            # we strip it to get the base URL
            self.base_url = self.base_url[:-3]

    def _client(self, timeout: float = 5):
        if ollama is None:
            raise ImportError(
                "The 'ollama' Python package is required. You may have "
                "installed Ollama via their CLI or desktop app, but you "
                "also need the Python SDK to manage models from CoPaw. "
                "Please install it with: pip install 'copaw[ollama]'",
            )
        return ollama.AsyncClient(host=self.base_url, timeout=timeout)

    @staticmethod
    def _normalize_models_payload(payload: Any) -> List[ModelInfo]:
        rows = payload.get("models", [])
        models: List[ModelInfo] = []
        for row in rows or []:
            model_id = str(
                getattr(row, "model", ""),
            ).strip()
            model_name = model_id
            if not model_id:
                continue
            models.append(
                ModelInfo(
                    id=model_id,
                    name=model_name,
                ),
            )

        deduped: List[ModelInfo] = []
        seen: set[str] = set()
        for model in models:
            if model.id in seen:
                continue
            seen.add(model.id)
            deduped.append(model)
        return deduped

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check if Ollama provider is reachable with current configuration."""
        try:
            client = self._client(timeout=timeout)
            await client.list()
            return True, ""
        except ImportError:
            return False, "Ollama Python SDK is not installed"
        except ConnectionError:
            return False, f"Failed to connect to Ollama at `{self.base_url}`"
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to `{self.base_url}`",
            )

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch available models and cache them on this provider instance."""
        try:
            client = self._client(timeout=timeout)
            payload = await client.list()
            models = self._normalize_models_payload(payload)
            return models
        except (ImportError, ConnectionError, OSError, RuntimeError):
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable."""
        target = (model_id or "").strip()
        if not target:
            return False, "Empty model ID"
        try:
            client = self._client(timeout=timeout)
            await client.chat(
                model=target,
                messages=[{"role": "user", "content": "ping"}],
                options={"num_predict": 1},
            )
            return True, ""
        except ImportError:
            return False, "Ollama Python SDK is not installed"
        except ConnectionError:
            return False, f"Failed to connect to Ollama at `{self.base_url}`"
        except Exception:
            return False, f"Unknown exception when connecting to `{target}`"

    async def add_model(
        self,
        model_info: ModelInfo,
        target: str = "models",
        timeout: float = 36000,
    ) -> tuple[bool, str]:
        """Ollama models are added by pulling from a registry, so here we
        interpret "adding" a model as pulling it from the registry.
        The model_info.id is expected to be in the format of
        "registry/model:tag" or "registry/model".
        """
        if model_info.id in {
            model.id for model in self.extra_models  # type: ignore [has-type]
        }:
            return False, f"Model '{model_info.id}' already exists"
        client = self._client(timeout=timeout)
        try:
            await client.pull(model=model_info.id)
        except ImportError:
            return False, "Ollama Python SDK is not installed"
        except ConnectionError:
            return False, f"Failed to connect to Ollama at `{self.base_url}`"
        except Exception:
            return False, f"Failed to pull model '{model_info.id}'"
        self.extra_models = await self.fetch_models()
        return True, ""

    async def delete_model(
        self,
        model_id: str,
        timeout: float = 60,
    ) -> tuple[bool, str]:
        client = self._client(timeout=timeout)
        try:
            await client.delete(model=model_id)
        except ImportError:
            return False, "Ollama Python SDK is not installed"
        except ConnectionError:
            return False, f"Failed to connect to Ollama at `{self.base_url}`"
        except Exception:
            return False, f"Failed to delete model '{model_id}'"
        self.extra_models = await self.fetch_models()
        return True, ""

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from .openai_chat_model_compat import OpenAIChatModelCompat

        if self.base_url.endswith("/"):
            openai_compatible_url = self.base_url[:-1] + "/v1"
        else:
            openai_compatible_url = self.base_url + "/v1"

        return OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            stream_tool_parsing=False,
            client_kwargs={"base_url": openai_compatible_url},
            generate_kwargs=self.generate_kwargs,
        )
