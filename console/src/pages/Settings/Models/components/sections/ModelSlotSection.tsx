import { SaveOutlined } from "@ant-design/icons";
import { Button, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

type SlotInfo = {
  provider_id?: string;
  model?: string;
};

type Option = {
  value: string;
  label: string;
};

interface ModelSlotSectionProps {
  titleKey: string;
  currentSlot?: SlotInfo;
  selectedProviderId?: string;
  selectedModel?: string;
  providerOptions: Option[];
  modelOptions: Option[];
  hasModels: boolean;
  saving: boolean;
  canSave: boolean;
  isActive: boolean;
  onProviderChange: (providerId: string) => void;
  onModelChange: (model: string) => void;
  onSave: () => void;
}

export function ModelSlotSection({
  titleKey,
  currentSlot,
  selectedProviderId,
  selectedModel,
  providerOptions,
  modelOptions,
  hasModels,
  saving,
  canSave,
  isActive,
  onProviderChange,
  onModelChange,
  onSave,
}: ModelSlotSectionProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.slotSection}>
      <div className={styles.slotHeader}>
        <h3 className={styles.slotTitle}>{t(titleKey)}</h3>
        {currentSlot?.provider_id && currentSlot?.model && (
          <span className={styles.slotCurrent}>
            {t("models.active", {
              provider: currentSlot.provider_id,
              model: currentSlot.model,
            })}
          </span>
        )}
      </div>

      <div className={styles.slotForm}>
        <div className={styles.slotField}>
          <label className={styles.slotLabel}>{t("models.provider")}</label>
          <Select
            style={{ width: "100%" }}
            placeholder={t("models.selectProvider")}
            value={selectedProviderId}
            onChange={onProviderChange}
            options={providerOptions}
          />
        </div>

        <div className={styles.slotField}>
          <label className={styles.slotLabel}>{t("models.model")}</label>
          <Select
            style={{ width: "100%" }}
            placeholder={hasModels ? t("models.selectModel") : t("models.addModelFirst")}
            disabled={!hasModels}
            showSearch
            optionFilterProp="label"
            value={selectedModel}
            onChange={onModelChange}
            options={modelOptions}
          />
        </div>

        <div
          className={styles.slotField}
          style={{ flex: "0 0 auto", minWidth: "120px" }}
        >
          <label className={styles.slotLabel} style={{ visibility: "hidden" }}>
            {t("models.actions")}
          </label>
          <Button
            type="primary"
            loading={saving}
            disabled={!canSave}
            onClick={onSave}
            block
            icon={<SaveOutlined />}
          >
            {isActive ? t("models.saved") : t("models.save")}
          </Button>
        </div>
      </div>
    </div>
  );
}

