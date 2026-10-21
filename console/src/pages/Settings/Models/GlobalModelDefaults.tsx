import { useState } from "react";
import { Descriptions } from "antd";
import { useTranslation } from "react-i18next";
import { ModelChoice } from "../../Chat/ModelSelector/ModelChoice";
import { modelSlotLabel } from "../../Chat/ModelSelector/modelSelectorModels";
import { providerApi } from "@/api/modules/provider";
import type {
  ActiveModelsInfo,
  ModelSlotConfig,
  ModelType,
  ProviderInfo,
} from "@/api/types";
import { useAppMessage } from "@/hooks/useAppMessage";

export function GlobalModelDefaults({
  activeModels,
  providers,
  onSaved,
}: {
  activeModels: ActiveModelsInfo | null;
  providers: ProviderInfo[];
  onSaved: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);
  const save = async (type: ModelType, slot: ModelSlotConfig | null) => {
    setSaving(true);
    try {
      await providerApi.setActiveLlm({
        scope: "global",
        model_type: type,
        provider_id: slot?.provider_id ?? null,
        model: slot?.model ?? null,
      });
      await onSaved();
    } catch (error) {
      message.error(String(error));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Descriptions
      size="small"
      colon={false}
      column={{ xs: 1, sm: 1, md: 1, lg: 2, xl: 2, xxl: 2 }}
      styles={{ label: { alignItems: "center" } }}
      style={{ padding: "12px 24px" }}
      aria-label={t("models.defaultModels")}
      title={t("models.defaultModels")}
      items={(["chat", "decision"] as const).map((type) => {
        const slot = activeModels?.default_models?.[type];
        const label = t(
          type === "chat"
            ? "models.defaultChatModel"
            : "models.defaultDecisionModel",
        );
        return {
          key: type,
          label,
          children: (
            <ModelChoice
              ariaLabel={label}
              modelType={type}
              value={slot}
              label={modelSlotLabel(providers, slot) ?? t("models.notSet")}
              disabled={saving || !activeModels}
              onChange={(value) => void save(type, value)}
              resetOption={
                type === "decision" && slot
                  ? {
                      label: t("common.clear"),
                      onReset: () => void save(type, null),
                    }
                  : undefined
              }
            />
          ),
        };
      })}
    />
  );
}
