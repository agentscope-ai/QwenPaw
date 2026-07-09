import { Drawer, Switch, Select, InputNumber, Button, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { useNotifications } from "../../Settings/Notifications/useNotifications";
import { useAgentStore } from "../../../stores/agentStore";
import { getAgentDisplayName } from "../../../utils/agentDisplayName";
import type { NotificationSourceToggles } from "../../../api/modules/notifications";
import styles from "./NotificationSettingsDrawer.module.less";

interface Props {
  open: boolean;
  onClose: () => void;
}

const SOURCE_KEYS: {
  key: keyof NotificationSourceToggles | "_label";
  labelKey: string;
  indent?: boolean;
  isLabel?: boolean;
}[] = [
  { key: "approval", labelKey: "notifications.sourceApproval" },
  { key: "_label", labelKey: "notifications.sourceCron", isLabel: true },
  { key: "cron_text", labelKey: "notifications.sourceCronText", indent: true },
  {
    key: "cron_agent",
    labelKey: "notifications.sourceCronAgent",
    indent: true,
  },
  { key: "heartbeat", labelKey: "notifications.sourceHeartbeat" },
  { key: "memory", labelKey: "notifications.sourceMemory" },
  { key: "skill_autoupdate", labelKey: "notifications.sourceSkillUpdate" },
];

export function NotificationSettingsDrawer({ open, onClose }: Props) {
  const { t } = useTranslation();
  const agents = useAgentStore((state) => state.agents);
  const {
    config,
    loading,
    saving,
    testing,
    testResult,
    toggleEnabled,
    toggleSound,
    updateMinInterval,
    toggleSource,
    updateAgentIds,
    sendTest,
  } = useNotifications();

  if (loading || !config) {
    return (
      <Drawer
        title={t("notifications.title")}
        open={open}
        onClose={onClose}
        width={420}
      >
        <div className={styles.loading}>{t("common.loading")}</div>
      </Drawer>
    );
  }

  const agentOptions = agents.map((agent) => ({
    value: agent.id,
    label: getAgentDisplayName(agent, t),
  }));

  return (
    <Drawer
      title={t("notifications.title")}
      open={open}
      onClose={onClose}
      width={420}
    >
      <div className={styles.container}>
        <p className={styles.description}>{t("notifications.description")}</p>

        {/* Master switch */}
        <div className={styles.settingRow}>
          <div className={styles.settingInfo}>
            <div className={styles.settingTitle}>
              {t("notifications.enableLabel")}
            </div>
            <div className={styles.settingHint}>
              {t("notifications.enableHint")}
            </div>
          </div>
          <Switch
            checked={config.enabled}
            onChange={toggleEnabled}
            loading={saving}
          />
        </div>

        {/* Sound */}
        <div className={styles.settingRow}>
          <div className={styles.settingInfo}>
            <div className={styles.settingTitle}>
              {t("notifications.soundLabel")}
            </div>
            <div className={styles.settingHint}>
              {t("notifications.soundHint")}
            </div>
          </div>
          <Switch
            checked={config.sound}
            onChange={toggleSound}
            disabled={!config.enabled}
            loading={saving}
          />
        </div>

        {/* Min interval */}
        <div className={styles.settingRow}>
          <div className={styles.settingInfo}>
            <div className={styles.settingTitle}>
              {t("notifications.intervalLabel")}
            </div>
            <div className={styles.settingHint}>
              {t("notifications.intervalHint")}
            </div>
          </div>
          <InputNumber
            min={1}
            max={3600}
            value={config.min_interval_seconds}
            onChange={(val) => val && updateMinInterval(val)}
            disabled={!config.enabled}
            addonAfter="s"
            style={{ width: 110 }}
          />
        </div>

        {/* Source toggles */}
        <div className={styles.section}>
          <h4 className={styles.sectionTitle}>
            {t("notifications.sourcesTitle")}
          </h4>
          <p className={styles.sectionHint}>{t("notifications.sourcesHint")}</p>
          {SOURCE_KEYS.map(({ key, labelKey, indent, isLabel }) =>
            isLabel ? (
              <div key={key} className={styles.sourceRow}>
                <div className={styles.sourceLabel}>{t(labelKey)}</div>
              </div>
            ) : (
              <div
                key={key}
                className={styles.sourceRow}
                style={indent ? { paddingLeft: 16 } : undefined}
              >
                <div className={styles.sourceLabel}>{t(labelKey)}</div>
                <Switch
                  size="small"
                  checked={
                    config.sources[key as keyof NotificationSourceToggles]
                  }
                  onChange={(checked) =>
                    toggleSource(
                      key as keyof NotificationSourceToggles,
                      checked,
                    )
                  }
                  disabled={!config.enabled}
                />
              </div>
            ),
          )}
        </div>

        {/* Agent filter */}
        {agentOptions.length > 1 && (
          <div className={styles.section}>
            <h4 className={styles.sectionTitle}>
              {t("notifications.agentFilterTitle")}
            </h4>
            <p className={styles.sectionHint}>
              {t("notifications.agentFilterHint")}
            </p>
            <Select
              mode="multiple"
              allowClear
              placeholder={t("notifications.allAgentsPlaceholder")}
              value={config.agent_ids ?? undefined}
              onChange={(val) =>
                updateAgentIds(val && val.length > 0 ? val : null)
              }
              options={agentOptions}
              disabled={!config.enabled}
              style={{ width: "100%" }}
            />
          </div>
        )}

        {/* Test button */}
        <div className={styles.testRow}>
          <Button
            onClick={sendTest}
            loading={testing}
            disabled={!config.enabled}
            size="small"
          >
            {t("notifications.testButton")}
          </Button>
          {testResult && (
            <Tag color={testResult.success ? "success" : "error"}>
              {testResult.message}
            </Tag>
          )}
        </div>
      </div>
    </Drawer>
  );
}
