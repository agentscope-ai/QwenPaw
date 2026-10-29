import { useTranslation } from "react-i18next";
import type { ModelSlotConfig } from "@/api/types/provider";
import { ModelChoice } from "@/pages/Chat/ModelSelector/ModelChoice";
import { useEligibleProviders } from "@/pages/Chat/ModelSelector/useEligibleProviders";

/** Adapt the shared model picker to the nullable memory-model form field. */
export function MemoryModelChoice({
  value,
  onChange,
}: {
  value?: ModelSlotConfig | null;
  onChange?: (value: ModelSlotConfig | null) => void;
}) {
  const { t } = useTranslation();
  const providers = useEligibleProviders(true);
  const provider = providers?.find((item) => item.id === value?.provider_id);
  const model = provider?.models.find((item) => item.id === value?.model);
  const label = !value
    ? t("agentConfig.memoryModelUseMain")
    : !value.provider_id
    ? t("agentConfig.memoryModelInheritedProvider", { model: value.model })
    : provider && model
    ? `${provider.name} / ${model.name || model.id}`
    : t("agentConfig.memoryModelUnavailable", {
        provider: value.provider_id,
        model: value.model,
      });

  return (
    <ModelChoice
      value={value}
      ariaLabel={t("agentConfig.memoryModelLabel")}
      label={label}
      onChange={(slot) => onChange?.(slot)}
      resetOption={{
        label: t("agentConfig.memoryModelUseMain"),
        onReset: () => onChange?.(null),
      }}
    />
  );
}
