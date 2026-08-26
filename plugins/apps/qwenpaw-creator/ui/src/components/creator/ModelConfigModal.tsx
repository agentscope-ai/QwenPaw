import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Input,
  Select,
  Checkbox,
  Button,
  message,
  AutoComplete,
  Tooltip,
} from "antd";
import { Brain } from "lucide-react";
import {
  SettingOutlined,
  LinkOutlined,
  SaveOutlined,
  DownOutlined,
  EyeOutlined,
  PictureOutlined,
  UserOutlined,
  VideoCameraOutlined,
  AudioOutlined,
  SoundOutlined,
  NodeIndexOutlined,
  GlobalOutlined,
  ReloadOutlined,
  CloseOutlined,
  ThunderboltOutlined,
  SafetyOutlined,
  ReadOutlined,
  TranslationOutlined,
} from "@ant-design/icons";
import {
  getModelConfig,
  saveModelConfig,
  patchPermissionMode,
  patchCreationCheckpoints,
  patchSelfReview,
  testModelConnection,
  getHostProviders,
  getHostProviderApiKey,
  getRealApiKey,
  getTtsCapabilities,
  getVideoCapabilities,
} from "@/api/creator";
import type {
  HostProviderInfo,
  TtsCapabilities,
  VideoModelCapabilities,
} from "@/api/creator";
import type {
  GroundingConfig,
  ModelConfigData,
  ModelConfigItem,
} from "@/contracts/creator";
import ModelSetupGuide from "@/components/onboarding/ModelSetupGuide";

export const LLM_PROTOCOLS = [
  "Anthropic Claude",
  "DashScope（百炼）",
  "Aliyun Token Plan",
  "Aliyun Coding Plan",
  "DeepSeek",
  "Google Gemini",
  "OpenAI 协议",
  "Azure OpenAI",
  "MiniMax",
  "Kimi（月之暗面）",
  "智谱 AI",
  "SiliconFlow（硅基流动）",
  "ModelScope（魔搭）",
  "百度千帆",
  "Volcano Engine（火山引擎）",
  "小米 MiMo",
  "自定义",
];
export const VLM_PROTOCOLS = [
  "Anthropic Claude",
  "DashScope（百炼）",
  "Aliyun Token Plan",
  "Aliyun Coding Plan",
  "DeepSeek",
  "Google Gemini",
  "OpenAI 协议",
  "Azure OpenAI",
  "MiniMax",
  "Kimi（月之暗面）",
  "智谱 AI",
  "SiliconFlow（硅基流动）",
  "ModelScope（魔搭）",
  "百度千帆",
  "Volcano Engine（火山引擎）",
  "小米 MiMo",
  "自定义",
];
export const ASR_PROTOCOLS = [
  "DashScope Fun-ASR",
  "DashScope Qwen3-ASR",
  "OpenAI Whisper",
];
export const TTS_PROTOCOLS = ["DashScope（百炼）"];
export const S2V_PROTOCOLS = ["DashScope（百炼）"];
export const EMBEDDING_PROTOCOLS = ["DashScope（百炼）"];
export const IMAGE_PROTOCOLS = [
  "OpenAI 协议",
  "DashScope（百炼）",
  "Google Gemini",
  "Volcano Engine（火山引擎）",
  "Black Forest Labs（FLUX）",
  "Ideogram",
  "Aliyun Token Plan",
];
// Kling and Vidu appear twice on purpose: they are served both as
// Bailian-hosted models on the DashScope protocol and through their own
// official APIs, and the protocol choice is what selects the channel.
export const VIDEO_PROTOCOLS = [
  "DashScope（百炼）",
  "Volcano Engine（火山引擎）",
  "Google Gemini（Veo）",
  "MiniMax（海螺）",
  "Kling（可灵官方）",
  "Vidu（官方）",
  "Aliyun Token Plan",
];

// Display-only labels for the protocol dropdowns: the stored protocol
// strings double as backend match keys (substring checks in the host),
// so only the rendered label translates while the value stays verbatim.
// Unknown/custom protocols fall back to their raw value.
export const PROTOCOL_LABEL_KEYS: Record<string, string> = {
  "Anthropic Claude": "modelConfig.protocols.anthropicClaude",
  "DashScope（百炼）": "modelConfig.protocols.dashscope",
  "Aliyun Token Plan": "modelConfig.protocols.aliyunTokenPlan",
  "Aliyun Coding Plan": "modelConfig.protocols.aliyunCodingPlan",
  DeepSeek: "modelConfig.protocols.deepseek",
  "Google Gemini": "modelConfig.protocols.googleGemini",
  "OpenAI 协议": "modelConfig.protocols.openai",
  "Azure OpenAI": "modelConfig.protocols.azureOpenai",
  MiniMax: "modelConfig.protocols.minimax",
  "Kimi（月之暗面）": "modelConfig.protocols.kimi",
  "智谱 AI": "modelConfig.protocols.zhipu",
  "SiliconFlow（硅基流动）": "modelConfig.protocols.siliconflow",
  "ModelScope（魔搭）": "modelConfig.protocols.modelscope",
  百度千帆: "modelConfig.protocols.qianfan",
  "Volcano Engine（火山引擎）": "modelConfig.protocols.volcengine",
  "Black Forest Labs（FLUX）": "modelConfig.protocols.bfl",
  Ideogram: "modelConfig.protocols.ideogram",
  "Google Gemini（Veo）": "modelConfig.protocols.googleGeminiVeo",
  "MiniMax（海螺）": "modelConfig.protocols.minimaxHailuo",
  "Kling（可灵官方）": "modelConfig.protocols.klingOfficial",
  "Vidu（官方）": "modelConfig.protocols.viduOfficial",
  "小米 MiMo": "modelConfig.protocols.xiaomiMimo",
  自定义: "modelConfig.protocols.custom",
  "DashScope Fun-ASR": "modelConfig.protocols.dashscopeFunAsr",
  "DashScope Qwen3-ASR": "modelConfig.protocols.dashscopeQwen3Asr",
  "OpenAI Whisper": "modelConfig.protocols.openaiWhisper",
};

// Default endpoints for LLM/VLM protocols when the host provider registry
// is unavailable (standalone deployments). Values are copied verbatim from
// src/qwenpaw/providers/provider_manager.py — keep in sync with the host.
const LLM_PROTOCOL_FALLBACK_BASE_URLS: Record<string, string> = {
  "DashScope（百炼）": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "Aliyun Token Plan":
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
  "Aliyun Coding Plan": "https://coding.dashscope.aliyuncs.com/v1",
  DeepSeek: "https://api.deepseek.com",
  "OpenAI 协议": "https://api.openai.com/v1",
  "Anthropic Claude": "https://api.anthropic.com",
  "Google Gemini": "https://generativelanguage.googleapis.com",
  MiniMax: "https://api.minimaxi.com/anthropic",
  "Kimi（月之暗面）": "https://api.moonshot.cn/v1",
  "智谱 AI": "https://open.bigmodel.cn/api/paas/v4",
  "SiliconFlow（硅基流动）": "https://api.siliconflow.cn/v1",
  "ModelScope（魔搭）": "https://api-inference.modelscope.cn/v1",
  "Volcano Engine（火山引擎）": "https://ark.cn-beijing.volces.com/api/v3",
  "小米 MiMo": "https://token-plan-cn.xiaomimimo.com/v1",
};

// Presets seed a default endpoint when the user picks a protocol/model;
// the URL always stays editable for self-hosted or proxied deployments.
interface ProtocolPreset {
  base_url: string;
  models: string[];
  base_url_options?: { label: string; value: string }[];
}

const PROTOCOL_TO_PROVIDER_ID: Record<string, string> = {
  "DashScope（百炼）": "dashscope",
  "Aliyun Token Plan": "aliyun-tokenplan",
  "Aliyun Coding Plan": "aliyun-codingplan",
  DeepSeek: "deepseek",
  "OpenAI 协议": "openai",
  "Azure OpenAI": "azure-openai",
  "Anthropic Claude": "anthropic",
  "Google Gemini": "gemini",
  MiniMax: "minimax-cn",
  "Kimi（月之暗面）": "kimi-cn",
  "智谱 AI": "zhipu-cn",
  "SiliconFlow（硅基流动）": "siliconflow-cn",
  "ModelScope（魔搭）": "modelscope",
  百度千帆: "qianfan",
  "Volcano Engine（火山引擎）": "volcengine-cn",
  "小米 MiMo": "mimo-tokenplan",
};

const ASR_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope Fun-ASR": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    models: ["fun-asr"],
  },
  "DashScope Qwen3-ASR": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    models: ["qwen3-asr-flash"],
  },
  "OpenAI Whisper": {
    base_url: "https://api.openai.com/v1",
    models: ["whisper-1"],
  },
};

const TTS_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope（百炼）": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    // Filled from the backend capability table so the UI never offers a model
    // this build cannot drive.
    models: [],
  },
};

const S2V_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope（百炼）": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    models: ["wan2.2-s2v"],
  },
};

const EMBEDDING_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope（百炼）": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    models: ["qwen3-vl-embedding"],
  },
};

const IMAGE_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope（百炼）": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    // Only models served by the multimodal-generation endpoint the backend
    // actually calls (per the Bailian qwen-image / wan2.7 / wan2.6 API
    // references); the legacy t2i family uses a different async endpoint
    // this provider does not speak, so it is not offered. qwen-image-3.0
    // is the current flagship and leads as the default pick.
    models: [
      "qwen-image-3.0-pro",
      "qwen-image-2.0-pro",
      "qwen-image-2.0",
      "qwen-image-max",
      "qwen-image-plus",
      "wan2.7-image-pro",
      "wan2.7-image",
      "wan2.6-image",
      "z-image-turbo",
    ],
  },
  "OpenAI 协议": {
    base_url: "https://api.openai.com/v1",
    models: ["gpt-image-2"],
  },
  "Google Gemini": {
    base_url: "https://generativelanguage.googleapis.com/v1beta",
    // Nano Banana family via generateContent. gemini-3-pro-image accepts
    // up to 14 reference images (6 objects + 5 characters + 3 style);
    // gemini-2.5-flash-image works best with at most 3 references.
    models: [
      "gemini-3-pro-image",
      "gemini-3.1-flash-image",
      "gemini-3.1-flash-lite-image",
      "gemini-2.5-flash-image",
    ],
  },
  "Volcano Engine（火山引擎）": {
    base_url: "https://ark.cn-beijing.volces.com",
    // Ark images/generations (synchronous). Seedream 5.0 pro accepts up
    // to 10 reference images; 5.0 lite / 4.5 / 4.0 accept up to 14.
    models: [
      "doubao-seedream-5-0-pro-260628",
      "doubao-seedream-5-0-lite-260128",
      "doubao-seedream-4-5-251128",
      "doubao-seedream-4-0-250828",
    ],
  },
  "Black Forest Labs（FLUX）": {
    base_url: "https://api.bfl.ai",
    // FLUX.2 create-then-poll API; up to 8 reference images
    // (input_image .. input_image_8).
    models: [
      "flux-2-pro",
      "flux-2-max",
      "flux-2-flex",
      "flux-2-klein-9b",
      "flux-2-klein-4b",
    ],
  },
  Ideogram: {
    base_url: "https://api.ideogram.ai",
    // ideogram-v3 exposes aspect_ratio and one character reference; the
    // v4 generate endpoint documents neither, so it is text-to-image only.
    models: ["ideogram-v3", "ideogram-v4"],
  },
  "Aliyun Token Plan": {
    base_url: "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1",
    models: ["wan2.7-image-pro", "wan2.7-image"],
  },
};

const VIDEO_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope（百炼）": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    // Wan3.0 keeps one All-in-One model ID; Wan2/HappyHorse family base names
    // derive their per-mode sibling at submission. The kling/ and vidu/ entries
    // are exact Bailian-hosted models.
    // Bailian-hosted third-party models served by the same
    // video-synthesis endpoint (kling v3: t2v/i2v/refer≤7; vidu:
    // reference-to-video only, 1-7 images).
    models: [
      "wan2.7",
      "wan3.0-video",
      "wan3.0-video-prime",
      "happyhorse-1.1",
      "kling/kling-v3-omni-video-generation",
      "kling/kling-v3-video-generation",
      "vidu/viduq3-mix_reference2video",
      "vidu/viduq3_reference2video",
      "vidu/viduq3-turbo_reference2video",
      "vidu/viduq3-ad_reference2video",
      "vidu/viduq3-drama_reference2video",
      "vidu/viduq2-pro_reference2video",
      "vidu/viduq2_reference2video",
    ],
  },
  "Volcano Engine（火山引擎）": {
    base_url: "https://ark.cn-beijing.volces.com",
    // Seedance 2.5 (doubao-seedance-2-5-260628) adds omni reference
    // (up to 30 images + 10 videos) and 4-30s output.
    models: [
      "doubao-seedance-2-5-260628",
      "doubao-seedance-2-0-260128",
      "doubao-seedance-2-0-fast-260128",
      "doubao-seedance-2-0-mini-260615",
    ],
  },
  "Google Gemini（Veo）": {
    base_url: "https://generativelanguage.googleapis.com/v1beta",
    // Veo 3.1 predictLongRunning: durations 4/6/8s (8s with references
    // or 1080p/4k), up to 3 reference images; Lite has no references/4k.
    models: [
      "veo-3.1-generate-preview",
      "veo-3.1-fast-generate-preview",
      "veo-3.1-lite-generate-preview",
    ],
  },
  "MiniMax（海螺）": {
    base_url: "https://api.minimax.io",
    // Hailuo: 768P at 6/10s, 1080P at 6s (Hailuo-02 also has 512P);
    // S2V-01 is the only subject
    // reference model (1 character image). China endpoint:
    // https://api.minimaxi.com
    models: [
      "MiniMax-Hailuo-2.3",
      "MiniMax-Hailuo-2.3-Fast",
      "MiniMax-Hailuo-02",
      "S2V-01",
    ],
  },
  "Kling（可灵官方）": {
    base_url: "https://api-singapore.klingai.com",
    // Official channel (Bearer API Key). kling-3.0-omni serves reference
    // generation (refer<=7, 3-15s, 720p/1080p/4k); kling-2.6 is t2v/i2v
    // only (5s or 10s, 720p/1080p).
    models: ["kling-3.0-omni", "kling-2.6"],
  },
  "Vidu（官方）": {
    base_url: "https://api.vidu.com",
    // Official Vidu channel (Token auth). Mode support is per exact model:
    // e.g. q3-turbo supports t2v/i2v/r2v while q3-mix is r2v-only.
    models: ["viduq3-mix", "viduq3-turbo", "viduq3", "viduq2-pro", "viduq2"],
  },
  "Aliyun Token Plan": {
    base_url: "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1",
    models: ["happyhorse-1.1"],
  },
};

type ModelType =
  | "llm"
  | "vlm"
  | "asr"
  | "tts"
  | "s2v"
  | "embedding"
  | "image"
  | "video";
type TabType = ModelType | "grounding";

// Sections whose endpoint comes from a fixed protocol preset rather than
// from user input.
export const PRESETS_BY_TYPE: Record<string, Record<string, ProtocolPreset>> = {
  asr: ASR_PRESETS,
  tts: TTS_PRESETS,
  s2v: S2V_PRESETS,
  image: IMAGE_PRESETS,
  video: VIDEO_PRESETS,
};
const PRESET_SEEDED_TYPES: ModelType[] = ["asr", "tts", "s2v"];
const DEFAULT_CONFIG: ModelConfigData = {
  llm: {
    enabled: true,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    multimodal: false,
  },
  vlm: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    use_llm: false,
    multimodal: false,
  },
  grounding: {
    enabled: true,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    reuse_llm: true,
    validation_source: "llm",
    tavily_api_key: "",
    serper_api_key: "",
    native_search_enabled: true,
    search_provider: "dashscope_qwen",
    search_reuse_llm: true,
    search_model_name: "",
    search_api_key: "",
    search_base_url: "",
    search_protocol: "DashScope（百炼）",
  },
  asr: {
    enabled: false,
    model_name: "fun-asr",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope Fun-ASR",
    custom_protocol: "",
    provider: "fun-asr",
    language: "",
    reuse_llm_key: true,
  },
  tts: {
    enabled: false,
    model_name: "qwen3-tts-flash",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    voice: "Cherry",
    vc_model_name: "qwen3-tts-vc-2026-01-22",
    reuse_llm_key: true,
  },
  s2v: {
    enabled: false,
    model_name: "wan2.2-s2v",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    detect_model_name: "",
    reuse_llm_key: true,
  },
  embedding: {
    enabled: false,
    model_name: "qwen3-vl-embedding",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    reuse_vlm_key: true,
  },
  image: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    translate_model: "",
    reuse_llm_key: true,
  },
  video: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    reuse_llm_key: true,
  },
  oss: {
    enabled: false,
    access_key_id: "",
    access_key_secret: "",
    endpoint: "",
    bucket: "",
    public_base_url: "",
    policy_api_key: "",
  },
  executionAuthorization: { mode: "required" },
  creationCheckpoints: { mode: "required" },
  mediaReview: { mode: "required" },
  selfReview: {
    sync_enabled: false,
    media_enabled: false,
    render_enabled: false,
    operators: {},
  },
};

// One-dimensional automation ladder projected onto the three persisted
// permission fields. Index equals the slider position.
const PERMISSION_MODES: {
  labelKey: string;
  descriptionKey: string;
  checkpoints: "required" | "skip";
  execution: "required" | "allow_all";
  mediaReview: "required" | "auto_approve";
}[] = [
  {
    labelKey: "modelConfig.permissionMode0Label",
    descriptionKey: "modelConfig.permissionMode0Desc",
    checkpoints: "required",
    execution: "required",
    mediaReview: "required",
  },
  {
    labelKey: "modelConfig.permissionMode1Label",
    descriptionKey: "modelConfig.permissionMode1Desc",
    checkpoints: "skip",
    execution: "required",
    mediaReview: "required",
  },
  {
    labelKey: "modelConfig.permissionMode2Label",
    descriptionKey: "modelConfig.permissionMode2Desc",
    checkpoints: "skip",
    execution: "allow_all",
    mediaReview: "required",
  },
  {
    labelKey: "modelConfig.permissionMode3Label",
    descriptionKey: "modelConfig.permissionMode3Desc",
    checkpoints: "skip",
    execution: "allow_all",
    mediaReview: "auto_approve",
  },
];

function permissionModeIndex(config: ModelConfigData): number {
  if (config.executionAuthorization.mode === "allow_all") {
    return config.mediaReview.mode === "auto_approve" ? 3 : 2;
  }
  if (config.creationCheckpoints.mode === "skip") return 1;
  return 0;
}

// Settings-center navigation: model panes group the existing cards; the
// automation panes host the permission ladder and the self-review tiers.
type SettingsPane =
  | "lang"
  | "perception"
  | "media"
  | "mode"
  | "review"
  | "guide";

const PANE_MODELS: Record<"lang" | "perception" | "media", TabType[]> = {
  lang: ["llm", "vlm", "embedding"],
  perception: ["asr", "grounding"],
  media: ["image", "video", "tts", "s2v"],
};

const PANE_OF_TYPE: Record<TabType, SettingsPane> = {
  llm: "lang",
  vlm: "lang",
  embedding: "lang",
  asr: "perception",
  grounding: "perception",
  image: "media",
  video: "media",
  tts: "media",
  s2v: "media",
};

const VIDEO_MODE_LABEL_KEYS: Record<string, string> = {
  r2v: "modelConfig.videoModeR2v",
  t2v: "modelConfig.videoModeT2v",
  i2v: "modelConfig.videoModeI2v",
  video_edit: "modelConfig.videoModeEdit",
};

function isWan3VideoModel(modelName: string): boolean {
  return /^wan3\.0-video(?:-prime)?$/i.test((modelName || "").trim());
}
// Per-pane title/description plus one scenario hint reusing the onboarding
// guide copy, so the settings center and the guide never diverge.
const MODEL_PANE_META = {
  lang: {
    titleKey: "modelConfig.paneLang",
    descKey: "modelConfig.paneLangDesc",
    hint: {
      sceneKey: "onboarding.modelGuideAllScenes",
      modelsKey: "onboarding.modelGuideLlm",
      whyKey: "onboarding.modelGuideLlmDesc",
    },
  },
  perception: {
    titleKey: "modelConfig.panePerception",
    descKey: "modelConfig.panePerceptionDesc",
    hint: {
      sceneKey: "onboarding.modelGuideAsr",
      modelsKey: "onboarding.modelGuideAsrModels",
      whyKey: "onboarding.modelGuideAsrDesc",
    },
  },
  media: {
    titleKey: "modelConfig.paneMedia",
    descKey: "modelConfig.paneMediaDesc",
    hint: {
      sceneKey: "onboarding.modelGuideDramaGeneral",
      modelsKey: "onboarding.modelGuideDramaModels",
      whyKey: "onboarding.modelGuideDramaGeneralDesc",
    },
  },
} as const;

// Collapsed one-line brief plus the expanded “used for / when needed” note
// for every model card, so users learn each model's role in place.
const CARD_TEXT_KEYS: Record<
  TabType,
  { brief: string; usage: string; need: string }
> = {
  llm: {
    brief: "modelConfig.briefLlm",
    usage: "modelConfig.usageLlm",
    need: "modelConfig.needLlm",
  },
  vlm: {
    brief: "modelConfig.briefVlm",
    usage: "modelConfig.usageVlm",
    need: "modelConfig.needVlm",
  },
  grounding: {
    brief: "modelConfig.briefGrounding",
    usage: "modelConfig.usageGrounding",
    need: "modelConfig.needGrounding",
  },
  asr: {
    brief: "modelConfig.briefAsr",
    usage: "modelConfig.usageAsr",
    need: "modelConfig.needAsr",
  },
  tts: {
    brief: "modelConfig.briefTts",
    usage: "modelConfig.usageTts",
    need: "modelConfig.needTts",
  },
  s2v: {
    brief: "modelConfig.briefS2v",
    usage: "modelConfig.usageS2v",
    need: "modelConfig.needS2v",
  },
  embedding: {
    brief: "modelConfig.briefEmbedding",
    usage: "modelConfig.usageEmbedding",
    need: "modelConfig.needEmbedding",
  },
  image: {
    brief: "modelConfig.briefImage",
    usage: "modelConfig.usageImage",
    need: "modelConfig.needImage",
  },
  video: {
    brief: "modelConfig.briefVideo",
    usage: "modelConfig.usageVideo",
    need: "modelConfig.needVideo",
  },
};

// Mirrors of the backend advisory-round constants, display-only:
// run_review/admission.py MAX_SYNC_REVIEW_ROUNDS / MAX_MEDIA_REVIEW_ROUNDS
// and render_review/protocol.py MAX_REVIEW_ROUNDS. Keep in sync.
const REVIEW_TIER_ROUNDS = { sync: 2, media: 2, render: 3 } as const;

function hasUsableApiKey(item: ModelConfigItem): boolean {
  return item.api_key !== undefined && item.api_key.length > 0;
}

function isFreeTierProtocol(
  protocol: string,
  hostProviders: HostProviderInfo[],
): boolean {
  const provider = hostProviders.find((p) => p.name === protocol);
  if (!provider) return false;
  if (provider.require_api_key === false) return true;
  return provider.models.some((m) => m.is_free === true);
}

function hasFreeModels(
  protocol: string,
  hostProviders: HostProviderInfo[],
): boolean {
  const provider = hostProviders.find((p) => p.name === protocol);
  if (!provider) return false;
  return provider.models.some((m) => m.is_free === true);
}

function groundingValidationModel(config: ModelConfigData): ModelConfigItem {
  if (config.grounding.validation_source === "llm") return config.llm;
  if (config.grounding.validation_source === "vlm") {
    return config.vlm.use_llm ? config.llm : config.vlm;
  }
  return config.grounding;
}

function groundingSearchModel(config: ModelConfigData): ModelConfigItem {
  if (config.grounding.search_reuse_llm) return config.llm;
  return {
    enabled: config.grounding.native_search_enabled,
    model_name: config.grounding.search_model_name,
    api_key: config.grounding.search_api_key,
    base_url: config.grounding.search_base_url,
    protocol: config.grounding.search_protocol,
    custom_protocol: "",
  };
}

/**
 * Check whether a model's protocol/host indicates DashScope/Qwen native
 * search capability. Mirrors the backend ``dashscope_native_search_unavailable_reason``
 * hostname extraction so UI and server agree on edge-case URLs.
 */
export function supportsQwenNativeSearch(item: ModelConfigItem): boolean {
  const protocol = item.protocol.toLocaleLowerCase();
  if (protocol.includes("dashscope") || item.protocol.includes("百炼"))
    return true;
  try {
    const host = new URL(item.base_url).hostname.toLocaleLowerCase();
    return host.includes("dashscope");
  } catch {
    return false;
  }
}

function groundingSearchLabel(config: ModelConfigData): string {
  const providers: string[] = [];
  if (config.grounding.tavily_api_key) providers.push("tavily");
  if (config.grounding.serper_api_key) providers.push("serper");
  const searchModel = groundingSearchModel(config);
  if (
    config.grounding.native_search_enabled &&
    searchModel.model_name &&
    supportsQwenNativeSearch(searchModel)
  ) {
    providers.push(searchModel.model_name);
  }
  return providers.join("/");
}

interface Props {
  open: boolean;
  onClose: () => void;
}

const CARD_META: {
  type: TabType;
  labelKey: string;
  icon: React.ReactNode;
  required: boolean;
}[] = [
  {
    type: "llm",
    labelKey: "modelConfig.llm",
    icon: <Brain size={16} style={{ color: "var(--color-accent)" }} />,
    required: true,
  },
  {
    type: "vlm",
    labelKey: "modelConfig.vlm",
    icon: (
      <EyeOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "grounding",
    labelKey: "modelConfig.grounding",
    icon: (
      <GlobalOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "asr",
    labelKey: "modelConfig.asr",
    icon: (
      <AudioOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "tts",
    labelKey: "modelConfig.tts",
    icon: (
      <SoundOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "s2v",
    labelKey: "modelConfig.s2v",
    icon: (
      <UserOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "embedding",
    labelKey: "modelConfig.embedding",
    icon: (
      <NodeIndexOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "image",
    labelKey: "modelConfig.imageGen",
    icon: (
      <PictureOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "video",
    labelKey: "modelConfig.videoGen",
    icon: (
      <VideoCameraOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
];

export default function ModelConfigModal({ open, onClose }: Props) {
  const { t } = useTranslation();
  const protocolLabel = (protocol: string): string => {
    const key = PROTOCOL_LABEL_KEYS[protocol];
    return key ? t(key) : protocol;
  };
  const [config, setConfig] = useState<ModelConfigData>(DEFAULT_CONFIG);
  const snapshotRef = useRef<ModelConfigData | null>(null);
  // Latest-wins serialization for the permission slider: a drag across
  // several stops fires one onChange per stop; concurrent saves could
  // finish out of order and strand an intermediate stop on the server.
  const permissionSaveRef = useRef<{
    inflight: boolean;
    queued: number | null;
    baseline: ModelConfigData | null;
  }>({ inflight: false, queued: null, baseline: null });

  const savePermissionMode = useCallback(
    async (index: number): Promise<void> => {
      const state = permissionSaveRef.current;
      const target = PERMISSION_MODES[index];
      if (!target) return;
      state.inflight = true;
      try {
        await patchPermissionMode({
          execution: target.execution,
          checkpoints: target.checkpoints,
          mediaReview: target.mediaReview,
        });
        const queued = state.queued;
        state.queued = null;
        if (queued !== null && queued !== index) {
          await savePermissionMode(queued);
          return;
        }
        state.baseline = null;
      } catch (err) {
        const baseline = state.baseline;
        state.baseline = null;
        state.queued = null;
        if (baseline) setConfig(baseline);
        message.error(
          (err as Error).message || t("modelConfig.permissionModeSaveFailed"),
        );
      } finally {
        state.inflight = false;
      }
    },
    [],
  );
  const [activePane, setActivePane] = useState<SettingsPane>("lang");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    llm: true,
  });
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [tested, setTested] = useState<Record<string, boolean>>({});
  const [testingLlmMultimodal, setTestingLlmMultimodal] = useState(false);
  const [testingVlmMultimodal, setTestingVlmMultimodal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [hostProviders, setHostProviders] = useState<HostProviderInfo[]>([]);
  const [ttsCapabilities, setTtsCapabilities] =
    useState<TtsCapabilities | null>(null);
  const [videoCapabilities, setVideoCapabilities] =
    useState<VideoModelCapabilities | null>(null);
  const [videoCapabilitiesLoading, setVideoCapabilitiesLoading] =
    useState(false);
  const [videoCapabilitiesError, setVideoCapabilitiesError] = useState(false);
  // What the user actually typed in a model-name dropdown. Filtering by the
  // field value would hide every other model once one is configured, so the
  // full catalog shows on open and narrows only while typing.
  const [modelSearch, setModelSearch] = useState<Record<string, string>>({});
  // A stale or partial response must not break the whole modal, so the list is
  // normalized once and every consumer reads this instead of the raw payload.
  const ttsModels = ttsCapabilities?.models ?? [];
  const ttsCapability = ttsModels.find(
    (item) => item.model === config.tts.model_name,
  );

  useEffect(() => {
    getHostProviders().then(setHostProviders);
    getTtsCapabilities()
      .then(setTtsCapabilities)
      .catch(() => setTtsCapabilities(null));
  }, []);

  useEffect(() => {
    if (!open || !config.video.model_name.trim()) {
      setVideoCapabilities(null);
      setVideoCapabilitiesLoading(false);
      setVideoCapabilitiesError(false);
      return;
    }
    let active = true;
    setVideoCapabilities(null);
    setVideoCapabilitiesLoading(true);
    setVideoCapabilitiesError(false);
    const timer = window.setTimeout(() => {
      getVideoCapabilities(config.video.model_name, config.video.protocol)
        .then((value) => {
          if (active) setVideoCapabilities(value);
        })
        .catch(() => {
          if (active) {
            setVideoCapabilities(null);
            setVideoCapabilitiesError(true);
          }
        })
        .finally(() => {
          if (active) setVideoCapabilitiesLoading(false);
        });
    }, 120);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [open, config.video.model_name, config.video.protocol]);

  const STATIC_PROVIDER_IDS = new Set(Object.values(PROTOCOL_TO_PROVIDER_ID));

  const dynamicProviderMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const p of hostProviders) {
      if (STATIC_PROVIDER_IDS.has(p.id)) continue;
      const isFree = p.is_free_tier === true;
      const hasKey = !!p.api_key && p.api_key !== "";
      if (isFree || hasKey) {
        map[p.name] = p.id;
      }
    }
    return map;
  }, [hostProviders]);

  const dynamicProtocols = useMemo(
    () => Object.keys(dynamicProviderMap),
    [dynamicProviderMap],
  );

  const mergedProviderMap = useMemo(
    () => ({ ...PROTOCOL_TO_PROVIDER_ID, ...dynamicProviderMap }),
    [dynamicProviderMap],
  );

  // Resolve the real API key (for connection tests).
  const resolveRealApiKey = async (
    section: string,
    item?: ModelConfigItem,
  ): Promise<string> => {
    // Use the key the frontend already holds when it is real (not the
    // mask and not empty).
    if (item && item.api_key && item.api_key !== "__CREATOR_SECRET__") {
      return item.api_key;
    }

    // Otherwise fetch it from the backend.
    try {
      const result = await getRealApiKey(section);
      return result.api_key;
    } catch {
      return "";
    }
  };

  const loadConfig = useCallback(async () => {
    try {
      // Await the shared host-provider fetch so dynamically merged
      // protocols (e.g. OpenCode) are not mistaken for legacy unknown
      // values and reset below.
      const [data, providers] = await Promise.all([
        getModelConfig(),
        getHostProviders(),
      ]);
      const knownHostProtocols = new Set(providers.map((p) => p.name));
      const receivedGrounding = data.grounding as Partial<GroundingConfig>;
      const validationSource =
        receivedGrounding.validation_source ??
        (receivedGrounding.reuse_llm === false ? "custom" : "llm");
      const merged: ModelConfigData = {
        ...DEFAULT_CONFIG,
        ...data,
        grounding: {
          ...DEFAULT_CONFIG.grounding,
          ...data.grounding,
          validation_source: validationSource,
          reuse_llm: validationSource === "llm",
          search_reuse_llm:
            receivedGrounding.search_reuse_llm ??
            receivedGrounding.reuse_llm ??
            true,
        },
        oss: { ...DEFAULT_CONFIG.oss, ...data.oss },
        executionAuthorization: {
          ...DEFAULT_CONFIG.executionAuthorization,
          ...data.executionAuthorization,
        },
        creationCheckpoints: {
          ...DEFAULT_CONFIG.creationCheckpoints,
          ...data.creationCheckpoints,
        },
        mediaReview: {
          ...DEFAULT_CONFIG.mediaReview,
          ...data.mediaReview,
        },
        selfReview: {
          ...DEFAULT_CONFIG.selfReview,
          ...data.selfReview,
        },
      };
      if (
        !VLM_PROTOCOLS.includes(merged.vlm.protocol) &&
        !knownHostProtocols.has(merged.vlm.protocol)
      )
        merged.vlm.protocol = VLM_PROTOCOLS[0];
      if (!ASR_PROTOCOLS.includes(merged.asr.protocol))
        merged.asr.protocol = ASR_PROTOCOLS[0];
      if (!TTS_PROTOCOLS.includes(merged.tts.protocol))
        merged.tts.protocol = TTS_PROTOCOLS[0];
      if (!S2V_PROTOCOLS.includes(merged.s2v.protocol))
        merged.s2v.protocol = S2V_PROTOCOLS[0];
      if (!EMBEDDING_PROTOCOLS.includes(merged.embedding.protocol))
        merged.embedding.protocol = EMBEDDING_PROTOCOLS[0];
      if (!IMAGE_PROTOCOLS.includes(merged.image.protocol))
        merged.image.protocol = IMAGE_PROTOCOLS[0];
      if (!VIDEO_PROTOCOLS.includes(merged.video.protocol))
        merged.video.protocol = VIDEO_PROTOCOLS[0];
      // A never-configured section arrives with empty base_url/model, and a
      // frozen preset URL cannot be typed in. Sections with a single
      // protocol (TTS/S2V) would therefore be unsavable, because switching
      // protocol — the only thing that applies a preset — is impossible.
      PRESET_SEEDED_TYPES.forEach((type) => {
        const item = merged[type] as ModelConfigItem;
        const preset = PRESETS_BY_TYPE[type][item.protocol];
        if (!preset) return;
        if (!item.base_url) item.base_url = preset.base_url;
        if (!item.model_name && preset.models.length === 1)
          item.model_name = preset.models[0];
      });
      // LLM/VLM: seed the protocol's registry default endpoint so a fresh
      // section shows where it will connect instead of an empty field.
      (["llm", "vlm"] as const).forEach((type) => {
        const item = merged[type];
        if (!item.base_url) {
          item.base_url = LLM_PROTOCOL_FALLBACK_BASE_URLS[item.protocol] ?? "";
        }
      });
      // Image/video: seed the protocol preset's endpoint and lead model
      // (qwen-image-3.0-pro / the wan2.7 family) so a fresh section starts
      // from the current Bailian defaults instead of empty fields.
      (["image", "video"] as const).forEach((type) => {
        const item = merged[type] as ModelConfigItem;
        const preset = PRESETS_BY_TYPE[type]?.[item.protocol];
        if (!preset) return;
        if (!item.base_url) item.base_url = preset.base_url;
        if (!item.model_name && preset.models.length > 0)
          item.model_name = preset.models[0];
      });
      const initialTested: Record<string, boolean> = {};
      CARD_META.forEach((meta) => {
        if (meta.type === "grounding") return;
        const item = merged[meta.type] as ModelConfigItem;
        if (item?.enabled) initialTested[meta.type] = true;
      });
      setConfig(merged);
      setTested(initialTested);
      snapshotRef.current = JSON.parse(JSON.stringify(merged));
    } catch {
      setConfig(DEFAULT_CONFIG);
      snapshotRef.current = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
    }
  }, []);

  useEffect(() => {
    if (open) {
      loadConfig();
      setActivePane("lang");
      setExpanded({ llm: true });
    }
  }, [open, loadConfig]);

  const handleReload = useCallback(async () => {
    if (reloading) return;
    setReloading(true);
    try {
      await loadConfig();
      message.success(t("modelConfig.configReloaded"));
    } catch (err) {
      message.error(
        (err as Error).message || t("modelConfig.reloadConfigError"),
      );
    } finally {
      setReloading(false);
    }
  }, [loadConfig, reloading]);

  const updateItem = useCallback(
    (type: ModelType, field: string, value: unknown) => {
      setConfig((prev) => {
        const updated = { ...prev, [type]: { ...prev[type], [field]: value } };
        if (type === "tts" && field === "model_name") {
          // Speech models disagree about voices: those without system voices
          // reject any preset name, and the valid names differ per family, so
          // realign the default voice in the same update.
          const capability = ttsModels.find((item) => item.model === value);
          const voices = capability?.systemVoices ?? [];
          const keep = voices.includes(prev.tts.voice) ? prev.tts.voice : "";
          updated.tts = {
            ...updated.tts,
            voice: keep || voices[0] || "",
          };
        }

        if (
          type === "llm" &&
          // Only real connection-credential edits invalidate a VLM that
          // reuses the LLM config; derived flags like enabled/multimodal
          // (flipped by a successful connectivity test) must not silently
          // disable the VLM — saving right after would persist that state.
          ["base_url", "api_key", "model_name", "protocol"].includes(field) &&
          prev.vlm.use_llm
        ) {
          updated.vlm = { ...updated.vlm, use_llm: false, enabled: false };
        }
        if (
          type === "vlm" &&
          field !== "enabled" &&
          prev.vlm.enabled &&
          !prev.vlm.use_llm
        ) {
          updated.vlm = { ...updated.vlm, enabled: false };
        }
        return updated;
      });
      if (field !== "enabled") {
        setTested((prev) => ({ ...prev, [type]: false }));
        if (type === "llm" || type === "vlm") {
          setTested((prev) => ({
            ...prev,
            groundingValidation: false,
            groundingSearch:
              type === "llm" && config.grounding.search_reuse_llm
                ? false
                : prev.groundingSearch,
          }));
        }
      }
    },
    [config.grounding.search_reuse_llm, ttsModels],
  );

  const updateGrounding = useCallback(
    (field: keyof GroundingConfig, value: unknown) => {
      setConfig((prev) => ({
        ...prev,
        grounding: { ...prev.grounding, [field]: value },
      }));
      if (
        field === "reuse_llm" ||
        field === "validation_source" ||
        field === "api_key" ||
        field === "base_url" ||
        field === "model_name" ||
        field === "protocol"
      ) {
        setTested((prev) => ({ ...prev, groundingValidation: false }));
      }
      if (
        field === "tavily_api_key" ||
        field === "serper_api_key" ||
        field === "native_search_enabled" ||
        field === "search_reuse_llm" ||
        field === "search_api_key" ||
        field === "search_base_url" ||
        field === "search_model_name" ||
        field === "search_protocol"
      ) {
        setTested((prev) => ({ ...prev, groundingSearch: false }));
      }
    },
    [],
  );

  const toggleExpand = useCallback((id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  // Jump straight to one model's card from the guide pane or a hint link.
  const jumpToModel = useCallback((type: TabType) => {
    setActivePane(PANE_OF_TYPE[type]);
    setExpanded((prev) => ({ ...prev, [type]: true }));
  }, []);

  // Persist one self-review tier; optimistic with rollback, mirroring the
  // permission ladder’s failure handling.
  const saveSelfReview = useCallback(
    async (
      tier: "sync_enabled" | "media_enabled" | "render_enabled",
      value: boolean,
    ): Promise<void> => {
      const previous = config.selfReview;
      setConfig((prev) => ({
        ...prev,
        selfReview: { ...prev.selfReview, [tier]: value },
      }));
      try {
        await patchSelfReview({ [tier]: value });
      } catch (err) {
        setConfig((prev) => ({ ...prev, selfReview: previous }));
        message.error(
          (err as Error).message || t("modelConfig.selfReviewSaveFailed"),
        );
      }
    },
    [config.selfReview],
  );

  // Persist one advanced operator switch (高级配置). ``null`` restores
  // the auto (能开尽开) resolution; booleans record an explicit choice.
  // Optimistic with rollback, and the read-only operatorStatus rows are
  // re-derived locally so the badges track the toggle immediately.
  const saveReviewOperator = useCallback(
    async (key: string, value: boolean | null): Promise<void> => {
      const applyLocal = (
        prev: ModelConfigData,
        next: boolean | null,
      ): ModelConfigData => {
        const operators = { ...(prev.selfReview.operators ?? {}) };
        if (next === null) {
          delete operators[key];
        } else {
          operators[key] = next;
        }
        const operatorStatus = (prev.selfReview.operatorStatus ?? []).map(
          (op) =>
            op.key === key
              ? {
                  ...op,
                  source: (next === null ? "auto" : "user") as "auto" | "user",
                  enabled:
                    next === null
                      ? op.capability_ok || Boolean(op.degrades)
                      : next,
                }
              : op,
        );
        return {
          ...prev,
          selfReview: { ...prev.selfReview, operators, operatorStatus },
        };
      };
      // Roll back only THIS pill: a render-time snapshot of the whole
      // section would undo a sibling toggle that succeeded meanwhile.
      const previousValue = config.selfReview.operators?.[key] ?? null;
      setConfig((prev) => applyLocal(prev, value));
      try {
        await patchSelfReview({ operators: { [key]: value } });
      } catch (err) {
        setConfig((prev) => applyLocal(prev, previousValue));
        message.error(
          (err as Error).message || t("modelConfig.selfReviewSaveFailed"),
        );
      }
    },
    [config.selfReview],
  );

  // Restore a whole group of operators to the auto resolution in one
  // PATCH. Restoration lives on the group header (a per-pill ⟳ marker
  // read as a confusing “refresh” icon).
  const restoreReviewOperators = useCallback(
    async (keys: string[]): Promise<void> => {
      if (keys.length === 0) {
        return;
      }
      const previous = config.selfReview;
      setConfig((prev) => {
        const operators = { ...(prev.selfReview.operators ?? {}) };
        for (const key of keys) {
          delete operators[key];
        }
        const operatorStatus = (prev.selfReview.operatorStatus ?? []).map(
          (op) =>
            keys.includes(op.key)
              ? {
                  ...op,
                  source: "auto" as const,
                  enabled: op.capability_ok || Boolean(op.degrades),
                }
              : op,
        );
        return {
          ...prev,
          selfReview: { ...prev.selfReview, operators, operatorStatus },
        };
      });
      try {
        await patchSelfReview({
          operators: Object.fromEntries(keys.map((key) => [key, null])),
        });
      } catch (err) {
        setConfig((prev) => ({ ...prev, selfReview: previous }));
        message.error(
          (err as Error).message || t("modelConfig.selfReviewSaveFailed"),
        );
      }
    },
    [config.selfReview],
  );

  // One click per ladder stop; reuses the latest-wins save queue so a burst
  // of clicks cannot strand an intermediate stop on the server.
  const handleSelectMode = useCallback(
    (index: number) => {
      const target = PERMISSION_MODES[index];
      if (!target) return;
      const state = permissionSaveRef.current;
      if (state.baseline === null) state.baseline = config;
      setConfig((previous) => ({
        ...previous,
        executionAuthorization: { mode: target.execution },
        creationCheckpoints: { mode: target.checkpoints },
        mediaReview: { mode: target.mediaReview },
      }));
      if (state.inflight) {
        state.queued = index;
        return;
      }
      void savePermissionMode(index);
    },
    [config, savePermissionMode],
  );

  const handleVlmToggle = useCallback(
    async (enabled: boolean) => {
      if (!enabled) {
        setConfig((prev) => ({
          ...prev,
          vlm: { ...prev.vlm, enabled: false },
        }));
        setTested((prev) => ({ ...prev, vlm: false }));
        return;
      }

      if (config.vlm.use_llm) {
        setConfig((prev) => ({ ...prev, vlm: { ...prev.vlm, enabled: true } }));
        return;
      }

      const vlmItem = config.vlm;
      const vlmFree = isFreeTierProtocol(vlmItem.protocol, hostProviders);
      if (
        !vlmItem.base_url ||
        !vlmItem.model_name ||
        (!vlmFree && !hasUsableApiKey(vlmItem))
      ) {
        message.warning(t("modelConfig.fillCompleteVlm"));
        return;
      }

      setTestingVlmMultimodal(true);
      try {
        const data = await testModelConnection({
          type: "vlm",
          base_url: vlmItem.base_url,
          api_key: vlmItem.api_key,
          model_name: vlmItem.model_name,
          protocol: vlmItem.protocol,
          require_api_key: !vlmFree,
        });
        if (data.ok) {
          message.success(t("modelConfig.multimodalTestPassed"));
          setTested((prev) => ({ ...prev, vlm: true }));
          setConfig((prev) => ({
            ...prev,
            vlm: { ...prev.vlm, enabled: true, multimodal: true },
          }));
        } else {
          message.warning(data.error || t("modelConfig.multimodalTestFailed"));
          setTested((prev) => ({ ...prev, vlm: false }));
        }
      } catch (err) {
        message.error(
          (err as Error).message || t("modelConfig.multimodalTestError"),
        );
        setTested((prev) => ({ ...prev, vlm: false }));
      } finally {
        setTestingVlmMultimodal(false);
      }
    },
    [config],
  );

  const handleVlmUseLlm = useCallback(
    async (checked: boolean) => {
      if (!checked) {
        setConfig((prev) => ({
          ...prev,
          vlm: { ...prev.vlm, use_llm: false },
        }));
        return;
      }

      const llmItem = config.llm;
      const llmFree = isFreeTierProtocol(llmItem.protocol, hostProviders);
      if (
        !llmItem.base_url ||
        !llmItem.model_name ||
        (!llmFree && !hasUsableApiKey(llmItem))
      ) {
        message.warning(t("modelConfig.fillCompleteLlm"));
        return;
      }

      setTestingLlmMultimodal(true);
      try {
        // Resolve the real API key (the frontend only stores the mask).
        const realApiKey = await resolveRealApiKey("llm", llmItem);
        const data = await testModelConnection({
          type: "vlm",
          base_url: llmItem.base_url,
          api_key: realApiKey,
          model_name: llmItem.model_name,
          protocol: llmItem.protocol,
          require_api_key: !llmFree,
        });
        if (data.ok) {
          message.success(t("modelConfig.multimodalTestPassedReuse"));
          setTested((prev) => ({ ...prev, vlm: true, llm: true }));
          setConfig((prev) => ({
            ...prev,
            llm: { ...prev.llm, multimodal: true },
            vlm: { ...prev.vlm, use_llm: true, enabled: true },
          }));
        } else {
          message.warning(
            data.error || t("modelConfig.multimodalTestFailedReuse"),
          );
          setTested((prev) => ({ ...prev, vlm: false }));
        }
      } catch (err) {
        message.error(
          (err as Error).message || t("modelConfig.multimodalTestError"),
        );
        setTested((prev) => ({ ...prev, vlm: false }));
      } finally {
        setTestingLlmMultimodal(false);
      }
    },
    [config],
  );

  const handleTest = useCallback(
    async (type: ModelType): Promise<boolean> => {
      let item = config[type] as ModelConfigItem;
      if (type === "vlm" && config.vlm.use_llm) {
        item = config.llm;
      }
      const isFree = isFreeTierProtocol(item.protocol, hostProviders);
      const hasKey = isFree
        ? true
        : (type === "asr" && config.asr.reuse_llm_key) ||
          (type === "tts" && config.tts.reuse_llm_key) ||
          (type === "s2v" && config.s2v.reuse_llm_key) ||
          (type === "image" && config.image.reuse_llm_key) ||
          (type === "video" && config.video.reuse_llm_key)
        ? hasUsableApiKey(config.llm)
        : type === "embedding" && config.embedding.reuse_vlm_key
        ? hasUsableApiKey(config.vlm.use_llm ? config.llm : config.vlm) ||
          hasUsableApiKey(config.llm)
        : hasUsableApiKey(item);
      if (!item.base_url || !hasKey || !item.model_name) {
        message.warning(t("modelConfig.fillComplete"));
        return false;
      }

      setTesting((prev) => ({ ...prev, [type]: true }));
      try {
        // Resolve the real API key (the frontend only stores the mask).
        let testApiKey: string;
        if (
          (type === "asr" && config.asr.reuse_llm_key) ||
          (type === "tts" && config.tts.reuse_llm_key) ||
          (type === "s2v" && config.s2v.reuse_llm_key) ||
          (type === "image" && config.image.reuse_llm_key) ||
          (type === "video" && config.video.reuse_llm_key)
        ) {
          // ASR/TTS/S2V/Image/Video can reuse the LLM API key (same
          // DashScope credential).
          testApiKey = await resolveRealApiKey("llm", config.llm);
        } else if (type === "embedding" && config.embedding.reuse_vlm_key) {
          // Embedding reuses the VLM key (which may itself reuse the LLM).
          const vlmSection = config.vlm.use_llm ? "llm" : "vlm";
          const vlmItem = config.vlm.use_llm ? config.llm : config.vlm;
          testApiKey =
            (await resolveRealApiKey(vlmSection, vlmItem)) ||
            (await resolveRealApiKey("llm", config.llm));
        } else if (type === "vlm" && config.vlm.use_llm) {
          // VLM reuses the LLM config.
          testApiKey = await resolveRealApiKey("llm", config.llm);
        } else {
          // Use the API key of the current section.
          testApiKey = await resolveRealApiKey(type, item);
        }

        const data = await testModelConnection({
          type,
          base_url: item.base_url,
          api_key: testApiKey,
          model_name: item.model_name,
          protocol: item.protocol,
          provider: type === "asr" ? config.asr.provider : undefined,
          voice: type === "tts" ? config.tts.voice : undefined,
          require_api_key: !isFree,
        });
        if (data.ok) {
          message.success(t("modelConfig.connectionTestSuccess"));
          setTested((prev) => ({ ...prev, [type]: true }));
          updateItem(type, "enabled", true);
          return true;
        } else {
          message.warning(data.error || t("modelConfig.connectionTestFailed"));
          setTested((prev) => ({ ...prev, [type]: false }));
          return false;
        }
      } catch (err) {
        message.error(
          (err as Error).message || t("modelConfig.connectionTestError"),
        );
        setTested((prev) => ({ ...prev, [type]: false }));
        return false;
      } finally {
        setTesting((prev) => ({ ...prev, [type]: false }));
      }
    },
    [config, updateItem],
  );

  // Enabling a model runs the connectivity probe first and only switches
  // the card on after a passing test, so an enabled card is never left in
  // the red "untested" state; a failed or incomplete probe keeps it off.
  const handleEnableToggle = useCallback(
    async (type: ModelType, checked: boolean): Promise<void> => {
      if (type === "vlm") {
        await handleVlmToggle(checked);
        return;
      }
      if (!checked) {
        updateItem(type, "enabled", false);
        setTested((prev) => ({ ...prev, [type]: false }));
        return;
      }
      // handleTest itself validates the fields (warning toast when
      // incomplete) and only enables the card after a passing probe, so no
      // pre-check is needed here.
      await handleTest(type);
    },
    [handleTest, handleVlmToggle, updateItem],
  );

  const handleGroundingTest = useCallback(async (): Promise<boolean> => {
    const item = groundingValidationModel(config);
    const groundingFree = isFreeTierProtocol(item.protocol, hostProviders);
    if (
      !item.base_url ||
      (!groundingFree && !hasUsableApiKey(item)) ||
      !item.model_name
    ) {
      message.warning(t("modelConfig.groundingFillComplete"));
      return false;
    }

    setTesting((prev) => ({ ...prev, grounding: true }));
    try {
      // Resolve the real API key (the frontend only stores the mask),
      // picking the section that matches the validation model source.
      let realApiKey = item.api_key;
      if (config.grounding.validation_source === "llm") {
        realApiKey = await resolveRealApiKey("llm", config.llm);
      } else if (config.grounding.validation_source === "vlm") {
        const vlmSection = config.vlm.use_llm ? "llm" : "vlm";
        const vlmItem = config.vlm.use_llm ? config.llm : config.vlm;
        realApiKey = await resolveRealApiKey(vlmSection, vlmItem);
      } else {
        realApiKey = await resolveRealApiKey("grounding", item);
      }

      const data = await testModelConnection({
        type: "vlm",
        base_url: item.base_url,
        api_key: realApiKey,
        model_name: item.model_name,
        protocol: item.protocol,
        require_api_key: !groundingFree,
      });
      if (!data.ok) {
        message.warning(
          data.error || t("modelConfig.groundingVerifyTestFailed"),
        );
        setTested((prev) => ({ ...prev, groundingValidation: false }));
        return false;
      }
      message.success(t("modelConfig.groundingVerifyTestSuccess"));
      setTested((prev) => ({ ...prev, groundingValidation: true }));
      return true;
    } catch (err) {
      message.error(
        (err as Error).message || t("modelConfig.groundingVerifyTestError"),
      );
      setTested((prev) => ({ ...prev, groundingValidation: false }));
      return false;
    } finally {
      setTesting((prev) => ({ ...prev, grounding: false }));
    }
  }, [config]);

  const handleSave = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      const prev = snapshotRef.current;
      if (!prev) throw new Error(t("modelConfig.snapshotLost"));

      if (config.grounding.enabled) {
        const groundingModel = groundingValidationModel(config);
        const groundingFree = isFreeTierProtocol(
          groundingModel.protocol,
          hostProviders,
        );
        if (
          !groundingModel.base_url ||
          !groundingModel.model_name ||
          (!groundingFree && !hasUsableApiKey(groundingModel))
        ) {
          message.warning(t("modelConfig.groundingDefaultOn"));
          return;
        }
        const searchModel = groundingSearchModel(config);
        const searchFree = isFreeTierProtocol(
          searchModel.protocol,
          hostProviders,
        );
        const nativeSearchReady =
          config.grounding.native_search_enabled &&
          !!searchModel.base_url &&
          !!searchModel.model_name &&
          (searchFree || hasUsableApiKey(searchModel)) &&
          supportsQwenNativeSearch(searchModel);
        if (
          !config.grounding.tavily_api_key &&
          !config.grounding.serper_api_key &&
          !nativeSearchReady
        ) {
          message.warning(t("modelConfig.groundingSearchNotConfigured"));
          return;
        }
      }

      const dirtySections: TabType[] = [];
      for (const section of [
        "llm",
        "vlm",
        "grounding",
        "asr",
        "tts",
        "s2v",
        "embedding",
        "image",
        "video",
      ] as TabType[]) {
        if (JSON.stringify(config[section]) !== JSON.stringify(prev[section])) {
          dirtySections.push(section);
        }
      }

      for (const section of dirtySections) {
        if (section !== "grounding" && !tested[section]) {
          const ok = await handleTest(section);
          if (!ok) return;
        }
      }

      if (dirtySections.length > 0) {
        // Save everything in one POST: sequential per-section PATCHes each
        // re-validate the full grounding config, so interdependent edits
        // (e.g. a generic LLM plus a Tavily key) could fail mid-sequence
        // and leave a partially saved configuration behind.
        const res = await saveModelConfig(config);
        if (!res.ok) throw new Error(t("modelConfig.saveFailedServer"));
      }

      message.success(t("modelConfig.configSaved"));
      snapshotRef.current = JSON.parse(JSON.stringify(config));
      onClose();
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : t("modelConfig.unknownError");
      message.error(t("modelConfig.saveFailed", { detail }));
    } finally {
      setSaving(false);
    }
  }, [config, tested, saving, handleTest, onClose]);

  const handleCancel = useCallback(() => {
    if (snapshotRef.current)
      setConfig(JSON.parse(JSON.stringify(snapshotRef.current)));
    onClose();
  }, [onClose]);

  const protocolsFor = (type: ModelType) => {
    const base =
      type === "llm"
        ? LLM_PROTOCOLS
        : type === "vlm"
        ? VLM_PROTOCOLS
        : type === "asr"
        ? ASR_PROTOCOLS
        : type === "tts"
        ? TTS_PROTOCOLS
        : type === "s2v"
        ? S2V_PROTOCOLS
        : type === "embedding"
        ? EMBEDDING_PROTOCOLS
        : type === "image"
        ? IMAGE_PROTOCOLS
        : VIDEO_PROTOCOLS;
    if (type === "llm" || type === "vlm") {
      const withDynamic = [...base, ...dynamicProtocols];
      const customIdx = withDynamic.indexOf("自定义");
      if (customIdx !== -1 && customIdx !== withDynamic.length - 1) {
        withDynamic.splice(customIdx, 1);
        withDynamic.push("自定义");
      }
      return withDynamic;
    }
    return base;
  };

  const getPresetForType = (
    type: ModelType,
    protocol: string,
  ): ProtocolPreset | null => {
    if (type === "llm" || type === "vlm") {
      const providerId = mergedProviderMap[protocol];
      if (!providerId) return null;
      const provider = hostProviders.find((p) => p.id === providerId);
      if (!provider) {
        const fallback = LLM_PROTOCOL_FALLBACK_BASE_URLS[protocol];
        return fallback ? { base_url: fallback, models: [] } : null;
      }
      return {
        base_url: provider.base_url,
        models: [
          ...provider.models.map((m) => m.id),
          ...provider.extra_models.map((m) => m.id),
        ],
        base_url_options: provider.meta?.base_url_options,
      };
    }
    if (type === "asr") return ASR_PRESETS[protocol] || null;
    if (type === "s2v") return S2V_PRESETS[protocol] || null;
    if (type === "tts") {
      const preset = TTS_PRESETS[protocol];
      if (!preset) return null;
      // Supported speech models come from the backend capability table.
      return {
        ...preset,
        models: ttsModels.map((item) => item.model),
      };
    }
    if (type === "embedding") return EMBEDDING_PRESETS[protocol] || null;
    if (type === "image") return IMAGE_PRESETS[protocol] || null;
    if (type === "video") return VIDEO_PRESETS[protocol] || null;
    return null;
  };

  const getModelOptions = (
    type: ModelType,
    protocol: string,
  ): { value: string; label: string }[] => {
    if (type === "llm" || type === "vlm") {
      const providerId = mergedProviderMap[protocol];
      if (!providerId) return [];
      const provider = hostProviders.find((p) => p.id === providerId);
      if (!provider) return [];
      return [
        ...provider.models.map((m) => ({
          value: m.id,
          label: m.is_free ? `${m.id} (免费)` : m.id,
        })),
        ...provider.extra_models.map((m) => ({ value: m.id, label: m.id })),
      ];
    }
    if (type === "tts") {
      // Label each speech model with what it can do, so the choice between
      // "has system voices" and "must design a voice first" is visible.
      return ttsModels.map((item) => ({
        value: item.model,
        label: item.label,
      }));
    }
    const preset = getPresetForType(type, protocol);
    if (!preset?.models.length) return [];
    return preset.models.map((m) => ({ value: m, label: m }));
  };

  const handleProtocolChange = async (type: ModelType, protocol: string) => {
    updateItem(type, "protocol", protocol);
    const preset = getPresetForType(type, protocol);
    if (preset) {
      if (preset.base_url_options?.length) {
        updateItem(type, "base_url", preset.base_url_options[0].value);
      } else if (preset.base_url !== undefined) {
        updateItem(type, "base_url", preset.base_url);
      }
      if (preset.models.length > 0) {
        const currentModel = (config[type] as ModelConfigItem).model_name;
        if (!preset.models.includes(currentModel)) {
          updateItem(type, "model_name", preset.models[0]);
        }
      }
    }

    // For LLM/VLM on their first configuration (empty api_key), try to
    // sync the API key from the host.
    if ((type === "llm" || type === "vlm") && protocol !== "自定义") {
      const currentItem = config[type] as ModelConfigItem;
      if (
        !currentItem.api_key ||
        currentItem.api_key === "__CREATOR_SECRET__"
      ) {
        const providerId = mergedProviderMap[protocol];
        if (providerId) {
          const hostProvider = hostProviders.find((p) => p.id === providerId);
          if (hostProvider?.require_api_key === false) {
            // Free-tier provider — no key needed.
          } else {
            try {
              const result = await getHostProviderApiKey(providerId);
              if (result.api_key) {
                updateItem(type, "api_key", result.api_key);
              }
            } catch (error) {
              console.warn(
                `Failed to sync API key from host for ${providerId}:`,
                error,
              );
            }
          }
        }
      }
    }

    if (type === "asr") {
      const provider = protocol === "OpenAI Whisper" ? "whisper" : "fun-asr";
      updateItem("asr", "provider", provider);
    }
  };

  // Host-console convention for stored secrets: the field stays empty with
  // a “leave blank to keep” hint; typing replaces the key and clearing the
  // field falls back to the stored credential instead of erasing it.
  const secretInput = (
    current: string,
    storedInSnapshot: boolean,
    emptyPlaceholder: string,
    commit: (value: string) => void,
  ) => (
    <Input.Password
      visibilityToggle={false}
      placeholder={
        current === "__CREATOR_SECRET__"
          ? t("modelConfig.leaveBlankKeep")
          : emptyPlaceholder
      }
      value={current === "__CREATOR_SECRET__" ? "" : current}
      onChange={(event) => {
        const next = event.target.value;
        commit(next === "" && storedInSnapshot ? "__CREATOR_SECRET__" : next);
      }}
    />
  );

  const renderFields = (type: ModelType) => {
    const item = config[type] as ModelConfigItem;
    const preset = getPresetForType(type, item.protocol);
    const modelOptions = getModelOptions(type, item.protocol);
    const hasPresetModels = modelOptions.length > 0;
    const hasBaseUrlOptions = (preset?.base_url_options?.length ?? 0) > 0;
    // DashScope sections ride the text-model credential by default; while
    // the persisted reuse flag is on, the key field says so instead of
    // asking for a second copy of the same secret.
    const reuseFlag =
      type === "asr"
        ? config.asr.reuse_llm_key
        : type === "tts"
        ? config.tts.reuse_llm_key
        : type === "s2v"
        ? config.s2v.reuse_llm_key
        : type === "image"
        ? config.image.reuse_llm_key
        : type === "video"
        ? config.video.reuse_llm_key
        : type === "embedding"
        ? config.embedding.reuse_vlm_key
        : null;
    const reuseSourceLabel = type === "embedding" ? "VLM" : "LLM";
    const reusingKey = reuseFlag === true;

    return (
      <>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "0 16px",
          }}
        >
          <div>
            <label className="field-label">
              {t("modelConfig.apiProtocol")}
            </label>
            <Select
              value={item.protocol}
              onChange={(v) => handleProtocolChange(type, v)}
              options={protocolsFor(type).map((p) => {
                const provider = hostProviders.find((hp) => hp.name === p);
                const isFullyFree = provider?.require_api_key === false;
                const hasFree = hasFreeModels(p, hostProviders);
                let suffix = "";
                if (isFullyFree) {
                  suffix = " (免费)";
                } else if (hasFree) {
                  suffix = " (含免费模型)";
                }
                return {
                  value: p,
                  label: `${protocolLabel(p)}${suffix}`,
                };
              })}
            />
            {item.protocol === "自定义" && (
              <Input
                className="mt-2"
                placeholder={t("modelConfig.inputProtocolName")}
                value={item.custom_protocol}
                onChange={(e) =>
                  updateItem(type, "custom_protocol", e.target.value)
                }
              />
            )}
          </div>
          <div>
            <label className="field-label">{t("modelConfig.modelName")}</label>
            {hasPresetModels ? (
              <AutoComplete
                value={item.model_name}
                onChange={(v) => updateItem(type, "model_name", v)}
                options={modelOptions.filter((option) => {
                  const typed = (modelSearch[type] ?? "").toLowerCase();
                  if (!typed) return true;
                  return (
                    option.label.toLowerCase().includes(typed) ||
                    option.value.toLowerCase().includes(typed)
                  );
                })}
                onSearch={(typed) =>
                  setModelSearch((prev) => ({ ...prev, [type]: typed }))
                }
                onFocus={() =>
                  setModelSearch((prev) => ({ ...prev, [type]: "" }))
                }
                placeholder={t("modelConfig.selectOrInputModel")}
              />
            ) : (
              <Input
                placeholder="model"
                value={item.model_name}
                onChange={(e) => updateItem(type, "model_name", e.target.value)}
              />
            )}
          </div>
          <div>
            <label className="field-label">API Key</label>
            {reusingKey ? (
              <Input
                disabled
                value=""
                placeholder={t("modelConfig.reusingKeyPlaceholder", {
                  model: reuseSourceLabel,
                })}
              />
            ) : (
              secretInput(
                item.api_key,
                (snapshotRef.current?.[type] as ModelConfigItem | undefined)
                  ?.api_key === "__CREATOR_SECRET__",
                "sk-...",
                (value) => updateItem(type, "api_key", value),
              )
            )}
          </div>
          <div>
            <label className="field-label">Base URL</label>
            {hasBaseUrlOptions ? (
              <AutoComplete
                value={item.base_url}
                onChange={(v) => updateItem(type, "base_url", v)}
                options={preset!.base_url_options!.map((opt) => ({
                  value: opt.value,
                  label: opt.label,
                }))}
                style={{ width: "100%" }}
              />
            ) : (
              <Input
                placeholder="https://api.example.com"
                value={item.base_url}
                onChange={(e) => updateItem(type, "base_url", e.target.value)}
              />
            )}
          </div>
        </div>
        {(type === "image" || type === "video") &&
          (item.protocol.toLowerCase().includes("dashscope") ||
            item.protocol.includes("百炼") ||
            item.protocol.toLowerCase().includes("token plan")) && (
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <Checkbox
                checked={
                  type === "image"
                    ? config.image.reuse_llm_key
                    : config.video.reuse_llm_key
                }
                onChange={(e) => {
                  const checked = e.target.checked;
                  updateItem(type, "reuse_llm_key", checked);
                  if (checked) {
                    updateItem(type, "api_key", "");
                  }
                }}
              >
                {t("modelConfig.reuseLlmApiKey")}
              </Checkbox>
            </div>
          )}
        {type === "asr" && (
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <Checkbox
              checked={config.asr.reuse_llm_key}
              onChange={(e) => {
                const checked = e.target.checked;
                updateItem("asr", "reuse_llm_key", checked);
                if (checked) {
                  updateItem("asr", "api_key", "");
                }
              }}
            >
              {t("modelConfig.reuseLlmApiKey")}
            </Checkbox>
            <Input
              style={{ width: 220 }}
              placeholder={t("modelConfig.languageOptional")}
              value={config.asr.language}
              onChange={(e) => updateItem("asr", "language", e.target.value)}
            />
          </div>
        )}
        {type === "tts" && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "0 16px",
            }}
          >
            <div style={{ gridColumn: "1 / -1", marginBottom: 4 }}>
              <Checkbox
                checked={config.tts.reuse_llm_key}
                onChange={(e) => {
                  const checked = e.target.checked;
                  updateItem("tts", "reuse_llm_key", checked);
                  if (checked) {
                    updateItem("tts", "api_key", "");
                  }
                }}
              >
                {t("modelConfig.reuseLlmApiKey")}
              </Checkbox>
            </div>
            {(ttsCapability?.systemVoices.length ?? 0) > 0 && (
              <div>
                <label className="field-label">
                  {t("modelConfig.ttsNarratorVoice")}
                </label>
                <AutoComplete
                  value={config.tts.voice}
                  onChange={(v) => updateItem("tts", "voice", v)}
                  options={(ttsCapability?.systemVoices ?? []).map((v) => ({
                    value: v,
                    label: v,
                  }))}
                  placeholder={t("modelConfig.ttsVoicePlaceholder")}
                />
              </div>
            )}
            <p
              style={{
                gridColumn: "1 / -1",
                margin: "2px 0 0",
                fontSize: 11,
                lineHeight: 1.6,
                color: "var(--color-text-tertiary)",
              }}
            >
              {ttsCapability && ttsCapability.systemVoices.length === 0
                ? t("modelConfig.ttsNoSystemVoicesNote")
                : t("modelConfig.ttsSystemVoicesNote")}
              {t("modelConfig.ttsCloneModelAutoNote")}
            </p>
          </div>
        )}
        {type === "s2v" && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "0 16px",
            }}
          >
            <div style={{ gridColumn: "1 / -1", marginBottom: 4 }}>
              <Checkbox
                checked={config.s2v.reuse_llm_key}
                onChange={(e) => {
                  const checked = e.target.checked;
                  updateItem("s2v", "reuse_llm_key", checked);
                  if (checked) {
                    updateItem("s2v", "api_key", "");
                  }
                }}
              >
                {t("modelConfig.reuseLlmApiKey")}
              </Checkbox>
            </div>
            <div>
              <label className="field-label">
                {t("modelConfig.s2vDetectModelLabel")}
              </label>
              <Input
                placeholder="wan2.2-s2v-detect"
                value={config.s2v.detect_model_name}
                onChange={(e) =>
                  updateItem("s2v", "detect_model_name", e.target.value)
                }
              />
            </div>
            <p
              style={{
                gridColumn: "1 / -1",
                margin: "2px 0 0",
                fontSize: 11,
                lineHeight: 1.6,
                color: "var(--color-text-tertiary)",
              }}
            >
              {t("modelConfig.s2vDetectNote")}
            </p>
          </div>
        )}
        {type === "embedding" && (
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <Checkbox
              checked={config.embedding.reuse_vlm_key}
              onChange={(e) => {
                const checked = e.target.checked;
                updateItem("embedding", "reuse_vlm_key", checked);
                if (checked) {
                  updateItem("embedding", "api_key", "");
                }
              }}
            >
              {t("modelConfig.reuseVlmApiKey")}
            </Checkbox>
            <span
              style={{
                fontSize: 11,
                color: "var(--color-text-tertiary)",
              }}
            >
              {t("modelConfig.embeddingReuseNote")}
            </span>
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Button
            className="test-btn"
            icon={<LinkOutlined />}
            loading={testing[type]}
            onClick={() => handleTest(type)}
          >
            {t("modelConfig.testConnection")}
          </Button>
        </div>
      </>
    );
  };

  const toggleControl = (type: ModelType) => {
    if (type === "llm") return null;
    const item = config[type] as ModelConfigItem;
    const meta = CARD_META.find((card) => card.type === type);
    const busy =
      (type === "vlm" && testingVlmMultimodal === true) ||
      testing[type] === true;
    return (
      <>
        <label className="desktop-toggle" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            aria-label={meta ? t(meta.labelKey) : type}
            checked={item.enabled}
            disabled={busy}
            onChange={(e) => {
              void handleEnableToggle(type, e.target.checked);
            }}
          />
          <div className="track" />
          <div className="thumb" />
        </label>
        {busy && (
          <span
            style={{
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              whiteSpace: "nowrap",
            }}
          >
            {type === "vlm"
              ? t("modelConfig.multimodalTesting")
              : t("modelConfig.connectionTesting")}
          </span>
        )}
      </>
    );
  };

  const renderGroundingCard = (meta: (typeof CARD_META)[number]) => {
    const { type, labelKey, icon } = meta;
    const isExpanded = expanded.grounding;
    const verifier = groundingValidationModel(config);
    const searchModel = groundingSearchModel(config);
    const verifierFree = isFreeTierProtocol(verifier.protocol, hostProviders);
    const verifierReady =
      !!verifier.model_name &&
      !!verifier.base_url &&
      (verifierFree || hasUsableApiKey(verifier));
    const searchFree = isFreeTierProtocol(searchModel.protocol, hostProviders);
    const nativeSearchReady =
      config.grounding.native_search_enabled &&
      !!searchModel.model_name &&
      !!searchModel.base_url &&
      (searchFree || hasUsableApiKey(searchModel)) &&
      supportsQwenNativeSearch(searchModel);
    const searchReady =
      !!config.grounding.tavily_api_key ||
      !!config.grounding.serper_api_key ||
      nativeSearchReady;
    const searchLabel = groundingSearchLabel(config);

    return (
      <div
        key={type}
        className="glass-card"
        style={{ borderRadius: 8, boxShadow: "var(--shadow-xs)" }}
      >
        <div
          onClick={() => toggleExpand("grounding")}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 18px",
            cursor: "pointer",
            userSelect: "none",
            borderBottom: isExpanded ? "1px solid var(--color-border)" : "none",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span
              style={{
                width: 30,
                height: 30,
                borderRadius: 8,
                background: "var(--color-bg-layout)",
                border: "1px solid var(--color-border)",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              {icon}
            </span>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{t(labelKey)}</span>
            <span
              style={{
                fontSize: 10,
                color: "var(--color-text-tertiary)",
                background: "var(--color-bg-secondary)",
                padding: "1px 7px",
                borderRadius: 4,
              }}
            >
              {t("modelConfig.searchVerifyDecoupled")}
            </span>
            {config.grounding.enabled &&
              (searchLabel || verifier.model_name) && (
                <span
                  className="text-ellipsis"
                  style={{
                    fontSize: 10,
                    color:
                      verifierReady && searchReady
                        ? "var(--color-success)"
                        : "var(--color-text-tertiary)",
                    background: "var(--color-success-soft)",
                    padding: "1px 7px",
                    borderRadius: 4,
                    maxWidth: 140,
                  }}
                >
                  {searchLabel || t("modelConfig.notConfiguredSearch")}
                  {verifier.model_name ? ` · ${verifier.model_name}` : ""}
                </span>
              )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: config.grounding.enabled
                  ? "var(--color-success)"
                  : "var(--color-border)",
              }}
            />
            <label
              className="desktop-toggle"
              onClick={(event) => event.stopPropagation()}
            >
              <input
                type="checkbox"
                aria-label={t("modelConfig.enableGrounding")}
                checked={config.grounding.enabled}
                onChange={(event) =>
                  updateGrounding("enabled", event.target.checked)
                }
              />
              <div className="track" />
              <div className="thumb" />
            </label>
            <DownOutlined
              style={{
                fontSize: 10,
                color: "var(--color-text-tertiary)",
                transition: "transform 0.2s",
                transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
              }}
            />
          </div>
        </div>
        {isExpanded && (
          <div
            style={{
              padding: "16px 18px 32px",
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
            <div
              style={{
                borderLeft: "3px solid var(--color-accent)",
                background: "var(--color-bg-layout)",
                borderRadius: "0 8px 8px 0",
                padding: "7px 12px",
                fontSize: 11.5,
                lineHeight: 1.6,
                color: "var(--color-text-secondary)",
                display: "flex",
                flexDirection: "column",
                gap: 3,
              }}
            >
              <span>
                <b
                  style={{
                    color: "var(--color-text-primary)",
                    marginRight: 4,
                  }}
                >
                  {t("modelConfig.usageLabel")}
                </b>
                {t(CARD_TEXT_KEYS.grounding.usage)}
              </span>
              <span>
                <b style={{ color: "var(--color-accent)", marginRight: 4 }}>
                  {t("modelConfig.needLabel")}
                </b>
                {t(CARD_TEXT_KEYS.grounding.need)}
              </span>
            </div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              {t("modelConfig.search")}
            </div>
            {/* Priority chain: Tavily first, Qwen native search fallback. */}
            <div
              style={{
                border: "1px solid var(--color-border)",
                borderRadius: 8,
                padding: "12px 14px",
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "1px 6px",
                    borderRadius: 4,
                    background: "var(--color-accent-soft)",
                    color: "var(--color-accent)",
                    flexShrink: 0,
                  }}
                >
                  {t("modelConfig.priority")}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: "var(--color-text-primary)",
                  }}
                >
                  {t("modelConfig.tavilySearch")}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: config.grounding.tavily_api_key
                      ? "var(--color-success)"
                      : "var(--color-text-tertiary)",
                  }}
                >
                  {config.grounding.tavily_api_key
                    ? t("modelConfig.configured")
                    : t("modelConfig.tavilyNotConfigured")}
                </span>
              </div>
              <div>
                <label className="field-label">
                  {t("modelConfig.tavilyApiKeyOptional")}
                </label>
                {secretInput(
                  config.grounding.tavily_api_key,
                  snapshotRef.current?.grounding.tavily_api_key ===
                    "__CREATOR_SECRET__",
                  "tvly-...",
                  (value) => updateGrounding("tavily_api_key", value),
                )}
              </div>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                margin: "-8px 0 -8px 16px",
                fontSize: 13,
                lineHeight: 1,
                color: "var(--color-text-tertiary)",
              }}
            >
              ↓
            </div>
            {/* Second choice: Serper (Google search), tried after Tavily. */}
            <div
              style={{
                border: "1px solid var(--color-border)",
                borderRadius: 8,
                padding: "12px 14px",
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "1px 6px",
                    borderRadius: 4,
                    background: "var(--color-bg-secondary)",
                    color: "var(--color-text-secondary)",
                    flexShrink: 0,
                  }}
                >
                  {t("modelConfig.secondary")}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: "var(--color-text-primary)",
                  }}
                >
                  {t("modelConfig.serperSearch")}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: config.grounding.serper_api_key
                      ? "var(--color-success)"
                      : "var(--color-text-tertiary)",
                  }}
                >
                  {config.grounding.serper_api_key
                    ? t("modelConfig.configured")
                    : t("modelConfig.configuredSkipChannel")}
                </span>
              </div>
              <div>
                <label className="field-label">
                  {t("modelConfig.serperApiKeyOptional")}
                </label>
                {secretInput(
                  config.grounding.serper_api_key,
                  snapshotRef.current?.grounding.serper_api_key ===
                    "__CREATOR_SECRET__",
                  "serper key",
                  (value) => updateGrounding("serper_api_key", value),
                )}
              </div>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                margin: "-8px 0 -8px 16px",
                fontSize: 13,
                lineHeight: 1,
                color: "var(--color-text-tertiary)",
              }}
            >
              ↓
            </div>
            <div
              style={{
                border: "1px solid var(--color-border)",
                borderRadius: 8,
                padding: "12px 14px",
                display: "flex",
                flexDirection: "column",
                gap: 10,
                opacity: config.grounding.native_search_enabled ? 1 : 0.75,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "1px 6px",
                    borderRadius: 4,
                    background: "var(--color-bg-secondary)",
                    color: "var(--color-text-secondary)",
                    flexShrink: 0,
                  }}
                >
                  {t("modelConfig.fallback")}
                </span>
                <Checkbox
                  checked={config.grounding.native_search_enabled}
                  onChange={(event) =>
                    updateGrounding(
                      "native_search_enabled",
                      event.target.checked,
                    )
                  }
                >
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: "var(--color-text-primary)",
                    }}
                  >
                    {t("modelConfig.qwenDashScopeNativeSearch")}
                  </span>
                </Checkbox>
              </div>
              {config.grounding.native_search_enabled ? (
                <div
                  style={{
                    borderLeft: "2px solid var(--color-border)",
                    marginLeft: 5,
                    paddingLeft: 14,
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                    }}
                  >
                    <Checkbox
                      checked={config.grounding.search_reuse_llm}
                      onChange={(event) =>
                        updateGrounding(
                          "search_reuse_llm",
                          event.target.checked,
                        )
                      }
                    >
                      <span
                        style={{
                          fontSize: 12,
                          color: "var(--color-text-secondary)",
                        }}
                      >
                        {t("modelConfig.reuseLlmConfigForSearch")}
                      </span>
                    </Checkbox>
                    <span
                      style={{
                        fontSize: 11,
                        color: nativeSearchReady
                          ? "var(--color-success)"
                          : "var(--color-text-tertiary)",
                      }}
                    >
                      {searchModel.model_name
                        ? t("modelConfig.currentModel", {
                            model: searchModel.model_name,
                          }) +
                          (nativeSearchReady
                            ? ""
                            : t("modelConfig.notSupportNativeSearch"))
                        : t("modelConfig.notConfiguredSearch")}
                    </span>
                  </div>
                  {!config.grounding.search_reuse_llm && (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "0 16px",
                      }}
                    >
                      <div>
                        <label className="field-label">
                          {t("modelConfig.qwenSearchModel")}
                        </label>
                        <Input
                          placeholder="qwen3.7-plus"
                          value={config.grounding.search_model_name}
                          onChange={(event) =>
                            updateGrounding(
                              "search_model_name",
                              event.target.value,
                            )
                          }
                        />
                      </div>
                      <div>
                        <label className="field-label">
                          {t("modelConfig.qwenSearchApiKey")}
                        </label>
                        {secretInput(
                          config.grounding.search_api_key,
                          snapshotRef.current?.grounding.search_api_key ===
                            "__CREATOR_SECRET__",
                          "sk-search-...",
                          (value) => updateGrounding("search_api_key", value),
                        )}
                      </div>
                      <div>
                        <label className="field-label">
                          {t("modelConfig.qwenSearchBaseUrl")}
                        </label>
                        <Input
                          placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                          value={config.grounding.search_base_url}
                          onChange={(event) =>
                            updateGrounding(
                              "search_base_url",
                              event.target.value,
                            )
                          }
                        />
                      </div>
                      <div>
                        <label className="field-label">
                          {t("modelConfig.searchAdapter")}
                        </label>
                        <Select
                          value={config.grounding.search_protocol}
                          onChange={(value) =>
                            updateGrounding("search_protocol", value)
                          }
                          options={[
                            {
                              value: "DashScope（百炼）",
                              label: t("modelConfig.searchAdapterDashScope"),
                            },
                          ]}
                        />
                      </div>
                    </div>
                  )}
                </div>
              ) : null}
            </div>

            <div
              style={{
                borderTop: "1px solid var(--color-border)",
                paddingTop: 16,
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              {t("modelConfig.verify")}
            </div>
            <div>
              <label className="field-label">
                {t("modelConfig.verifyModelSource")}
              </label>
              <Select
                value={config.grounding.validation_source}
                onChange={(value) => {
                  updateGrounding("validation_source", value);
                  updateGrounding("reuse_llm", value === "llm");
                }}
                options={[
                  {
                    value: "llm",
                    label: t("modelConfig.reuseLlmConfigOption"),
                  },
                  {
                    value: "vlm",
                    label: t("modelConfig.reuseVlmConfigOption"),
                  },
                  {
                    value: "custom",
                    label: t("modelConfig.customVerifyModel"),
                  },
                ]}
              />
              {config.grounding.validation_source !== "custom" && (
                <div
                  style={{
                    marginTop: 6,
                    fontSize: 11,
                    color: verifierReady
                      ? "var(--color-success)"
                      : "var(--color-text-tertiary)",
                  }}
                >
                  {verifier.model_name
                    ? t("modelConfig.currentModel", {
                        model: verifier.model_name,
                      })
                    : t("modelConfig.notConfiguredSearch")}
                </div>
              )}
            </div>

            {config.grounding.validation_source === "custom" && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "0 16px",
                }}
              >
                <div>
                  <label className="field-label">
                    {t("modelConfig.verifyModel")}
                  </label>
                  <Input
                    placeholder="model"
                    value={config.grounding.model_name}
                    onChange={(event) =>
                      updateGrounding("model_name", event.target.value)
                    }
                  />
                </div>
                <div>
                  <label className="field-label">
                    {t("modelConfig.verifyModelApiKey")}
                  </label>
                  {secretInput(
                    config.grounding.api_key,
                    snapshotRef.current?.grounding.api_key ===
                      "__CREATOR_SECRET__",
                    "sk-...",
                    (value) => updateGrounding("api_key", value),
                  )}
                </div>
                <div>
                  <label className="field-label">
                    {t("modelConfig.verifyModelBaseUrl")}
                  </label>
                  <Input
                    placeholder="https://api.example.com"
                    value={config.grounding.base_url}
                    onChange={(event) =>
                      updateGrounding("base_url", event.target.value)
                    }
                  />
                </div>
                <div>
                  <label className="field-label">
                    {t("modelConfig.apiProtocol")}
                  </label>
                  <Select
                    value={config.grounding.protocol}
                    onChange={(value) => updateGrounding("protocol", value)}
                    options={VLM_PROTOCOLS.map((protocol) => ({
                      value: protocol,
                      label: protocolLabel(protocol),
                    }))}
                  />
                </div>
              </div>
            )}

            <div>
              <Button
                className="test-btn"
                icon={<LinkOutlined />}
                loading={testing.grounding}
                onClick={handleGroundingTest}
              >
                {t("modelConfig.testVerifyModelImageInput")}
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderCard = (meta: (typeof CARD_META)[number]) => {
    if (meta.type === "grounding") return renderGroundingCard(meta);
    const { type, labelKey, icon, required } = meta;
    const isExpanded = expanded[type];
    const item = config[type] as ModelConfigItem;
    const usingLlm =
      type === "vlm" && config.vlm.use_llm && config.llm.model_name;
    const configured = !item.enabled
      ? false
      : usingLlm
      ? true
      : !!item.model_name;
    const isTested = tested[type] === true;

    const videoModes = videoCapabilities?.supportedModes ?? [];
    const videoFamilyBlock =
      type === "video" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="field-label" style={{ marginBottom: 0 }}>
            {t("modelConfig.videoFamilyCaps")}
          </span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {videoModes.map((mode) => (
              <span
                key={mode}
                style={{
                  fontSize: 10.5,
                  padding: "2px 9px",
                  borderRadius: 9,
                  fontWeight: 500,
                  background: "var(--color-success-soft)",
                  color: "var(--color-success)",
                }}
              >
                {t(VIDEO_MODE_LABEL_KEYS[mode] ?? mode)}
              </span>
            ))}
            {videoCapabilitiesLoading && (
              <span
                style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}
              >
                {t("modelConfig.videoCapabilitiesLoading")}
              </span>
            )}
            {!videoCapabilitiesLoading &&
              videoCapabilities &&
              !videoCapabilities.known && (
                <span style={{ fontSize: 11, color: "var(--color-error)" }}>
                  {t("modelConfig.videoCapabilityUnknown")}
                </span>
              )}
            {!videoCapabilitiesLoading && videoCapabilitiesError && (
              <span style={{ fontSize: 11, color: "var(--color-error)" }}>
                {t("modelConfig.videoCapabilityUnavailable")}
              </span>
            )}
          </div>
          <span
            style={{
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              lineHeight: 1.6,
            }}
          >
            {!videoCapabilitiesLoading &&
              videoCapabilities &&
              t(
                isWan3VideoModel(config.video.model_name)
                  ? "modelConfig.videoAllInOneNote"
                  : videoCapabilities.derivesModeModel
                  ? "modelConfig.videoFamilyNote"
                  : "modelConfig.videoExactModelNote",
              )}
          </span>
          <span
            style={{
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              lineHeight: 1.6,
            }}
          >
            {t("modelConfig.videoEndpointNote")}
          </span>
        </div>
      ) : null;

    // Bailian image models all share the multimodal-generation service path
    // appended by the backend, so one API root serves the whole catalogue.
    const imageEndpointBlock =
      type === "image" &&
      (item.protocol.toLowerCase().includes("dashscope") ||
        item.protocol.includes("百炼")) ? (
        <span
          style={{
            fontSize: 11,
            color: "var(--color-text-tertiary)",
            lineHeight: 1.6,
          }}
        >
          {t("modelConfig.imageEndpointNote")}
        </span>
      ) : null;

    const ttsFamilyBlock =
      type === "tts" && ttsCapability ? (
        <span
          style={{
            fontSize: 11,
            color: "var(--color-text-tertiary)",
            lineHeight: 1.6,
          }}
        >
          {ttsCapability.family === "qwen-tts"
            ? t("modelConfig.ttsFamilyNoteQwen")
            : t("modelConfig.ttsFamilyNoteCosy")}
        </span>
      ) : null;

    const statusColor = !configured
      ? "var(--color-border)"
      : isTested
      ? "var(--color-success)"
      : "var(--color-danger)";
    const statusDot = (
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: statusColor,
          flexShrink: 0,
        }}
      />
    );

    return (
      <div
        key={type}
        className="glass-card"
        style={{ borderRadius: 8, boxShadow: "var(--shadow-xs)" }}
      >
        <div
          onClick={() => toggleExpand(type)}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 18px",
            cursor: "pointer",
            userSelect: "none",
            borderBottom: isExpanded ? "1px solid var(--color-border)" : "none",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 12,
              minWidth: 0,
            }}
          >
            <span
              style={{
                width: 30,
                height: 30,
                borderRadius: 8,
                background: "var(--color-bg-layout)",
                border: "1px solid var(--color-border)",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              {icon}
            </span>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 2,
                minWidth: 0,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: "var(--color-text-primary)",
                  }}
                >
                  {t(labelKey)}
                </span>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    fontSize: 10,
                    fontWeight: 500,
                    color: required
                      ? "var(--color-accent)"
                      : "var(--color-text-tertiary)",
                    background: required
                      ? "var(--color-accent-soft)"
                      : "var(--color-bg-secondary)",
                    padding: "1px 7px",
                    borderRadius: 4,
                  }}
                >
                  {required
                    ? t("modelConfig.required")
                    : t("modelConfig.optional")}
                </span>
                {configured && (
                  <span
                    className="text-ellipsis"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      fontSize: 10,
                      fontWeight: 500,
                      color: isTested
                        ? "var(--color-success)"
                        : "var(--color-danger)",
                      background: "var(--color-success-soft)",
                      padding: "1px 7px",
                      borderRadius: 4,
                      maxWidth: 100,
                    }}
                  >
                    {!item.enabled
                      ? t("modelConfig.disabledLabel")
                      : usingLlm
                      ? config.llm.model_name
                      : item.model_name}
                    {!isTested &&
                      item.enabled &&
                      t("modelConfig.notTestedLabel")}
                  </span>
                )}
              </div>
              <span
                style={{
                  fontSize: 11,
                  color: "var(--color-text-tertiary)",
                  lineHeight: 1.4,
                }}
              >
                {t(CARD_TEXT_KEYS[type].brief)}
              </span>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {statusDot}
            {toggleControl(type)}
            <DownOutlined
              style={{
                fontSize: 10,
                color: "var(--color-text-tertiary)",
                transition: "transform 0.2s",
                transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
              }}
            />
          </div>
        </div>
        {isExpanded && (
          <div
            style={{
              padding: "16px 18px 32px",
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            <div
              style={{
                borderLeft: "3px solid var(--color-accent)",
                background: "var(--color-bg-layout)",
                borderRadius: "0 8px 8px 0",
                padding: "7px 12px",
                fontSize: 11.5,
                lineHeight: 1.6,
                color: "var(--color-text-secondary)",
                display: "flex",
                flexDirection: "column",
                gap: 3,
              }}
            >
              <span>
                <b
                  style={{
                    color: "var(--color-text-primary)",
                    marginRight: 4,
                  }}
                >
                  {t("modelConfig.usageLabel")}
                </b>
                {t(CARD_TEXT_KEYS[type].usage)}
              </span>
              <span>
                <b style={{ color: "var(--color-accent)", marginRight: 4 }}>
                  {t("modelConfig.needLabel")}
                </b>
                {t(CARD_TEXT_KEYS[type].need)}
              </span>
            </div>
            {type === "vlm" && (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Checkbox
                  checked={config.vlm.use_llm}
                  disabled={testingLlmMultimodal}
                  onChange={(e) => handleVlmUseLlm(e.target.checked)}
                >
                  <span
                    style={{
                      fontSize: 12,
                      color: testingLlmMultimodal
                        ? "var(--color-text-tertiary)"
                        : "var(--color-text-secondary)",
                      cursor: "pointer",
                    }}
                  >
                    {testingLlmMultimodal
                      ? t("modelConfig.multimodalTesting")
                      : t("modelConfig.reuseLlmConfig")}
                  </span>
                </Checkbox>
                {testingLlmMultimodal && (
                  <span
                    style={{
                      fontSize: 11,
                      color: "var(--color-text-tertiary)",
                    }}
                  >
                    {t("modelConfig.sendImageToVerify")}
                  </span>
                )}
              </div>
            )}
            {type !== "vlm" && renderFields(type)}
            {type === "vlm" && !config.vlm.use_llm && renderFields("vlm")}
            {imageEndpointBlock}
            {videoFamilyBlock}
            {ttsFamilyBlock}
          </div>
        )}
      </div>
    );
  };

  // Readiness mirrors the old segmented-tab status colouring: a model is
  // ready when it is enabled, resolves to a model name and passed its test.
  const modelReady = (type: TabType): boolean => {
    if (type === "grounding") {
      const verifier = groundingValidationModel(config);
      return (
        config.grounding.enabled &&
        !!groundingSearchLabel(config) &&
        !!verifier.model_name
      );
    }
    const item = config[type] as ModelConfigItem;
    if (type === "vlm" && config.vlm.use_llm)
      return item.enabled && tested.vlm === true;
    return item.enabled && !!item.model_name && tested[type] === true;
  };

  const paneReadyCount = (pane: "lang" | "perception" | "media") => {
    const types = PANE_MODELS[pane];
    return { ready: types.filter(modelReady).length, total: types.length };
  };

  const activeModeIndex = permissionModeIndex(config);
  const anyReviewTier =
    config.selfReview.sync_enabled ||
    config.selfReview.media_enabled ||
    config.selfReview.render_enabled;

  const navGroupLabel = (text: string) => (
    <div
      key={text}
      style={{
        fontSize: 10,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: 0.5,
        color: "var(--color-text-tertiary)",
        padding: "10px 12px 5px",
      }}
    >
      {text}
    </div>
  );

  const navButton = (
    pane: SettingsPane,
    icon: React.ReactNode,
    label: string,
    meta?: React.ReactNode,
  ) => (
    <button
      key={pane}
      type="button"
      data-settings-nav={pane}
      aria-current={activePane === pane}
      onClick={() => setActivePane(pane)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        padding: "7px 12px",
        borderRadius: 9999,
        border: `1px solid ${activePane === pane ? "#FFD7AC" : "transparent"}`,
        textAlign: "left",
        cursor: "pointer",
        fontSize: 12.5,
        fontWeight: activePane === pane ? 600 : 500,
        color: activePane === pane ? "#332F2E" : "var(--color-text-secondary)",
        background: activePane === pane ? "#FFF3E6" : "transparent",
        transition: "all 0.15s",
      }}
    >
      {icon}
      <span style={{ flex: 1, minWidth: 0, lineHeight: 1.3 }}>{label}</span>
      {meta}
    </button>
  );

  const paneCountChip = (pane: "lang" | "perception" | "media") => {
    const { ready, total } = paneReadyCount(pane);
    return (
      <span
        style={{
          fontSize: 10,
          fontWeight: 500,
          color:
            ready === total
              ? "var(--color-success)"
              : "var(--color-text-tertiary)",
        }}
      >
        {ready}/{total}
      </span>
    );
  };

  return (
    <Modal
      open={open}
      onCancel={handleCancel}
      footer={null}
      width={1000}
      centered
      closable={false}
      styles={{ body: { padding: 0 } }}
      rootClassName="model-config-modal"
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "18px 22px 14px",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <SettingOutlined
            style={{ color: "var(--color-text-primary)", fontSize: 16 }}
          />
          <span
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
          >
            {t("modelConfig.title")}
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--color-text-tertiary)",
            padding: 4,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 4,
            transition: "all 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color =
              "var(--color-text-primary)";
            (e.currentTarget as HTMLButtonElement).style.background =
              "var(--color-bg-secondary)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color =
              "var(--color-text-tertiary)";
            (e.currentTarget as HTMLButtonElement).style.background = "none";
          }}
          aria-label={t("modelConfig.close")}
        >
          <CloseOutlined style={{ fontSize: 14 }} />
        </button>
      </div>

      {/* Body: settings-center layout — grouped nav on the left, panes right. */}
      <div
        style={{
          display: "flex",
          height: "calc(80vh - 130px)",
          minHeight: 440,
        }}
      >
        <nav
          aria-label={t("modelConfig.settingsNav")}
          style={{
            width: 232,
            flexShrink: 0,
            borderRight: "1px solid var(--color-border)",
            background: "var(--color-bg-primary)",
            padding: "12px 10px",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {navGroupLabel(t("modelConfig.groupModels"))}
          {navButton(
            "lang",
            <Brain size={14} />,
            t("modelConfig.paneLang"),
            paneCountChip("lang"),
          )}
          {navButton(
            "perception",
            <AudioOutlined style={{ fontSize: 14 }} />,
            t("modelConfig.panePerception"),
            paneCountChip("perception"),
          )}
          {navButton(
            "media",
            <VideoCameraOutlined style={{ fontSize: 14 }} />,
            t("modelConfig.paneMedia"),
            paneCountChip("media"),
          )}
          {navGroupLabel(t("modelConfig.groupAutomation"))}
          {navButton(
            "mode",
            <ThunderboltOutlined style={{ fontSize: 14 }} />,
            t("modelConfig.paneMode"),
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: "var(--color-accent)",
                background: "var(--color-bg-primary)",
                border: "1px solid var(--color-border)",
                borderRadius: 8,
                padding: "1px 7px",
                whiteSpace: "nowrap",
              }}
            >
              {t(PERMISSION_MODES[activeModeIndex].labelKey)}
            </span>,
          )}
          {navButton(
            "review",
            <SafetyOutlined style={{ fontSize: 14 }} />,
            t("modelConfig.paneReview"),
            <span
              style={{
                fontSize: 10,
                fontWeight: 500,
                color: anyReviewTier
                  ? "var(--color-success)"
                  : "var(--color-text-tertiary)",
                whiteSpace: "nowrap",
              }}
            >
              {anyReviewTier
                ? [
                    config.selfReview.sync_enabled && "①",
                    config.selfReview.media_enabled && "②",
                    config.selfReview.render_enabled && "③",
                  ]
                    .filter(Boolean)
                    .join("")
                : t("modelConfig.reviewOff")}
            </span>,
          )}
          {navGroupLabel(t("modelConfig.groupHelp"))}
          {navButton(
            "guide",
            <ReadOutlined style={{ fontSize: 14 }} />,
            t("modelConfig.paneGuide"),
          )}
        </nav>

        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "20px 24px 28px",
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          {(activePane === "lang" ||
            activePane === "perception" ||
            activePane === "media") &&
            (() => {
              const paneMeta = MODEL_PANE_META[activePane];
              return (
                <>
                  <div>
                    <div
                      style={{
                        fontSize: 15,
                        fontWeight: 700,
                        color: "var(--color-text-primary)",
                      }}
                    >
                      {t(paneMeta.titleKey)}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--color-text-tertiary)",
                        marginTop: 3,
                        lineHeight: 1.6,
                      }}
                    >
                      {t(paneMeta.descKey)}
                    </div>
                  </div>
                  <div
                    style={{
                      display: "inline-flex",
                      flexWrap: "wrap",
                      alignItems: "baseline",
                      gap: 6,
                      borderRadius: 8,
                      background: "var(--color-bg-layout)",
                      padding: "5px 10px",
                      fontSize: 11,
                      color: "var(--color-text-tertiary)",
                      alignSelf: "flex-start",
                    }}
                  >
                    <b style={{ color: "var(--color-text-primary)" }}>
                      {t(paneMeta.hint.sceneKey)}
                    </b>
                    <span
                      style={{
                        fontWeight: 500,
                        color: "var(--color-accent)",
                      }}
                    >
                      {t(paneMeta.hint.modelsKey)}
                    </span>
                    <span>{t(paneMeta.hint.whyKey)}</span>
                  </div>
                  {PANE_MODELS[activePane].map((type) => {
                    const meta = CARD_META.find((item) => item.type === type);
                    return meta ? renderCard(meta) : null;
                  })}
                  {activePane === "media" && (
                    <div
                      className="glass-card"
                      style={{ borderRadius: 8, boxShadow: "var(--shadow-xs)" }}
                    >
                      <div
                        onClick={() => toggleExpand("translate")}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "14px 18px",
                          cursor: "pointer",
                          userSelect: "none",
                          borderBottom: expanded.translate
                            ? "1px solid var(--color-border)"
                            : "none",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "flex-start",
                            gap: 12,
                            minWidth: 0,
                          }}
                        >
                          <span
                            style={{
                              width: 30,
                              height: 30,
                              borderRadius: 8,
                              background: "var(--color-bg-layout)",
                              border: "1px solid var(--color-border)",
                              display: "inline-flex",
                              alignItems: "center",
                              justifyContent: "center",
                              flexShrink: 0,
                            }}
                          >
                            <TranslationOutlined
                              style={{
                                color: "var(--color-text-tertiary)",
                                fontSize: 16,
                              }}
                            />
                          </span>
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              gap: 2,
                              minWidth: 0,
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 10,
                              }}
                            >
                              <span
                                style={{
                                  fontSize: 14,
                                  fontWeight: 600,
                                  color: "var(--color-text-primary)",
                                }}
                              >
                                {t("modelConfig.translateCardTitle")}
                              </span>
                              <span
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  fontSize: 10,
                                  fontWeight: 500,
                                  color: "var(--color-text-tertiary)",
                                  background: "var(--color-bg-secondary)",
                                  padding: "1px 7px",
                                  borderRadius: 4,
                                }}
                              >
                                {t("modelConfig.optional")}
                              </span>
                              <span
                                className="text-ellipsis"
                                style={{
                                  fontSize: 10,
                                  fontWeight: 500,
                                  color: "var(--color-text-tertiary)",
                                  maxWidth: 140,
                                }}
                              >
                                {config.image.translate_model ||
                                  "qwen-mt-image"}
                              </span>
                            </div>
                            <span
                              style={{
                                fontSize: 11,
                                color: "var(--color-text-tertiary)",
                                lineHeight: 1.4,
                              }}
                            >
                              {t("modelConfig.translateCardBrief")}
                            </span>
                          </div>
                        </div>
                        <DownOutlined
                          style={{
                            fontSize: 10,
                            color: "var(--color-text-tertiary)",
                            transition: "transform 0.2s",
                            transform: expanded.translate
                              ? "rotate(180deg)"
                              : "rotate(0deg)",
                          }}
                        />
                      </div>
                      {expanded.translate && (
                        <div
                          style={{
                            padding: "16px 18px 24px",
                            display: "flex",
                            flexDirection: "column",
                            gap: 12,
                          }}
                        >
                          <div style={{ maxWidth: 380 }}>
                            <label className="field-label">
                              {t("modelConfig.translateModelLabel")}
                            </label>
                            <Input
                              placeholder="qwen-mt-image"
                              value={config.image.translate_model}
                              onChange={(event) =>
                                updateItem(
                                  "image",
                                  "translate_model",
                                  event.target.value,
                                )
                              }
                            />
                          </div>
                          <p
                            style={{
                              margin: 0,
                              fontSize: 11,
                              lineHeight: 1.6,
                              color: "var(--color-text-tertiary)",
                            }}
                          >
                            {t("modelConfig.translateCardNote")}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </>
              );
            })()}

          {activePane === "mode" && (
            <>
              <div>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    color: "var(--color-text-primary)",
                  }}
                >
                  {t("modelConfig.paneMode")}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--color-text-tertiary)",
                    marginTop: 3,
                    lineHeight: 1.6,
                  }}
                >
                  {t("modelConfig.paneModeDesc")}
                </div>
              </div>
              <div
                role="radiogroup"
                aria-label={t("modelConfig.permissionModeTitle")}
                style={{ display: "flex", flexDirection: "column", gap: 10 }}
              >
                {PERMISSION_MODES.map((mode, index) => {
                  const selected = index === activeModeIndex;
                  const gates = [
                    mode.checkpoints === "required",
                    mode.execution === "required",
                    mode.mediaReview === "required",
                  ];
                  const gateLabels = [
                    t("modelConfig.gateCheckpoints"),
                    t("modelConfig.gateExecution"),
                    t("modelConfig.gateMediaReview"),
                  ];
                  return (
                    <div
                      key={mode.labelKey}
                      role="radio"
                      aria-checked={selected}
                      tabIndex={0}
                      onClick={() => handleSelectMode(index)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          handleSelectMode(index);
                        }
                      }}
                      style={{
                        display: "flex",
                        gap: 12,
                        alignItems: "flex-start",
                        border: `1.5px solid ${
                          selected
                            ? "var(--color-accent)"
                            : "var(--color-border)"
                        }`,
                        borderRadius: 8,
                        background: "var(--color-bg-primary)",
                        boxShadow: selected
                          ? "0 2px 10px rgba(255, 127, 22, 0.12)"
                          : "var(--shadow-xs)",
                        padding: "13px 16px",
                        cursor: "pointer",
                        transition: "all 0.15s",
                      }}
                    >
                      <span
                        style={{
                          width: 16,
                          height: 16,
                          borderRadius: "50%",
                          flexShrink: 0,
                          marginTop: 2,
                          border: `1.5px solid ${
                            selected
                              ? "var(--color-accent)"
                              : "var(--color-border-strong)"
                          }`,
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                      >
                        {selected && (
                          <span
                            style={{
                              width: 8,
                              height: 8,
                              borderRadius: "50%",
                              background: "var(--color-accent)",
                            }}
                          />
                        )}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div
                          style={{
                            fontSize: 13,
                            fontWeight: 600,
                            color: "var(--color-text-primary)",
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          {t(mode.labelKey)}
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 400,
                              color: "var(--color-text-tertiary)",
                            }}
                          >
                            {t("modelConfig.modeLevel", { level: index })}
                          </span>
                        </div>
                        <div
                          style={{
                            fontSize: 12,
                            color: "var(--color-text-secondary)",
                            marginTop: 3,
                            lineHeight: 1.55,
                          }}
                        >
                          {t(mode.descriptionKey)}
                        </div>
                        <div
                          style={{
                            display: "flex",
                            gap: 6,
                            marginTop: 9,
                            flexWrap: "wrap",
                          }}
                        >
                          {gateLabels.map((gate, gateIndex) => {
                            const on = gates[gateIndex];
                            return (
                              <span
                                key={gate}
                                style={{
                                  fontSize: 10.5,
                                  padding: "2px 9px",
                                  borderRadius: 9,
                                  fontWeight: 500,
                                  background: on
                                    ? "var(--color-success-soft)"
                                    : "var(--color-danger-soft)",
                                  color: on
                                    ? "var(--color-success)"
                                    : "var(--color-danger)",
                                }}
                              >
                                {on ? "✓ " : "✕ "}
                                {gate}
                                {!on && gateIndex === 2 && index === 3
                                  ? t("modelConfig.gateAutoPassSuffix")
                                  : ""}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              {activeModeIndex === 3 && (
                <div
                  style={{
                    borderRadius: 12,
                    padding: "10px 14px",
                    fontSize: 12,
                    lineHeight: 1.6,
                    background: "var(--color-warning-soft)",
                    border: "1px solid rgba(247, 144, 9, 0.3)",
                    color: "var(--color-warning)",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    flexWrap: "wrap",
                  }}
                >
                  {t("modelConfig.yoloReviewHint")}
                  <Button
                    type="link"
                    size="small"
                    style={{ padding: 0, fontSize: 12, height: "auto" }}
                    onClick={() => setActivePane("review")}
                  >
                    {t("modelConfig.goToSelfReview")}
                  </Button>
                </div>
              )}
              <div>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: "var(--color-text-primary)",
                  }}
                >
                  {t("modelConfig.executionModeTitle")}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--color-text-tertiary)",
                    marginTop: 3,
                    lineHeight: 1.6,
                  }}
                >
                  {activeModeIndex > 0
                    ? t("modelConfig.executionModeForcedDesc")
                    : t("modelConfig.executionModeDesc")}
                </div>
                <div
                  role="radiogroup"
                  aria-label={t("modelConfig.executionModeTitle")}
                  style={{
                    display: "flex",
                    gap: 8,
                    marginTop: 10,
                    flexWrap: "wrap",
                  }}
                >
                  {(["co_creation", "delegated", "fine_tuning"] as const).map(
                    (mode) => {
                      const forcedDelegated = activeModeIndex > 0;
                      const current = forcedDelegated
                        ? "delegated"
                        : config.creationCheckpoints.executionMode ??
                          "co_creation";
                      const selected = current === mode;
                      const disabled = forcedDelegated;
                      return (
                        <button
                          key={mode}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          disabled={disabled}
                          data-execution-mode={mode}
                          onClick={() => {
                            if (disabled) return;
                            setConfig((previous) => ({
                              ...previous,
                              creationCheckpoints: {
                                ...previous.creationCheckpoints,
                                executionMode: mode,
                              },
                            }));
                            void patchCreationCheckpoints(
                              config.creationCheckpoints.mode,
                              mode,
                            ).catch(() => {
                              message.error(
                                t("modelConfig.executionModeSaveFailed"),
                              );
                            });
                          }}
                          style={{
                            padding: "9px 14px",
                            borderRadius: 8,
                            fontSize: 12,
                            lineHeight: 1.4,
                            textAlign: "left",
                            cursor: disabled ? "not-allowed" : "pointer",
                            opacity: disabled && mode !== "delegated" ? 0.5 : 1,
                            border: `1.5px solid ${
                              selected
                                ? "var(--color-accent)"
                                : "var(--color-border)"
                            }`,
                            background: "var(--color-bg-primary)",
                            color: "var(--color-text-primary)",
                          }}
                        >
                          <div style={{ fontWeight: 600 }}>
                            {t(`modelConfig.executionMode_${mode}`)}
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--color-text-tertiary)",
                              marginTop: 2,
                            }}
                          >
                            {t(`modelConfig.executionMode_${mode}_desc`)}
                          </div>
                        </button>
                      );
                    },
                  )}
                </div>
              </div>
            </>
          )}

          {activePane === "review" &&
            (() => {
              const llmOk = modelReady("llm");
              const vlmOk = modelReady("vlm");
              const yolo = activeModeIndex === 3;
              const tiers = [
                {
                  key: "sync_enabled" as const,
                  ordinal: "①",
                  titleKey: "modelConfig.reviewSyncTitle",
                  descKey: "modelConfig.reviewSyncDesc",
                  roundsText: t("modelConfig.reviewSyncRounds", {
                    rounds: REVIEW_TIER_ROUNDS.sync,
                  }),
                  ready: llmOk,
                  depType: "llm" as TabType,
                  depLabel: "LLM",
                  opTiers: [1],
                },
                {
                  key: "media_enabled" as const,
                  ordinal: "②",
                  titleKey: "modelConfig.reviewMediaTitle",
                  descKey: "modelConfig.reviewMediaDesc",
                  roundsText: t("modelConfig.reviewMediaRounds", {
                    rounds: REVIEW_TIER_ROUNDS.media,
                  }),
                  ready: vlmOk,
                  depType: "vlm" as TabType,
                  depLabel: "VLM",
                  // Tier-0 objective operators feed the media review's
                  // evidence chain, so they are managed under this card.
                  opTiers: [0, 2],
                },
                {
                  key: "render_enabled" as const,
                  ordinal: "③",
                  titleKey: "modelConfig.reviewRenderTitle",
                  descKey: "modelConfig.reviewRenderDesc",
                  roundsText: t("modelConfig.reviewRenderRounds", {
                    rounds: REVIEW_TIER_ROUNDS.render,
                  }),
                  ready: vlmOk,
                  depType: "vlm" as TabType,
                  depLabel: "VLM",
                  opTiers: [3],
                },
              ];
              return (
                <>
                  <div>
                    <div
                      style={{
                        fontSize: 15,
                        fontWeight: 700,
                        color: "var(--color-text-primary)",
                      }}
                    >
                      {t("modelConfig.paneReview")}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--color-text-tertiary)",
                        marginTop: 3,
                        lineHeight: 1.6,
                      }}
                    >
                      {t("modelConfig.paneReviewDesc")}
                    </div>
                  </div>
                  <div
                    style={{
                      borderRadius: 12,
                      padding: "10px 14px",
                      fontSize: 12,
                      lineHeight: 1.6,
                      display: "flex",
                      gap: 9,
                      alignItems: "flex-start",
                      background:
                        yolo && !anyReviewTier
                          ? "var(--color-warning-soft)"
                          : "var(--color-bg-layout)",
                      border: `1px solid ${
                        yolo && !anyReviewTier
                          ? "rgba(247, 144, 9, 0.3)"
                          : "var(--color-border)"
                      }`,
                      color:
                        yolo && !anyReviewTier
                          ? "var(--color-warning)"
                          : "var(--color-text-secondary)",
                    }}
                  >
                    <span style={{ flex: 1, minWidth: 0 }}>
                      {yolo
                        ? anyReviewTier
                          ? t("modelConfig.reviewBannerYoloCovered")
                          : t("modelConfig.reviewBannerYoloBare")
                        : t("modelConfig.reviewBannerNormal", {
                            mode: t(PERMISSION_MODES[activeModeIndex].labelKey),
                          })}
                    </span>
                    <Button
                      type="link"
                      size="small"
                      style={{
                        padding: 0,
                        fontSize: 12,
                        height: "auto",
                        flexShrink: 0,
                      }}
                      onClick={() => setActivePane("mode")}
                    >
                      {t("modelConfig.adjustModeLink")}
                    </Button>
                  </div>
                  {tiers.map((tier) => (
                    <div
                      key={tier.key}
                      className="glass-card"
                      style={{
                        padding: "14px 16px",
                        borderRadius: 8,
                        boxShadow: "var(--shadow-xs)",
                      }}
                      data-review-tier={tier.key}
                    >
                      <div
                        style={{
                          display: "flex",
                          gap: 12,
                          alignItems: "flex-start",
                        }}
                      >
                        <span
                          style={{
                            width: 20,
                            height: 20,
                            borderRadius: "50%",
                            flexShrink: 0,
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            background: "var(--color-accent-soft)",
                            color: "var(--color-accent)",
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          {tier.ordinal}
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div
                            style={{
                              fontSize: 13,
                              fontWeight: 600,
                              color: "var(--color-text-primary)",
                              display: "flex",
                              alignItems: "center",
                              gap: 8,
                              flexWrap: "wrap",
                            }}
                          >
                            {t(tier.titleKey)}
                            <button
                              type="button"
                              onClick={() => jumpToModel(tier.depType)}
                              style={{
                                fontSize: 10.5,
                                padding: "1px 8px",
                                borderRadius: 8,
                                fontWeight: 500,
                                border: "none",
                                cursor: "pointer",
                                background: tier.ready
                                  ? "var(--color-success-soft)"
                                  : "var(--color-danger-soft)",
                                color: tier.ready
                                  ? "var(--color-success)"
                                  : "var(--color-danger)",
                              }}
                            >
                              {tier.ready
                                ? t("modelConfig.reviewDependsOk", {
                                    model: tier.depLabel,
                                  })
                                : t("modelConfig.reviewDependsMissing", {
                                    model: tier.depLabel,
                                  })}
                            </button>
                            {config.selfReview.envOverrides?.[tier.key] !==
                              undefined && (
                              <span
                                style={{
                                  fontSize: 10.5,
                                  padding: "1px 8px",
                                  borderRadius: 8,
                                  fontWeight: 500,
                                  background:
                                    "var(--color-warning-soft, #fef3c7)",
                                  color: "var(--color-warning, #92400e)",
                                }}
                                title={t("modelConfig.reviewEnvNote")}
                              >
                                {["1", "true", "yes", "on"].includes(
                                  (
                                    config.selfReview.envOverrides[tier.key] ??
                                    ""
                                  ).toLowerCase(),
                                )
                                  ? t("modelConfig.reviewEnvForcedOn")
                                  : t("modelConfig.reviewEnvForcedOff")}
                              </span>
                            )}
                          </div>
                          <div
                            style={{
                              fontSize: 12,
                              color: "var(--color-text-secondary)",
                              marginTop: 3,
                              lineHeight: 1.6,
                            }}
                          >
                            {t(tier.descKey)}
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--color-text-tertiary)",
                              marginTop: 6,
                              lineHeight: 1.6,
                            }}
                          >
                            {tier.roundsText}
                          </div>
                          {tier.key === "render_enabled" && (
                            <div
                              style={{
                                fontSize: 11,
                                color: "var(--color-text-tertiary)",
                                marginTop: 4,
                              }}
                            >
                              {t("modelConfig.reviewRenderDims")}
                            </div>
                          )}
                        </div>
                        <label
                          className="desktop-toggle"
                          style={{ opacity: tier.ready ? 1 : 0.4 }}
                        >
                          <input
                            type="checkbox"
                            checked={config.selfReview[tier.key]}
                            disabled={!tier.ready}
                            aria-label={t(tier.titleKey)}
                            onChange={(event) =>
                              void saveSelfReview(
                                tier.key,
                                event.target.checked,
                              )
                            }
                          />
                          <span className="track" />
                          <span className="thumb" />
                        </label>
                      </div>
                      {(() => {
                        // Advanced per-operator switches (高级配置): every
                        // check is one “lit” pill — click toggles it, the
                        // trailing i / ! badge explains it in plain words
                        // on hover. Pills only respond while their tier
                        // switch is on; otherwise the whole wall greys out.
                        const ops = (
                          config.selfReview.operatorStatus ?? []
                        ).filter((op) => tier.opTiers.includes(op.tier));
                        if (ops.length === 0) {
                          return null;
                        }
                        const tierLive = (
                          key:
                            | "sync_enabled"
                            | "media_enabled"
                            | "render_enabled",
                        ): boolean => {
                          const raw = config.selfReview.envOverrides?.[key];
                          if (raw !== undefined) {
                            return ["1", "true", "yes", "on"].includes(
                              raw.toLowerCase(),
                            );
                          }
                          return config.selfReview[key];
                        };
                        // Tier-0 evidence operators feed BOTH the media
                        // review and the final-cut review, so they stay
                        // adjustable while either of those runs — greying
                        // them out with only the media switch off would
                        // hide checks that are still executing.
                        const sharedWithRender =
                          tier.key === "media_enabled" &&
                          vlmOk &&
                          tierLive("render_enabled");
                        const tierEnabled =
                          tier.ready &&
                          (tierLive(tier.key) || sharedWithRender);
                        const manualKeys = ops
                          .filter((op) => op.source === "user")
                          .map((op) => op.key);
                        return (
                          <div style={{ marginTop: 10 }}>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 6,
                                fontSize: 11.5,
                                color: "var(--color-text-secondary)",
                                marginBottom: 6,
                              }}
                            >
                              {t("modelConfig.reviewOpsTitle", {
                                count: ops.filter((op) => op.enabled).length,
                                total: ops.length,
                              })}
                              <Tooltip
                                title={
                                  <div
                                    style={{
                                      maxWidth: 280,
                                      fontSize: 12,
                                      lineHeight: 1.6,
                                    }}
                                  >
                                    {t("modelConfig.reviewOpsDesc")}
                                  </div>
                                }
                              >
                                <span
                                  aria-label={t("modelConfig.reviewOpsDesc")}
                                  style={{
                                    width: 13,
                                    height: 13,
                                    borderRadius: "50%",
                                    display: "inline-flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    fontSize: 9,
                                    fontStyle: "italic",
                                    fontWeight: 700,
                                    border:
                                      "1px solid var(--color-text-tertiary)",
                                    color: "var(--color-text-tertiary)",
                                    cursor: "help",
                                    flexShrink: 0,
                                  }}
                                >
                                  i
                                </span>
                              </Tooltip>
                              {tierEnabled && manualKeys.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    void restoreReviewOperators(manualKeys)
                                  }
                                  style={{
                                    marginLeft: "auto",
                                    fontSize: 10.5,
                                    border: "none",
                                    background: "none",
                                    color: "var(--color-accent)",
                                    cursor: "pointer",
                                    padding: 0,
                                  }}
                                >
                                  {t("modelConfig.reviewOpsRestoreAll")}
                                </button>
                              )}
                            </div>
                            {!tierEnabled && (
                              <div
                                style={{
                                  fontSize: 11,
                                  color: "var(--color-text-tertiary)",
                                  marginBottom: 6,
                                }}
                              >
                                {t("modelConfig.reviewOpsDisabledHint")}
                              </div>
                            )}
                            {tierEnabled && sharedWithRender && (
                              <div
                                style={{
                                  fontSize: 11,
                                  color: "var(--color-text-tertiary)",
                                  marginBottom: 6,
                                }}
                              >
                                {t("modelConfig.reviewOpsSharedNote")}
                              </div>
                            )}
                            <div
                              style={{
                                display: "flex",
                                flexWrap: "wrap",
                                gap: 6,
                              }}
                            >
                              {ops.map((op) => {
                                const name = t(
                                  `modelConfig.reviewOp_${op.key}`,
                                );
                                const depMissing =
                                  op.dependency !== "none" && !op.capability_ok;
                                const lit = tierEnabled && op.enabled;
                                const stateText =
                                  op.source === "auto"
                                    ? op.enabled
                                      ? t("modelConfig.reviewOpStateAutoOn")
                                      : t("modelConfig.reviewOpStateAutoOff")
                                    : op.enabled
                                    ? t("modelConfig.reviewOpStateManualOn")
                                    : t("modelConfig.reviewOpStateManualOff");
                                const tooltip = (
                                  <div
                                    style={{
                                      maxWidth: 260,
                                      fontSize: 12,
                                      lineHeight: 1.6,
                                    }}
                                  >
                                    <div style={{ fontWeight: 600 }}>
                                      {name}
                                    </div>
                                    <div>
                                      {t(`modelConfig.reviewOpDesc_${op.key}`)}
                                    </div>
                                    {op.dependency !== "none" && (
                                      <div style={{ opacity: 0.85 }}>
                                        {t(
                                          `modelConfig.reviewOpDep_${op.dependency}`,
                                        )}
                                        {" · "}
                                        {op.capability_ok
                                          ? t("modelConfig.reviewOpDepReady")
                                          : t("modelConfig.reviewOpDepMissing")}
                                      </div>
                                    )}
                                    <div style={{ opacity: 0.85 }}>
                                      {tierEnabled
                                        ? stateText
                                        : t(
                                            "modelConfig.reviewOpsDisabledHint",
                                          )}
                                    </div>
                                  </div>
                                );
                                return (
                                  <button
                                    key={op.key}
                                    type="button"
                                    data-review-operator={op.key}
                                    aria-pressed={lit}
                                    aria-disabled={!tierEnabled}
                                    aria-label={name}
                                    onClick={() => {
                                      if (!tierEnabled) {
                                        return;
                                      }
                                      void saveReviewOperator(
                                        op.key,
                                        !op.enabled,
                                      );
                                    }}
                                    style={{
                                      display: "inline-flex",
                                      alignItems: "center",
                                      gap: 5,
                                      padding: "3px 9px",
                                      borderRadius: 999,
                                      fontSize: 11.5,
                                      lineHeight: 1.5,
                                      cursor: tierEnabled
                                        ? "pointer"
                                        : "not-allowed",
                                      opacity: tierEnabled ? 1 : 0.45,
                                      transition:
                                        "background .15s ease, color .15s ease, border-color .15s ease, opacity .15s ease",
                                      background: lit
                                        ? "var(--color-accent-soft)"
                                        : "transparent",
                                      color: lit
                                        ? "var(--color-accent)"
                                        : "var(--color-text-tertiary)",
                                      border: lit
                                        ? "1px solid var(--color-accent)"
                                        : "1px solid var(--color-border, rgba(0,0,0,0.15))",
                                    }}
                                  >
                                    {name}
                                    <Tooltip title={tooltip}>
                                      <span
                                        onClick={(event) =>
                                          event.stopPropagation()
                                        }
                                        style={{
                                          width: 13,
                                          height: 13,
                                          borderRadius: "50%",
                                          display: "inline-flex",
                                          alignItems: "center",
                                          justifyContent: "center",
                                          fontSize: 9,
                                          fontWeight: 700,
                                          fontStyle: depMissing
                                            ? "normal"
                                            : "italic",
                                          flexShrink: 0,
                                          cursor: "help",
                                          border: depMissing
                                            ? "1px solid var(--color-warning, #92400e)"
                                            : "1px solid currentColor",
                                          color: depMissing
                                            ? "var(--color-warning, #92400e)"
                                            : "inherit",
                                          background: depMissing
                                            ? "var(--color-warning-soft, #fef3c7)"
                                            : "transparent",
                                        }}
                                      >
                                        {depMissing ? "!" : "i"}
                                      </span>
                                    </Tooltip>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  ))}
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--color-text-tertiary)",
                      lineHeight: 1.6,
                    }}
                  >
                    {t("modelConfig.reviewEnvNote")}
                  </div>
                </>
              );
            })()}

          {activePane === "guide" && (
            <>
              <div>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    color: "var(--color-text-primary)",
                  }}
                >
                  {t("modelConfig.paneGuide")}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--color-text-tertiary)",
                    marginTop: 3,
                    lineHeight: 1.6,
                  }}
                >
                  {t("modelConfig.paneGuideDesc")}
                </div>
              </div>
              <div
                className="glass-card"
                style={{
                  padding: "16px 18px",
                  borderRadius: 8,
                  boxShadow: "var(--shadow-xs)",
                }}
              >
                <ModelSetupGuide
                  onNavigateToModel={(type) => jumpToModel(type as TabType)}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="action-bar">
        <div />
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Button onClick={handleCancel}>{t("modelConfig.close")}</Button>
          <Button
            icon={<ReloadOutlined />}
            loading={reloading}
            onClick={handleReload}
          >
            {t("modelConfig.reloadConfig")}
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={handleSave}
          >
            {t("modelConfig.saveConfig")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
