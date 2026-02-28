import { useEffect, useMemo, useState } from "react";
import { SaveOutlined } from "@ant-design/icons";
import { Button, Input, InputNumber, Select, Switch, message } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../../../api";
import styles from "../../index.module.less";

type CapabilityKey = "image" | "audio" | "video";
type ModeValue = "first" | "all";

type VisionCapability = {
  enabled?: boolean;
  attachments_mode?: string;
  max_images?: number;
  max_items?: number;
  timeout_seconds?: number;
  max_output_chars?: number;
  prompt_override?: string;
};

export type VisionSectionValue = {
  image?: VisionCapability;
  audio?: VisionCapability;
  video?: VisionCapability;
};

type CapabilityForm = {
  enabled: boolean;
  mode: ModeValue;
  maxItems: number;
  timeoutSeconds: number;
  maxOutputChars: number;
  promptOverride: string;
};

const CAPABILITIES: Array<{
  key: CapabilityKey;
  maxLimit: number;
  defaults: CapabilityForm;
  titleKey: string;
  timeoutLabelKey: string;
  promptLabelKey: string;
}> = [
  {
    key: "image",
    maxLimit: 16,
    defaults: {
      enabled: true,
      mode: "first",
      maxItems: 4,
      timeoutSeconds: 60,
      maxOutputChars: 4000,
      promptOverride: "",
    },
    titleKey: "models.image",
    timeoutLabelKey: "models.imageTimeoutMaxChars",
    promptLabelKey: "models.imagePromptOverride",
  },
  {
    key: "audio",
    maxLimit: 8,
    defaults: {
      enabled: false,
      mode: "first",
      maxItems: 1,
      timeoutSeconds: 90,
      maxOutputChars: 6000,
      promptOverride: "",
    },
    titleKey: "models.audio",
    timeoutLabelKey: "models.audioTimeoutMaxChars",
    promptLabelKey: "models.audioPromptOverride",
  },
  {
    key: "video",
    maxLimit: 4,
    defaults: {
      enabled: false,
      mode: "first",
      maxItems: 1,
      timeoutSeconds: 120,
      maxOutputChars: 6000,
      promptOverride: "",
    },
    titleKey: "models.video",
    timeoutLabelKey: "models.videoTimeoutMaxChars",
    promptLabelKey: "models.videoPromptOverride",
  },
];

function toMode(value: string | undefined, fallback: ModeValue): ModeValue {
  return value === "all" || value === "first" ? value : fallback;
}

function normalizeVisionForm(vision?: VisionSectionValue): Record<CapabilityKey, CapabilityForm> {
  const map = {} as Record<CapabilityKey, CapabilityForm>;
  for (const item of CAPABILITIES) {
    const input = vision?.[item.key];
    map[item.key] = {
      enabled: input?.enabled ?? item.defaults.enabled,
      mode: toMode(input?.attachments_mode, item.defaults.mode),
      maxItems: (input?.max_images ?? input?.max_items ?? item.defaults.maxItems) as number,
      timeoutSeconds: input?.timeout_seconds ?? item.defaults.timeoutSeconds,
      maxOutputChars: input?.max_output_chars ?? item.defaults.maxOutputChars,
      promptOverride: input?.prompt_override ?? item.defaults.promptOverride,
    };
  }
  return map;
}

interface MediaPrepassSectionProps {
  vision?: VisionSectionValue;
  onSaved: () => void;
}

export function MediaPrepassSection({ vision, onSaved }: MediaPrepassSectionProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [form, setForm] = useState<Record<CapabilityKey, CapabilityForm>>(
    normalizeVisionForm(vision),
  );

  useEffect(() => {
    setForm(normalizeVisionForm(vision));
    setDirty(false);
  }, [vision]);

  const modeOptions = useMemo(
    () => [
      { value: "first", label: t("models.first") },
      { value: "all", label: t("models.all") },
    ],
    [t],
  );

  const updateCapability = (
    key: CapabilityKey,
    patch: Partial<CapabilityForm>,
  ) => {
    setForm((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));
    setDirty(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await Promise.all([
        api.setVisionImageSettings({
          enabled: form.image.enabled,
          attachments_mode: form.image.mode,
          max_images: form.image.maxItems,
          timeout_seconds: form.image.timeoutSeconds,
          max_output_chars: form.image.maxOutputChars,
          prompt_override: form.image.promptOverride,
        }),
        api.setVisionAudioSettings({
          enabled: form.audio.enabled,
          attachments_mode: form.audio.mode,
          max_items: form.audio.maxItems,
          timeout_seconds: form.audio.timeoutSeconds,
          max_output_chars: form.audio.maxOutputChars,
          prompt_override: form.audio.promptOverride,
        }),
        api.setVisionVideoSettings({
          enabled: form.video.enabled,
          attachments_mode: form.video.mode,
          max_items: form.video.maxItems,
          timeout_seconds: form.video.timeoutSeconds,
          max_output_chars: form.video.maxOutputChars,
          prompt_override: form.video.promptOverride,
        }),
      ]);
      message.success(t("models.visionSettingsUpdated"));
      setDirty(false);
      onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSave");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.slotSection}>
      <div className={styles.slotHeader}>
        <h3 className={styles.slotTitle}>{t("models.visionMediaPrepass")}</h3>
      </div>

      <div className={styles.visionGrid}>
        {CAPABILITIES.map((item) => (
          <div className={styles.visionCard} key={item.key}>
            <div className={styles.visionCardHeader}>
              <span>{t(item.titleKey)}</span>
              <Switch
                checked={form[item.key].enabled}
                onChange={(value) => updateCapability(item.key, { enabled: value })}
              />
            </div>
            <div className={styles.slotForm}>
              <div className={styles.slotField}>
                <label className={styles.slotLabel}>{t("models.mode")}</label>
                <Select
                  value={form[item.key].mode}
                  onChange={(value) =>
                    updateCapability(item.key, { mode: value as ModeValue })
                  }
                  options={modeOptions}
                />
              </div>
              <div className={styles.slotField}>
                <label className={styles.slotLabel}>{t("models.maxItems")}</label>
                <InputNumber
                  style={{ width: "100%" }}
                  min={1}
                  max={item.maxLimit}
                  value={form[item.key].maxItems}
                  onChange={(value) =>
                    updateCapability(item.key, { maxItems: Number(value || 1) })
                  }
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className={styles.visionAdvancedGrid}>
        {CAPABILITIES.map((item) => (
          <div className={styles.slotField} key={`${item.key}-timeout`}>
            <label className={styles.slotLabel}>{t(item.timeoutLabelKey)}</label>
            <div className={styles.visionInline}>
              <InputNumber
                min={5}
                max={600}
                value={form[item.key].timeoutSeconds}
                onChange={(value) =>
                  updateCapability(item.key, { timeoutSeconds: Number(value || 1) })
                }
              />
              <InputNumber
                min={200}
                max={30000}
                value={form[item.key].maxOutputChars}
                onChange={(value) =>
                  updateCapability(item.key, { maxOutputChars: Number(value || 200) })
                }
              />
            </div>
          </div>
        ))}

        {CAPABILITIES.map((item) => (
          <div className={styles.slotField} key={`${item.key}-prompt`}>
            <label className={styles.slotLabel}>{t(item.promptLabelKey)}</label>
            <Input
              value={form[item.key].promptOverride}
              onChange={(e) =>
                updateCapability(item.key, { promptOverride: e.target.value })
              }
            />
          </div>
        ))}
      </div>

      <div className={styles.slotActions}>
        <Button
          type="primary"
          loading={saving}
          disabled={!dirty}
          onClick={handleSave}
          icon={<SaveOutlined />}
        >
          {t("models.save")}
        </Button>
      </div>
    </div>
  );
}

