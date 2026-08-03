import { Brain } from "lucide-react";
import {
  AudioOutlined,
  EyeOutlined,
  PictureOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";

/**
 * Model setup guide: explains which model capabilities each scenario needs and
 * the currently supported providers/protocols. Content must stay in sync with
 * ProjectComposer's required-model validation and ModelConfigModal's protocol
 * constants — update them together.
 */

interface ScenarioGuide {
  scenario: string;
  models: string;
  reason: string;
}

const SCENARIO_GUIDES: ScenarioGuide[] = [
  {
    scenario: "所有场景",
    models: "LLM（必选）",
    reason: "创作总纲规划、分镜脚本与 Agent 对话的大脑",
  },
  {
    scenario: "短剧 / 通用生成",
    models: "图片生成 + 视频生成 + VLM",
    reason: "生成分镜图与视频画面，VLM 负责画面质量回看",
  },
  {
    scenario: "剪辑 / 上传素材",
    models: "VLM",
    reason: "理解你上传的图片、视频素材的画面内容",
  },
  {
    scenario: "素材含人声 / 需转写",
    models: "ASR",
    reason: "把素材中的语音识别成文字，用于剪辑与字幕",
  },
];

interface ProviderGuide {
  type: string;
  icon: React.ReactNode;
  protocols: string;
}

const PROVIDER_GUIDES: ProviderGuide[] = [
  {
    type: "LLM / VLM",
    icon: <Brain size={12} />,
    protocols:
      "OpenAI 协议、DashScope（百炼）、Anthropic Claude、DeepSeek、Google Gemini、百度千帆、Volcano Engine（火山引擎）、自定义",
  },
  {
    type: "图片生成",
    icon: <PictureOutlined style={{ fontSize: 12 }} />,
    protocols: "OpenAI 协议、DashScope（百炼）",
  },
  {
    type: "视频生成",
    icon: <VideoCameraOutlined style={{ fontSize: 12 }} />,
    protocols:
      "DashScope（百炼：wan2.x r2v、happyhorse-1.x-r2v）、Volcano Engine（火山引擎：doubao-seedance-2.x）",
  },
  {
    type: "ASR 语音识别",
    icon: <AudioOutlined style={{ fontSize: 12 }} />,
    protocols: "DashScope Fun-ASR、OpenAI Whisper",
  },
];

export default function ModelSetupGuide() {
  return (
    <div className="space-y-3 text-xs leading-5 text-[var(--color-text-secondary)]">
      <div>
        <p className="mb-1.5 flex items-center gap-1.5 font-semibold text-[var(--color-text-primary)]">
          <EyeOutlined style={{ fontSize: 12 }} />
          什么场景需要配什么模型？
        </p>
        <ul className="space-y-1">
          {SCENARIO_GUIDES.map((item) => (
            <li
              key={item.scenario}
              className="flex flex-wrap items-baseline gap-x-1.5 rounded-md bg-[var(--color-bg-secondary)] px-2 py-1"
            >
              <span className="shrink-0 font-semibold text-[var(--color-text-primary)]">
                {item.scenario}
              </span>
              <span className="shrink-0 font-medium text-[var(--color-accent)]">
                {item.models}
              </span>
              <span className="min-w-0 text-[11px] text-[var(--color-text-tertiary)]">
                {item.reason}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="mb-1.5 font-semibold text-[var(--color-text-primary)]">
          当前支持的提供商 / 协议
        </p>
        <ul className="space-y-1">
          {PROVIDER_GUIDES.map((item) => (
            <li
              key={item.type}
              className="flex flex-wrap items-baseline gap-x-1.5 rounded-md bg-[var(--color-bg-secondary)] px-2 py-1"
            >
              <span className="flex shrink-0 items-center gap-1 font-semibold text-[var(--color-text-primary)]">
                {item.icon}
                {item.type}
              </span>
              <span className="min-w-0 text-[11px]">{item.protocols}</span>
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-[11px] text-[var(--color-text-tertiary)]">
          在「模型配置」中填写 Base URL、API Key
          与模型名称，并通过「测试连通性」后启用；VLM 可直接复用支持多模态的 LLM
          配置。
        </p>
      </div>
    </div>
  );
}
