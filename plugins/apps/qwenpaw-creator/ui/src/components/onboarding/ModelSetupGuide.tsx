import { Brain } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  AudioOutlined,
  EyeOutlined,
  GlobalOutlined,
  NodeIndexOutlined,
  PictureOutlined,
  SoundOutlined,
  UserOutlined,
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
  /** Model card the settings guide jumps to; unused in the home tour. */
  target: string;
}

function getScenarioGuides(t: (key: string) => string): ScenarioGuide[] {
  return [
    {
      scenario: t("onboarding.modelGuideAllScenes"),
      models: t("onboarding.modelGuideLlm"),
      reason: t("onboarding.modelGuideLlmDesc"),
      target: "llm",
    },
    {
      scenario: t("onboarding.modelGuideDramaGeneral"),
      models: t("onboarding.modelGuideDramaModels"),
      reason: t("onboarding.modelGuideDramaGeneralDesc"),
      target: "image",
    },
    {
      scenario: t("onboarding.modelGuideEditUpload"),
      models: t("onboarding.modelGuideEditModels"),
      reason: t("onboarding.modelGuideEditUploadDesc"),
      target: "vlm",
    },
    {
      scenario: t("onboarding.modelGuideAsr"),
      models: t("onboarding.modelGuideAsrModels"),
      reason: t("onboarding.modelGuideAsrDesc"),
      target: "asr",
    },
    {
      scenario: t("onboarding.modelGuideVoice"),
      models: t("onboarding.modelGuideVoiceModels"),
      reason: t("onboarding.modelGuideVoiceDesc"),
      target: "tts",
    },
  ];
}

interface ProviderGuide {
  type: string;
  icon: React.ReactNode;
  protocols: string;
}

function getProviderGuides(t: (key: string) => string): ProviderGuide[] {
  return [
    {
      type: "LLM / VLM",
      icon: <Brain size={12} />,
      protocols: t("onboarding.modelGuideLlmProtocols"),
    },
    {
      type: "Grounding",
      icon: <GlobalOutlined style={{ fontSize: 12 }} />,
      protocols: t("onboarding.modelGuideGroundingProtocols"),
    },
    {
      type: t("onboarding.modelGuideImageGen"),
      icon: <PictureOutlined style={{ fontSize: 12 }} />,
      protocols: t("onboarding.modelGuideImageGenProtocols"),
    },
    {
      type: t("onboarding.modelGuideVideoGen"),
      icon: <VideoCameraOutlined style={{ fontSize: 12 }} />,
      protocols: t("onboarding.modelGuideVideoGenProtocols"),
    },
    {
      type: t("onboarding.modelGuideAsrTitle"),
      icon: <AudioOutlined style={{ fontSize: 12 }} />,
      protocols: t("onboarding.modelGuideAsrProtocols"),
    },
    {
      type: t("onboarding.modelGuideTtsTitle"),
      icon: <SoundOutlined style={{ fontSize: 12 }} />,
      protocols: t("onboarding.modelGuideTtsProtocols"),
    },
    {
      type: t("onboarding.modelGuideS2vTitle"),
      icon: <UserOutlined style={{ fontSize: 12 }} />,
      protocols: t("onboarding.modelGuideS2vProtocols"),
    },
    {
      type: t("onboarding.modelGuideEmbeddingTitle"),
      icon: <NodeIndexOutlined style={{ fontSize: 12 }} />,
      protocols: t("onboarding.modelGuideEmbeddingProtocols"),
    },
  ];
}

export default function ModelSetupGuide({
  onNavigateToModel,
}: {
  /** Renders a jump link per scenario row when provided (settings guide). */
  onNavigateToModel?: (type: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3 text-xs leading-5 text-[var(--color-text-secondary)]">
      <div>
        <p className="mb-1.5 flex items-center gap-1.5 font-semibold text-[var(--color-text-primary)]">
          <EyeOutlined style={{ fontSize: 12 }} />
          {t("onboarding.modelGuideWhatModels")}
        </p>
        <ul className="space-y-1">
          {getScenarioGuides(t).map((item) => (
            <li
              key={item.scenario}
              className="flex flex-wrap items-baseline gap-x-1.5 rounded-[8px] bg-[var(--color-bg-layout)] px-2.5 py-1.5"
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
              {onNavigateToModel && (
                <button
                  type="button"
                  onClick={() => onNavigateToModel(item.target)}
                  className="ml-auto shrink-0 cursor-pointer border-none bg-transparent p-0 text-[11px] font-semibold text-[var(--color-accent)] hover:underline"
                >
                  {t("onboarding.modelGuideGoConfigure")}
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="mb-1.5 font-semibold text-[var(--color-text-primary)]">
          {t("onboarding.modelGuideProviders")}
        </p>
        <ul className="space-y-1">
          {getProviderGuides(t).map((item) => (
            <li
              key={item.type}
              className="flex flex-wrap items-baseline gap-x-1.5 rounded-[8px] bg-[var(--color-bg-layout)] px-2.5 py-1.5"
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
          {t("onboarding.modelGuideSetupDesc")}
        </p>
      </div>
    </div>
  );
}
