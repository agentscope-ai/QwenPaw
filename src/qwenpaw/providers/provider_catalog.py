# -*- coding: utf-8 -*-
"""Built-in provider catalog and default model definitions."""

from typing import List

from .anthropic_provider import AnthropicProvider
from .dashscope_provider import DashScopeProvider
from .gemini_provider import GeminiProvider
from .lmstudio_provider import LMStudioProvider
from .mimo_provider import MiMoProvider
from .modelscope_provider import ModelScopeProvider
from .ollama_provider import OllamaProvider
from .openai_provider import (
    KiloProvider,
    OpenAIProvider,
    OpenCodeProvider,
)
from .model_catalog import models_for_catalog_key
from .openai_response_provider import OpenAIResponseProvider
from .openrouter_provider import OpenRouterProvider
from .provider import ModelInfo, Provider
from .services.agentscope_platform import AgentScopePlatformProvider
from .services.deepseek import DeepSeekProvider
from .services.kimi import KimiProvider
from .services.zhipu import ZhipuProvider
from .services.siliconflow import SiliconFlowProvider
from .services.volcengine import VolcengineProvider
from .services.aliyun import AliyunPlanProvider
from .services.minimax import MiniMaxProvider
from .services.azure import AzureOpenAIProvider
from .services.qwenpaw import QwenPawProvider
from .services.mimo_plan import MiMoPlanProvider
from .provider_discovery_policy import apply_discovery_policy

# -------------------------------------------------------
# Built-in provider definitions and their default models.
# -------------------------------------------------------


def _models(catalog_key: str) -> List[ModelInfo]:
    return models_for_catalog_key(catalog_key)


MODELSCOPE_MODELS = _models("modelscope")
DASHSCOPE_MODELS = _models("dashscope")
MIMO_TOKENPLAN_MODELS = _models("mimo-tokenplan")
MIMO_MODELS = _models("mimo")
ALIYUN_TOKENPLAN_MODELS = _models("aliyun-tokenplan")
ALIYUN_CODINGPLAN_MODELS = _models("aliyun-codingplan")
ZHIPU_MODELS = _models("zhipu-cn")
OPENAI_MODELS = _models("openai")
KILO_MODELS = _models("kilo")
OPENCODE_MODELS = _models("opencode")
AZURE_OPENAI_MODELS = _models("azure-openai")
MINIMAX_MODELS = _models("minimax-cn")
KIMI_MODELS = _models("kimi-cn")
DEEPSEEK_MODELS = _models("deepseek")
VOLCENGINE_MODELS = _models("volcengine-cn")
VOLCENGINE_CODINGPLAN_MODELS = _models("volcengine-cn-codingplan")
VOLCENGINE_AGENTPLAN_MODELS = _models("volcengine-cn-agentplan")
ANTHROPIC_MODELS = _models("anthropic")
GEMINI_MODELS = _models("gemini")
KIMI_CODINGPLAN_MODELS = _models("kimi-codingplan")

PROVIDER_MODELSCOPE = ModelScopeProvider(
    id="modelscope",
    name="ModelScope",
    base_url="https://api-inference.modelscope.cn/v1",
    api_key_prefix="ms",
    models=_models("modelscope"),
    support_model_discovery=True,
    freeze_url=True,
)

PROVIDER_DASHSCOPE = DashScopeProvider(
    id="dashscope",
    name="DashScope",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key_prefix="sk",
    models=_models("dashscope"),
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

PROVIDER_ALIYUN_CODINGPLAN = AliyunPlanProvider(
    id="aliyun-codingplan",
    name="Aliyun Coding Plan (China)",
    base_url="https://coding.dashscope.aliyuncs.com/v1",
    api_key_prefix="sk-sp",
    models=_models("aliyun-codingplan"),
    support_connection_check=False,
    freeze_url=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="coding_plan_cn",
)

PROVIDER_ALIYUN_CODINGPLAN_INTL = AliyunPlanProvider(
    id="aliyun-codingplan-intl",
    name="Aliyun Coding Plan (International)",
    base_url="https://coding-intl.dashscope.aliyuncs.com/v1",
    api_key_prefix="sk-sp",
    models=_models("aliyun-codingplan-intl"),
    support_connection_check=False,
    freeze_url=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="coding_plan_intl",
)

PROVIDER_ALIYUN_TOKENPLAN = AliyunPlanProvider(
    id="aliyun-tokenplan",
    name="Aliyun Token Plan",
    base_url=(
        "https://token-plan.cn-beijing.maas.aliyuncs.com/" "compatible-mode/v1"
    ),
    api_key_prefix="sk-sp",
    models=_models("aliyun-tokenplan"),
    support_connection_check=False,
    freeze_url=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="token_plan",
)

PROVIDER_ALIYUN_TOKENPLAN_INTL = AliyunPlanProvider(
    id="aliyun-tokenplan-intl",
    name="Aliyun Token Plan (International)",
    base_url=(
        "https://token-plan.ap-southeast-1.maas.aliyuncs.com/"
        "compatible-mode/v1"
    ),
    api_key_prefix="sk-sp",
    models=_models("aliyun-tokenplan-intl"),
    support_connection_check=False,
    freeze_url=True,
    provider_group="aliyun",
    provider_group_name="Aliyun",
    provider_variant="token_plan_intl",
)

PROVIDER_ZHIPU_CN = ZhipuProvider(
    id="zhipu-cn",
    name="Zhipu (BigModel)",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    api_key_prefix="",
    models=_models("zhipu-cn"),
    freeze_url=True,
    provider_group="zhipu",
    provider_group_name="Zhipu",
    provider_variant="open_platform_cn",
    meta={"is_free_tier": True},
)

PROVIDER_ZHIPU_CN_CODINGPLAN = ZhipuProvider(
    id="zhipu-cn-codingplan",
    name="Zhipu Coding Plan (BigModel)",
    base_url="https://open.bigmodel.cn/api/coding/paas/v4",
    api_key_prefix="",
    models=_models("zhipu-cn-codingplan"),
    freeze_url=True,
    support_connection_check=False,
    provider_group="zhipu",
    provider_group_name="Zhipu",
    provider_variant="coding_plan_cn",
)

PROVIDER_ZHIPU_INTL = ZhipuProvider(
    id="zhipu-intl",
    name="Zhipu (Z.AI)",
    base_url="https://api.z.ai/api/paas/v4",
    api_key_prefix="",
    models=_models("zhipu-intl"),
    freeze_url=True,
    provider_group="zhipu",
    provider_group_name="Zhipu",
    provider_variant="open_platform_intl",
)

PROVIDER_ZHIPU_INTL_CODINGPLAN = ZhipuProvider(
    id="zhipu-intl-codingplan",
    name="Zhipu Coding Plan (Z.AI)",
    base_url="https://api.z.ai/api/coding/paas/v4",
    api_key_prefix="",
    models=_models("zhipu-intl-codingplan"),
    freeze_url=True,
    support_connection_check=False,
    provider_group="zhipu",
    provider_group_name="Zhipu",
    provider_variant="coding_plan_intl",
)

PROVIDER_QWENPAW = QwenPawProvider(
    id="qwenpaw-local",
    name="QwenPaw Local",
    is_local=True,
    require_api_key=False,
)

PROVIDER_AGENTSCOPE_PLATFORM = AgentScopePlatformProvider(
    id=f"agentscope-platform",
    name=f"AgentScope Platform",
    base_url=f"https://platform.agentscope.io/compatible-mode/v1",
    api_key_prefix=f"",
    meta={f"api_key_url": f"https://platform.agentscope.io/model-calls"},
)

PROVIDER_OPENAI = OpenAIProvider(
    id="openai",
    name="OpenAI",
    base_url="https://api.openai.com/v1",
    api_key_prefix="sk-",
    models=_models("openai"),
    support_model_discovery=True,
    freeze_url=True,
)

PROVIDER_OPENAI_RESPONSE = OpenAIResponseProvider(
    id="openai-response",
    name="OpenAI (Response API)",
    base_url="https://api.openai.com/v1",
    api_key_prefix="sk-",
    chat_model="OpenAIResponseModel",
    models=_models("openai-response"),
    support_model_discovery=True,
    freeze_url=True,
)

PROVIDER_OPENCODE = OpenCodeProvider(
    id="opencode",
    name="OpenCode",
    base_url="https://opencode.ai/zen/v1",
    api_key_prefix="",
    models=_models("opencode"),
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
    models=_models("kilo"),
    require_api_key=False,
    meta={"is_free_tier": True},
    freeze_url=True,
)

PROVIDER_AZURE_OPENAI = AzureOpenAIProvider(
    id="azure-openai",
    name="Azure OpenAI",
    api_key_prefix="",
    models=_models("azure-openai"),
)

PROVIDER_MINIMAX = MiniMaxProvider(
    id="minimax",
    name="MiniMax (International)",
    base_url="https://api.minimax.io/anthropic",
    models=_models("minimax"),
    chat_model="AnthropicChatModel",
    freeze_url=True,
    support_connection_check=False,
    provider_group="minimax",
    provider_group_name="MiniMax",
    provider_variant="open_platform_intl",
)

PROVIDER_MINIMAX_CN = MiniMaxProvider(
    id="minimax-cn",
    name="MiniMax (China)",
    base_url="https://api.minimaxi.com/anthropic",
    models=_models("minimax-cn"),
    chat_model="AnthropicChatModel",
    freeze_url=True,
    support_connection_check=False,
    provider_group="minimax",
    provider_group_name="MiniMax",
    provider_variant="open_platform_cn",
)

PROVIDER_KIMI_CN = KimiProvider(
    id="kimi-cn",
    name="Kimi (China)",
    base_url="https://api.moonshot.cn/v1",
    api_key_prefix="",
    models=_models("kimi-cn"),
    support_model_discovery=True,
    merge_with_catalog=True,
    freeze_url=True,
    provider_group="kimi",
    provider_group_name="Kimi",
    provider_variant="open_platform_cn",
)

PROVIDER_KIMI_INTL = KimiProvider(
    id="kimi-intl",
    name="Kimi (International)",
    base_url="https://api.moonshot.ai/v1",
    api_key_prefix="",
    models=_models("kimi-intl"),
    support_model_discovery=True,
    merge_with_catalog=True,
    freeze_url=True,
    provider_group="kimi",
    provider_group_name="Kimi",
    provider_variant="open_platform_intl",
)

PROVIDER_KIMI_CODINGPLAN = KimiProvider(
    id="kimi-codingplan",
    name="Kimi Coding Plan",
    base_url="https://api.kimi.com/coding/v1",
    api_key_prefix="sk-kimi-",
    models=_models("kimi-codingplan"),
    freeze_url=True,
    support_connection_check=False,
    provider_group="kimi",
    provider_group_name="Kimi",
    provider_variant="coding_plan",
)

PROVIDER_DEEPSEEK = DeepSeekProvider(
    id="deepseek",
    name="DeepSeek",
    base_url="https://api.deepseek.com",
    api_key_prefix="sk-",
    models=_models("deepseek"),
    support_model_discovery=True,
    merge_with_catalog=True,
    freeze_url=True,
)

PROVIDER_ANTHROPIC = AnthropicProvider(
    id="anthropic",
    name="Anthropic",
    base_url="https://api.anthropic.com",
    api_key_prefix="sk-ant-",
    models=_models("anthropic"),
    chat_model="AnthropicChatModel",
    support_model_discovery=True,
    freeze_url=False,
)

PROVIDER_GEMINI = GeminiProvider(
    id="gemini",
    name="Google Gemini",
    base_url="https://generativelanguage.googleapis.com",
    api_key_prefix="",
    models=_models("gemini"),
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

PROVIDER_SILICONFLOW_CN = SiliconFlowProvider(
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

PROVIDER_SILICONFLOW_INTL = SiliconFlowProvider(
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

PROVIDER_VOLCENGINE_CN = VolcengineProvider(
    id="volcengine-cn",
    name="Volcengine",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key_prefix="",
    models=_models("volcengine-cn"),
    freeze_url=True,
    support_model_discovery=False,
    provider_group="volcengine",
    provider_group_name="Volcengine",
    provider_variant="open_platform",
)

PROVIDER_VOLCENGINE_CN_CODINGPLAN = VolcengineProvider(
    id="volcengine-cn-codingplan",
    name="Volcengine Coding Plan",
    base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
    api_key_prefix="",
    models=_models("volcengine-cn-codingplan"),
    support_connection_check=False,
    freeze_url=True,
    support_model_discovery=False,
    provider_group="volcengine",
    provider_group_name="Volcengine",
    provider_variant="coding_plan",
)

PROVIDER_VOLCENGINE_CN_AGENTPLAN = VolcengineProvider(
    id="volcengine-cn-agentplan",
    name="Volcengine Agent Plan",
    base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
    api_key_prefix="",
    models=_models("volcengine-cn-agentplan"),
    support_connection_check=False,
    freeze_url=True,
    support_model_discovery=False,
    provider_group="volcengine",
    provider_group_name="Volcengine",
    provider_variant="agent_plan",
)

PROVIDER_MIMO_TOKENPLAN = MiMoPlanProvider(
    id="mimo-tokenplan",
    name="Xiaomi MiMo Token Plan",
    base_url="https://token-plan-cn.xiaomimimo.com/v1",
    api_key_prefix="",
    models=_models("mimo-tokenplan"),
    freeze_url=True,
    provider_group="mimo",
    provider_group_name="Xiaomi MiMo",
    provider_variant="token_plan",
)

PROVIDER_MIMO = MiMoProvider(
    id="mimo",
    name="Xiaomi MiMo",
    base_url="https://api.xiaomimimo.com/v1",
    api_key_prefix="sk-",
    models=_models("mimo"),
    freeze_url=True,
    support_model_discovery=True,
    provider_group="mimo",
    provider_group_name="Xiaomi MiMo",
    provider_variant="standard",
)


BUILTIN_PROVIDERS: tuple[Provider, ...] = (
    PROVIDER_QWENPAW,
    PROVIDER_OLLAMA,
    PROVIDER_LMSTUDIO,
    PROVIDER_OPENROUTER,
    PROVIDER_MODELSCOPE,
    PROVIDER_AGENTSCOPE_PLATFORM,
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
    PROVIDER_VOLCENGINE_CN_AGENTPLAN,
    PROVIDER_MIMO_TOKENPLAN,
    PROVIDER_MIMO,
)

BUILTIN_PROVIDER_CATALOG_KEYS = {
    provider.id: provider.id
    for provider in BUILTIN_PROVIDERS
    if not provider.is_local
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
    "KILO_MODELS",
    "KIMI_CODINGPLAN_MODELS",
    "KIMI_MODELS",
    "MIMO_MODELS",
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
    "PROVIDER_KILO",
    "PROVIDER_KIMI_CN",
    "PROVIDER_KIMI_CODINGPLAN",
    "PROVIDER_KIMI_INTL",
    "PROVIDER_LMSTUDIO",
    "PROVIDER_MIMO",
    "PROVIDER_MIMO_TOKENPLAN",
    "PROVIDER_MINIMAX",
    "PROVIDER_MINIMAX_CN",
    "PROVIDER_MODELSCOPE",
    "PROVIDER_OLLAMA",
    "PROVIDER_OPENCODE",
    "PROVIDER_OPENAI",
    "PROVIDER_AGENTSCOPE_PLATFORM",
    "PROVIDER_OPENAI_RESPONSE",
    "PROVIDER_OPENROUTER",
    "PROVIDER_QWENPAW",
    "PROVIDER_SILICONFLOW_CN",
    "PROVIDER_SILICONFLOW_INTL",
    "PROVIDER_VOLCENGINE_CN",
    "PROVIDER_VOLCENGINE_CN_AGENTPLAN",
    "PROVIDER_VOLCENGINE_CN_CODINGPLAN",
    "PROVIDER_ZHIPU_CN",
    "PROVIDER_ZHIPU_CN_CODINGPLAN",
    "PROVIDER_ZHIPU_INTL",
    "PROVIDER_ZHIPU_INTL_CODINGPLAN",
    "VOLCENGINE_AGENTPLAN_MODELS",
    "VOLCENGINE_CODINGPLAN_MODELS",
    "VOLCENGINE_MODELS",
    "ZHIPU_MODELS",
]
