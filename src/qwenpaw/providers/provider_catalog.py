# -*- coding: utf-8 -*-
"""Built-in provider catalog and default model definitions."""

from typing import List

from .anthropic_provider import AnthropicProvider
from .dashscope_provider import DashScopeProvider
from .gemini_provider import GeminiProvider
from .lmstudio_provider import LMStudioProvider
from .modelscope_provider import ModelScopeProvider
from .ollama_provider import OllamaProvider
from .openai_provider import (
    GitHubModelsProvider,
    KiloProvider,
    OpenAIProvider,
    OpenCodeProvider,
)
from .model_catalog import models_for_catalog_key
from .openai_response_provider import OpenAIResponseProvider
from .openrouter_provider import OpenRouterProvider
from .provider import ModelInfo, Provider
from .provider_discovery_policy import apply_discovery_policy

# -------------------------------------------------------
# Built-in provider definitions and their default models.
# -------------------------------------------------------


def _models(catalog_key: str) -> List[ModelInfo]:
    return models_for_catalog_key(catalog_key)


MODELSCOPE_MODELS = _models("MODELSCOPE_MODELS")
DASHSCOPE_MODELS = _models("DASHSCOPE_MODELS")
MIMO_TOKENPLAN_MODELS = _models("MIMO_TOKENPLAN_MODELS")
ALIYUN_TOKENPLAN_MODELS = _models("ALIYUN_TOKENPLAN_MODELS")
ALIYUN_CODINGPLAN_MODELS = _models("ALIYUN_CODINGPLAN_MODELS")
ZHIPU_MODELS = _models("ZHIPU_MODELS")
OPENAI_MODELS = _models("OPENAI_MODELS")
KILO_MODELS = _models("KILO_MODELS")
OPENCODE_MODELS = _models("OPENCODE_MODELS")
AZURE_OPENAI_MODELS = _models("AZURE_OPENAI_MODELS")
MINIMAX_MODELS = _models("MINIMAX_MODELS")
KIMI_MODELS = _models("KIMI_MODELS")
DEEPSEEK_MODELS = _models("DEEPSEEK_MODELS")
VOLCENGINE_MODELS = _models("VOLCENGINE_MODELS")
VOLCENGINE_CODINGPLAN_MODELS = _models("VOLCENGINE_CODINGPLAN_MODELS")
ANTHROPIC_MODELS = _models("ANTHROPIC_MODELS")
GEMINI_MODELS = _models("GEMINI_MODELS")
KIMI_CODINGPLAN_MODELS = _models("KIMI_CODINGPLAN_MODELS")
GITHUB_MODELS_MODELS = _models("GITHUB_MODELS_MODELS")

PROVIDER_MODELSCOPE = ModelScopeProvider(
    id="modelscope",
    name="ModelScope",
    base_url="https://api-inference.modelscope.cn/v1",
    api_key_prefix="ms",
    models=MODELSCOPE_MODELS,
    support_model_discovery=True,
    freeze_url=True,
)

PROVIDER_DASHSCOPE = DashScopeProvider(
    id="dashscope",
    name="DashScope",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key_prefix="sk",
    models=DASHSCOPE_MODELS,
    support_model_discovery=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="dashscope",
    meta={
        "base_url_options": [
            {
                "label": "China (Beijing)",
                "value": "https://dashscope.aliyuncs.com/"
                "compatible-mode/v1",
            },
            {
                "label": "International (Singapore)",
                "value": "https://dashscope-intl.aliyuncs.com/"
                "compatible-mode/v1",
            },
            {
                "label": "US (Virginia)",
                "value": "https://dashscope-us.aliyuncs.com/"
                "compatible-mode/v1",
            },
        ],
    },
)

PROVIDER_ALIYUN_CODINGPLAN = OpenAIProvider(
    id="aliyun-codingplan",
    name="Aliyun Coding Plan (China)",
    base_url="https://coding.dashscope.aliyuncs.com/v1",
    api_key_prefix="sk-sp",
    models=ALIYUN_CODINGPLAN_MODELS,
    support_connection_check=False,
    freeze_url=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="coding_plan_cn",
)

PROVIDER_ALIYUN_CODINGPLAN_INTL = OpenAIProvider(
    id="aliyun-codingplan-intl",
    name="Aliyun Coding Plan (International)",
    base_url="https://coding-intl.dashscope.aliyuncs.com/v1",
    api_key_prefix="sk-sp",
    models=ALIYUN_CODINGPLAN_MODELS,
    support_connection_check=False,
    freeze_url=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="coding_plan_intl",
)

PROVIDER_ALIYUN_TOKENPLAN = OpenAIProvider(
    id="aliyun-tokenplan",
    name="Aliyun Token Plan",
    base_url=(
        "https://token-plan.cn-beijing.maas.aliyuncs.com/" "compatible-mode/v1"
    ),
    api_key_prefix="sk-sp",
    models=ALIYUN_TOKENPLAN_MODELS,
    support_connection_check=False,
    freeze_url=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="token_plan",
)

PROVIDER_ALIYUN_TOKENPLAN_INTL = OpenAIProvider(
    id="aliyun-tokenplan-intl",
    name="Aliyun Token Plan (International)",
    base_url=(
        "https://token-plan.ap-southeast-1.maas.aliyuncs.com/"
        "compatible-mode/v1"
    ),
    api_key_prefix="sk-sp",
    models=ALIYUN_TOKENPLAN_MODELS,
    support_connection_check=False,
    freeze_url=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="token_plan_intl",
)

PROVIDER_ZHIPU_CN = OpenAIProvider(
    id="zhipu-cn",
    name="Zhipu (BigModel)",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    api_key_prefix="",
    models=ZHIPU_MODELS,
    freeze_url=True,
    provider_group="zhipu",
    provider_group_name="Zhipu",
    provider_variant="open_platform_cn",
    meta={"is_free_tier": True},
)

PROVIDER_ZHIPU_CN_CODINGPLAN = OpenAIProvider(
    id="zhipu-cn-codingplan",
    name="Zhipu Coding Plan (BigModel)",
    base_url="https://open.bigmodel.cn/api/coding/paas/v4",
    api_key_prefix="",
    models=ZHIPU_MODELS,
    freeze_url=True,
    support_connection_check=False,
    provider_group="zhipu",
    provider_group_name="Zhipu",
    provider_variant="coding_plan_cn",
)

PROVIDER_ZHIPU_INTL = OpenAIProvider(
    id="zhipu-intl",
    name="Zhipu (Z.AI)",
    base_url="https://api.z.ai/api/paas/v4",
    api_key_prefix="",
    models=ZHIPU_MODELS,
    freeze_url=True,
    provider_group="zhipu",
    provider_group_name="Zhipu",
    provider_variant="open_platform_intl",
)

PROVIDER_ZHIPU_INTL_CODINGPLAN = OpenAIProvider(
    id="zhipu-intl-codingplan",
    name="Zhipu Coding Plan (Z.AI)",
    base_url="https://api.z.ai/api/coding/paas/v4",
    api_key_prefix="",
    models=ZHIPU_MODELS,
    freeze_url=True,
    support_connection_check=False,
    provider_group="zhipu",
    provider_group_name="Zhipu",
    provider_variant="coding_plan_intl",
)

PROVIDER_QWENPAW = OpenAIProvider(
    id="qwenpaw-local",
    name="QwenPaw Local",
    is_local=True,
    require_api_key=False,
)

PROVIDER_OPENAI = OpenAIProvider(
    id="openai",
    name="OpenAI",
    base_url="https://api.openai.com/v1",
    api_key_prefix="sk-",
    models=OPENAI_MODELS,
    support_model_discovery=True,
    freeze_url=True,
)

PROVIDER_OPENAI_RESPONSE = OpenAIResponseProvider(
    id="openai-response",
    name="OpenAI (Response API)",
    base_url="https://api.openai.com/v1",
    api_key_prefix="sk-",
    chat_model="OpenAIResponseModel",
    models=OPENAI_MODELS,
    support_model_discovery=True,
    freeze_url=True,
)

PROVIDER_OPENCODE = OpenCodeProvider(
    id="opencode",
    name="OpenCode",
    base_url="https://opencode.ai/zen/v1",
    api_key_prefix="",
    models=OPENCODE_MODELS,
    require_api_key=False,
    meta={
        "base_url_options": [
            {"label": "OpenCode", "value": "https://opencode.ai/zen/v1"},
            {"label": "OpenCode Go", "value": "https://opencode.ai/zen/go/v1"},
        ],
        "is_free_tier": True,
    },
    freeze_url=False,
)

PROVIDER_KILO = KiloProvider(
    id="kilo",
    name="Kilo Code",
    base_url="https://api.kilo.ai/api/gateway",
    api_key_prefix="",
    models=KILO_MODELS,
    require_api_key=False,
    meta={"is_free_tier": True},
    freeze_url=True,
)

PROVIDER_AZURE_OPENAI = OpenAIProvider(
    id="azure-openai",
    name="Azure OpenAI",
    api_key_prefix="",
    models=AZURE_OPENAI_MODELS,
)

PROVIDER_MINIMAX = AnthropicProvider(
    id="minimax",
    name="MiniMax (International)",
    base_url="https://api.minimax.io/anthropic",
    models=MINIMAX_MODELS,
    chat_model="AnthropicChatModel",
    freeze_url=True,
    support_connection_check=False,
    provider_group="minimax",
    provider_group_name="MiniMax",
    provider_variant="open_platform_intl",
)

PROVIDER_MINIMAX_CN = AnthropicProvider(
    id="minimax-cn",
    name="MiniMax (China)",
    base_url="https://api.minimaxi.com/anthropic",
    models=MINIMAX_MODELS,
    chat_model="AnthropicChatModel",
    freeze_url=True,
    support_connection_check=False,
    provider_group="minimax",
    provider_group_name="MiniMax",
    provider_variant="open_platform_cn",
)

PROVIDER_KIMI_CN = OpenAIProvider(
    id="kimi-cn",
    name="Kimi (China)",
    base_url="https://api.moonshot.cn/v1",
    api_key_prefix="",
    models=KIMI_MODELS,
    support_model_discovery=True,
    merge_with_catalog=True,
    freeze_url=True,
    provider_group="kimi",
    provider_group_name="Kimi",
    provider_variant="open_platform_cn",
)

PROVIDER_KIMI_INTL = OpenAIProvider(
    id="kimi-intl",
    name="Kimi (International)",
    base_url="https://api.moonshot.ai/v1",
    api_key_prefix="",
    models=KIMI_MODELS,
    support_model_discovery=True,
    merge_with_catalog=True,
    freeze_url=True,
    provider_group="kimi",
    provider_group_name="Kimi",
    provider_variant="open_platform_intl",
)

PROVIDER_KIMI_CODINGPLAN = OpenAIProvider(
    id="kimi-codingplan",
    name="Kimi Coding Plan",
    base_url="https://api.kimi.com/coding/v1",
    api_key_prefix="sk-kimi-",
    models=KIMI_CODINGPLAN_MODELS,
    freeze_url=True,
    support_connection_check=False,
    provider_group="kimi",
    provider_group_name="Kimi",
    provider_variant="coding_plan",
)

PROVIDER_DEEPSEEK = OpenAIProvider(
    id="deepseek",
    name="DeepSeek",
    base_url="https://api.deepseek.com",
    api_key_prefix="sk-",
    models=DEEPSEEK_MODELS,
    support_model_discovery=True,
    merge_with_catalog=True,
    freeze_url=True,
)

PROVIDER_ANTHROPIC = AnthropicProvider(
    id="anthropic",
    name="Anthropic",
    base_url="https://api.anthropic.com",
    api_key_prefix="sk-ant-",
    models=ANTHROPIC_MODELS,
    chat_model="AnthropicChatModel",
    support_model_discovery=True,
    freeze_url=False,
)

PROVIDER_GEMINI = GeminiProvider(
    id="gemini",
    name="Google Gemini",
    base_url="https://generativelanguage.googleapis.com",
    api_key_prefix="",
    models=GEMINI_MODELS,
    chat_model="GeminiChatModel",
    support_model_discovery=True,
    freeze_url=True,
    meta={
        "is_free_tier": True,
    },
)

PROVIDER_OLLAMA = OllamaProvider(
    id="ollama",
    name="Ollama",
    is_local=True,
    require_api_key=False,
    support_model_discovery=True,
    generate_kwargs={"max_tokens": None},
)

PROVIDER_OPENROUTER = OpenRouterProvider(
    id="openrouter",
    name="OpenRouter",
    base_url="https://openrouter.ai/api/v1",
    api_key_prefix="sk-or-v1-",
    models=[],
    freeze_url=True,
    support_model_discovery=True,
    meta={
        "supports_oauth": True,
        "is_free_tier": True,
    },
)

PROVIDER_GITHUB_MODELS = GitHubModelsProvider(
    id="github-models",
    name="GitHub Models",
    base_url="https://models.github.ai/inference",
    api_key_prefix="ghp_",
    api_key_prefixes=["ghp_", "github_pat_"],
    models=GITHUB_MODELS_MODELS,
    freeze_url=False,
    meta={
        "is_free_tier": True,
    },
)


PROVIDER_LMSTUDIO = LMStudioProvider(
    id="lmstudio",
    name="LM Studio",
    is_local=True,
    base_url="http://localhost:1234/v1",
    require_api_key=False,
    api_key_prefix="",
    support_model_discovery=True,
    generate_kwargs={"max_tokens": None},
)

PROVIDER_SILICONFLOW_CN = OpenAIProvider(
    id="siliconflow-cn",
    name="SiliconFlow (China)",
    base_url="https://api.siliconflow.cn/v1",
    api_key_prefix="sk-",
    models=[],
    freeze_url=True,
    require_api_key=True,
    support_model_discovery=True,
    provider_group="siliconflow",
    provider_group_name="SiliconFlow",
    provider_variant="china",
    meta={
        "is_free_tier": True,
    },
)

PROVIDER_SILICONFLOW_INTL = OpenAIProvider(
    id="siliconflow-intl",
    name="SiliconFlow (International)",
    base_url="https://api.siliconflow.com/v1",
    api_key_prefix="sk-",
    models=[],
    freeze_url=True,
    require_api_key=True,
    support_model_discovery=True,
    provider_group="siliconflow",
    provider_group_name="SiliconFlow",
    provider_variant="international",
    meta={
        "is_free_tier": True,
    },
)

PROVIDER_VOLCENGINE_CN = OpenAIProvider(
    id="volcengine-cn",
    name="Volcano Engine",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key_prefix="",
    models=VOLCENGINE_MODELS,
    freeze_url=True,
    support_model_discovery=False,
    provider_group="volcengine",
    provider_group_name="Volcano Engine",
    provider_variant="open_platform",
)

PROVIDER_VOLCENGINE_CN_CODINGPLAN = OpenAIProvider(
    id="volcengine-cn-codingplan",
    name="Volcano Engine Coding Plan",
    base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
    api_key_prefix="",
    models=VOLCENGINE_CODINGPLAN_MODELS,
    support_connection_check=False,
    freeze_url=True,
    support_model_discovery=False,
    provider_group="volcengine",
    provider_group_name="Volcano Engine",
    provider_variant="coding_plan",
)

PROVIDER_MIMO_TOKENPLAN = OpenAIProvider(
    id="mimo-tokenplan",
    name="Xiaomi MiMo Token Plan",
    base_url="https://token-plan-cn.xiaomimimo.com/v1",
    api_key_prefix="",
    models=MIMO_TOKENPLAN_MODELS,
    freeze_url=True,
)


BUILTIN_PROVIDERS: tuple[Provider, ...] = (
    PROVIDER_QWENPAW,
    PROVIDER_OLLAMA,
    PROVIDER_LMSTUDIO,
    PROVIDER_OPENROUTER,
    PROVIDER_GITHUB_MODELS,
    PROVIDER_MODELSCOPE,
    PROVIDER_DASHSCOPE,
    PROVIDER_ALIYUN_CODINGPLAN,
    PROVIDER_ALIYUN_CODINGPLAN_INTL,
    PROVIDER_ALIYUN_TOKENPLAN,
    PROVIDER_ALIYUN_TOKENPLAN_INTL,
    PROVIDER_OPENCODE,
    PROVIDER_KILO,
    PROVIDER_OPENAI,
    PROVIDER_OPENAI_RESPONSE,
    PROVIDER_AZURE_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_DEEPSEEK,
    PROVIDER_KIMI_CN,
    PROVIDER_KIMI_INTL,
    PROVIDER_KIMI_CODINGPLAN,
    PROVIDER_MINIMAX_CN,
    PROVIDER_MINIMAX,
    PROVIDER_ZHIPU_CN,
    PROVIDER_ZHIPU_CN_CODINGPLAN,
    PROVIDER_ZHIPU_INTL,
    PROVIDER_ZHIPU_INTL_CODINGPLAN,
    PROVIDER_SILICONFLOW_CN,
    PROVIDER_SILICONFLOW_INTL,
    PROVIDER_VOLCENGINE_CN,
    PROVIDER_VOLCENGINE_CN_CODINGPLAN,
    PROVIDER_MIMO_TOKENPLAN,
)

BUILTIN_PROVIDER_CATALOG_KEYS = {
    "modelscope": "MODELSCOPE_MODELS",
    "dashscope": "DASHSCOPE_MODELS",
    "aliyun-codingplan": "ALIYUN_CODINGPLAN_MODELS",
    "aliyun-codingplan-intl": "ALIYUN_CODINGPLAN_MODELS",
    "aliyun-tokenplan": "ALIYUN_TOKENPLAN_MODELS",
    "aliyun-tokenplan-intl": "ALIYUN_TOKENPLAN_MODELS",
    "zhipu-cn": "ZHIPU_MODELS",
    "zhipu-cn-codingplan": "ZHIPU_MODELS",
    "zhipu-intl": "ZHIPU_MODELS",
    "zhipu-intl-codingplan": "ZHIPU_MODELS",
    "openai": "OPENAI_MODELS",
    "openai-response": "OPENAI_MODELS",
    "opencode": "OPENCODE_MODELS",
    "kilo": "KILO_MODELS",
    "azure-openai": "AZURE_OPENAI_MODELS",
    "minimax": "MINIMAX_MODELS",
    "minimax-cn": "MINIMAX_MODELS",
    "kimi-cn": "KIMI_MODELS",
    "kimi-intl": "KIMI_MODELS",
    "kimi-codingplan": "KIMI_CODINGPLAN_MODELS",
    "deepseek": "DEEPSEEK_MODELS",
    "anthropic": "ANTHROPIC_MODELS",
    "gemini": "GEMINI_MODELS",
    "github-models": "GITHUB_MODELS_MODELS",
    "volcengine-cn": "VOLCENGINE_MODELS",
    "volcengine-cn-codingplan": "VOLCENGINE_CODINGPLAN_MODELS",
    "mimo-tokenplan": "MIMO_TOKENPLAN_MODELS",
}

for _provider in BUILTIN_PROVIDERS:
    apply_discovery_policy(_provider)


__all__ = [
    "BUILTIN_PROVIDER_CATALOG_KEYS",
    "ALIYUN_CODINGPLAN_MODELS",
    "ALIYUN_TOKENPLAN_MODELS",
    "ANTHROPIC_MODELS",
    "AZURE_OPENAI_MODELS",
    "BUILTIN_PROVIDERS",
    "DASHSCOPE_MODELS",
    "DEEPSEEK_MODELS",
    "GEMINI_MODELS",
    "GITHUB_MODELS_MODELS",
    "KILO_MODELS",
    "KIMI_CODINGPLAN_MODELS",
    "KIMI_MODELS",
    "MIMO_TOKENPLAN_MODELS",
    "MINIMAX_MODELS",
    "MODELSCOPE_MODELS",
    "OPENAI_MODELS",
    "OPENCODE_MODELS",
    "PROVIDER_ALIYUN_CODINGPLAN",
    "PROVIDER_ALIYUN_CODINGPLAN_INTL",
    "PROVIDER_ALIYUN_TOKENPLAN",
    "PROVIDER_ALIYUN_TOKENPLAN_INTL",
    "PROVIDER_ANTHROPIC",
    "PROVIDER_AZURE_OPENAI",
    "PROVIDER_DASHSCOPE",
    "PROVIDER_DEEPSEEK",
    "PROVIDER_GEMINI",
    "PROVIDER_GITHUB_MODELS",
    "PROVIDER_KILO",
    "PROVIDER_KIMI_CN",
    "PROVIDER_KIMI_CODINGPLAN",
    "PROVIDER_KIMI_INTL",
    "PROVIDER_LMSTUDIO",
    "PROVIDER_MIMO_TOKENPLAN",
    "PROVIDER_MINIMAX",
    "PROVIDER_MINIMAX_CN",
    "PROVIDER_MODELSCOPE",
    "PROVIDER_OLLAMA",
    "PROVIDER_OPENCODE",
    "PROVIDER_OPENAI",
    "PROVIDER_OPENAI_RESPONSE",
    "PROVIDER_OPENROUTER",
    "PROVIDER_QWENPAW",
    "PROVIDER_SILICONFLOW_CN",
    "PROVIDER_SILICONFLOW_INTL",
    "PROVIDER_VOLCENGINE_CN",
    "PROVIDER_VOLCENGINE_CN_CODINGPLAN",
    "PROVIDER_ZHIPU_CN",
    "PROVIDER_ZHIPU_CN_CODINGPLAN",
    "PROVIDER_ZHIPU_INTL",
    "PROVIDER_ZHIPU_INTL_CODINGPLAN",
    "VOLCENGINE_CODINGPLAN_MODELS",
    "VOLCENGINE_MODELS",
    "ZHIPU_MODELS",
]
