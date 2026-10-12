import { NumberStepper as InputNumber } from "@/components/interaction/NumberStepper";
import { SettingsField } from "@/components/interaction/SettingsField";
import { SchedulePicker } from "@/components/interaction/SchedulePicker";
import { Card, Form, Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { ReMeLightMemoryConfig } from "@/api/types/agent";
import { isValidDreamCronShape } from "./dreamCron";
import styles from "../index.module.less";

// The backend schema keeps validating these numbers while the proactive
// section is switched off, so a cleared stepper must never reach the payload.
// Each entry mirrors the field's min/max rules and its backend default.
const PROACTIVE_NUMBER_LIMITS: Record<
  string,
  { min: number; max?: number; fallback: number }
> = {
  proactive_max_items: { min: 1, max: 10, fallback: 3 },
  proactive_refresh_min_interval_minutes: { min: 0, fallback: 120 },
  proactive_delivery_cooldown_days: { min: 0, max: 90, fallback: 3 },
  proactive_cron_max_items: { min: 0, max: 20, fallback: 0 },
};
const PROACTIVE_NUMBER_FIELDS = Object.keys(PROACTIVE_NUMBER_LIMITS);

/** The ReMe proactive agenda: closing card of Memory & Retrieval. */
export function ProactiveAgendaCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const remeConfig = Form.useWatch(["reme_light_memory_config"], form) as
    | ReMeLightMemoryConfig
    | undefined;
  const proactiveEnabled = remeConfig?.proactive_enabled ?? false;
  const proactiveCronEnabled = remeConfig?.proactive_cron_enabled ?? false;

  // antd skips the min/max rules for an empty InputNumber, so a value the user
  // cleared has to be rewritten before the form can be submitted again: the
  // backend validates these numbers even while proactive is switched off.
  const normalizeProactiveNumbers = (
    fields: string[] = PROACTIVE_NUMBER_FIELDS,
  ) => {
    form.setFields(
      fields.map((field) => {
        const limits = PROACTIVE_NUMBER_LIMITS[field];
        const value = form.getFieldValue(["reme_light_memory_config", field]);
        const valid =
          typeof value === "number" &&
          Number.isInteger(value) &&
          value >= limits.min &&
          (limits.max === undefined || value <= limits.max);
        return {
          name: ["reme_light_memory_config", field],
          value: valid ? value : limits.fallback,
          errors: [],
        };
      }),
    );
  };

  return (
    <Card className={styles.formCard}>
      <div className={styles.memoryConfigGrid}>
        <section className={styles.memoryConfigPanel}>
          <div className={styles.memorySectionHeader}>
            <div>
              <h3>{t("agentConfig.proactiveSectionTitle")}</h3>
              <p>{t("agentConfig.proactiveSectionDescription")}</p>
            </div>
            <SettingsField
              name={["reme_light_memory_config", "proactive_enabled"]}
              initialValue={false}
              valuePropName="checked"
              noStyle
            >
              <Switch
                aria-label={t("agentConfig.proactiveEnableTitle")}
                onChange={(checked) => {
                  if (!checked) {
                    normalizeProactiveNumbers();
                  }
                }}
              />
            </SettingsField>
          </div>
          <div className={styles.memorySettingRow}>
            <div>
              <strong>{t("agentConfig.proactiveMaxItems")}</strong>
              <span>{t("agentConfig.proactiveMaxItemsTooltip")}</span>
            </div>
            <SettingsField
              className={styles.memoryInlineField}
              name={["reme_light_memory_config", "proactive_max_items"]}
              initialValue={3}
              rules={[
                {
                  validator: (_, value?: number) =>
                    Number.isInteger(value)
                      ? Promise.resolve()
                      : Promise.reject(
                          new Error(t("agentConfig.proactiveNumberRequired")),
                        ),
                },
                {
                  type: "number",
                  min: 1,
                  message: t("agentConfig.proactiveMaxItemsMin"),
                },
                {
                  type: "number",
                  max: 10,
                  message: t("agentConfig.proactiveMaxItemsMax"),
                },
              ]}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                max={10}
                step={1}
                precision={0}
                disabled={!proactiveEnabled}
              />
            </SettingsField>
          </div>
          <div className={styles.memorySettingRow}>
            <div>
              <strong>{t("agentConfig.proactiveRefreshInterval")}</strong>
              <span>{t("agentConfig.proactiveRefreshIntervalTooltip")}</span>
            </div>
            <SettingsField
              className={styles.memoryInlineField}
              name={[
                "reme_light_memory_config",
                "proactive_refresh_min_interval_minutes",
              ]}
              initialValue={120}
              rules={[
                {
                  validator: (_, value?: number) =>
                    Number.isInteger(value)
                      ? Promise.resolve()
                      : Promise.reject(
                          new Error(t("agentConfig.proactiveNumberRequired")),
                        ),
                },
                {
                  type: "number",
                  min: 0,
                  message: t("agentConfig.proactiveRefreshIntervalMin"),
                },
              ]}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={0}
                step={15}
                precision={0}
                disabled={!proactiveEnabled}
              />
            </SettingsField>
          </div>
          <div className={styles.memoryToggleRow}>
            <div>
              <strong>{t("agentConfig.proactiveNotifyTitle")}</strong>
              <span>{t("agentConfig.proactiveNotifyDescription")}</span>
            </div>
            <SettingsField
              name={[
                "reme_light_memory_config",
                "proactive_inbox_push_enabled",
              ]}
              initialValue
              valuePropName="checked"
              noStyle
            >
              <Switch disabled={!proactiveEnabled} />
            </SettingsField>
          </div>
          <div className={styles.memorySettingRow}>
            <div>
              <strong>{t("agentConfig.proactiveCooldownDays")}</strong>
              <span>{t("agentConfig.proactiveCooldownDaysTooltip")}</span>
            </div>
            <SettingsField
              className={styles.memoryInlineField}
              name={[
                "reme_light_memory_config",
                "proactive_delivery_cooldown_days",
              ]}
              initialValue={3}
              rules={[
                {
                  validator: (_, value?: number) =>
                    Number.isInteger(value)
                      ? Promise.resolve()
                      : Promise.reject(
                          new Error(t("agentConfig.proactiveNumberRequired")),
                        ),
                },
                {
                  type: "number",
                  min: 0,
                  message: t("agentConfig.proactiveCooldownDaysMin"),
                },
                {
                  type: "number",
                  max: 90,
                  message: t("agentConfig.proactiveCooldownDaysMax"),
                },
              ]}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={0}
                max={90}
                step={1}
                precision={0}
                disabled={!proactiveEnabled}
              />
            </SettingsField>
          </div>
          <div className={styles.memoryToggleRow}>
            <div>
              <strong>{t("agentConfig.proactiveCronTitle")}</strong>
              <span>{t("agentConfig.proactiveCronTooltip")}</span>
            </div>
            <SettingsField
              name={["reme_light_memory_config", "proactive_cron_enabled"]}
              initialValue={false}
              valuePropName="checked"
              noStyle
            >
              <Switch
                disabled={!proactiveEnabled}
                onChange={(checked) => {
                  if (!checked) {
                    normalizeProactiveNumbers(["proactive_cron_max_items"]);
                  }
                }}
              />
            </SettingsField>
          </div>
          <SettingsField
            label={t("agentConfig.proactiveCron")}
            name={["reme_light_memory_config", "proactive_cron"]}
            tooltip={t("agentConfig.proactiveCronTooltip")}
            rules={
              proactiveEnabled && proactiveCronEnabled
                ? [
                    {
                      required: true,
                      whitespace: true,
                      message: t("agentConfig.proactiveCronRequired"),
                    },
                    {
                      validator: (_, value?: string) => {
                        if (!value?.trim() || isValidDreamCronShape(value)) {
                          return Promise.resolve();
                        }
                        return Promise.reject(
                          new Error(t("agentConfig.proactiveCronInvalid")),
                        );
                      },
                    },
                  ]
                : []
            }
          >
            <SchedulePicker
              disabled={!proactiveEnabled || !proactiveCronEnabled}
            />
          </SettingsField>
          <div className={styles.memorySettingRow}>
            <div>
              <strong>{t("agentConfig.proactiveCronMaxItems")}</strong>
              <span>{t("agentConfig.proactiveCronMaxItemsTooltip")}</span>
            </div>
            <SettingsField
              className={styles.memoryInlineField}
              name={["reme_light_memory_config", "proactive_cron_max_items"]}
              initialValue={0}
              rules={[
                {
                  validator: (_, value?: number) =>
                    Number.isInteger(value)
                      ? Promise.resolve()
                      : Promise.reject(
                          new Error(t("agentConfig.proactiveNumberRequired")),
                        ),
                },
                {
                  type: "number",
                  min: 0,
                  message: t("agentConfig.proactiveCronMaxItemsMin"),
                },
                {
                  type: "number",
                  max: 20,
                  message: t("agentConfig.proactiveCronMaxItemsMax"),
                },
              ]}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={0}
                max={20}
                step={1}
                precision={0}
                disabled={!proactiveEnabled || !proactiveCronEnabled}
              />
            </SettingsField>
          </div>
        </section>
      </div>
    </Card>
  );
}
