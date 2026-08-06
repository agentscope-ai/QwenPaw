import { Brain } from "lucide-react";
import { useTranslation } from "react-i18next";
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

function getScenarioGuides(t: (key: string) => string): ScenarioGuide[] {
  return [
    {
      scenario: t("onboarding.modelGuideAllScenes"),
      models: t("onboarding.modelGuideLlm"),
      reason: t("onboarding.modelGuideLlmDesc"),
    },
    {
      scenario: t("onboarding.modelGuideDramaGeneral"),
      models: t("onboarding.modelGuideDramaModels"),
      reason: t("onboarding.modelGuideDramaGeneralDesc"),
    },
    {
      scenario: t("onboarding.modelGuideEditUpload"),
      models: t("onboarding.modelGuideEditModels"),
      reason: t("onboarding.modelGuideEditUploadDesc"),
    },
    {
      scenario: t("onboarding.modelGuideAsr"),
      models: t("onboarding.modelGuideAsrModels"),
      reason: t("onboarding.modelGuideAsrDesc"),
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
  ];
}

export default function ModelSetupGuide() {
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
          {t("onboarding.modelGuideProviders")}
        </p>
        <ul className="space-y-1">
          {getProviderGuides(t).map((item) => (
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
          {t("onboarding.modelGuideSetupDesc")}
        </p>
      </div>
    </div>
  );
}
