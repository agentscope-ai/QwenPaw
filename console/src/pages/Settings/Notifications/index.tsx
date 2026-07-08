import { Button, Card, Switch, Select, InputNumber, Tag } from "antd";
import { BellOutlined, SoundOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useNotifications } from "./useNotifications";
import { useAgentStore } from "../../../stores/agentStore";
import { getAgentDisplayName } from "../../../utils/agentDisplayName";
import type { NotificationSourceToggles } from "../../../api/modules/notifications";
import styles from "./index.module.less";

const SOURCE_KEYS: {
  key: keyof NotificationSourceToggles;
  labelKey: string;
  hintKey: string;
}[] = [
  {
    key: "cron",
    labelKey: "notifications.sourceCron",
    hintKey: "notifications.sourceCronHint",
  },
  {
    key: "heartbeat",
    labelKey: "notifications.sourceHeartbeat",
    hintKey: "notifications.sourceHeartbeatHint",
  },
  {
    key: "memory",
    labelKey: "notifications.sourceMemory",
    hintKey: "notifications.sourceMemoryHint",
  },
  {
    key: "skill_autoupdate",
    labelKey: "notifications.sourceSkillUpdate",
    hintKey: "notifications.sourceSkillUpdateHint",
  },
];

export default function NotificationsPage() {
  const { t } = useTranslation();
  const agents = useAgentStore((state) => state.agents);
  const {
    config,
    loading,
    saving,
    testing,
    testResult,
    error,
    fetchConfig,
    toggleEnabled,
    toggleSound,
    updateMinInterval,
    toggleSource,
    updateAgentIds,
    sendTest,
  } = useNotifications();

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.centerState}>
          <span>{t("common.loading")}</span>
        </div>
      </div>
    );
  }

  if (error && !config) {
    return (
      <div className={styles.page}>
        <div className={styles.centerState}>
          <span className={styles.errorText}>{error}</span>
          <Button size="small" onClick={fetchConfig} style={{ marginTop: 12 }}>
            {t("environments.retry")}
          </Button>
        </div>
      </div>
    );
  }

  if (!config) return null;

  const agentOptions = agents.map((agent) => ({
    value: agent.id,
    label: getAgentDisplayName(agent, t),
  }));

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("notifications.title")}
      />

      <Card className={styles.settingsCard}>
        <div className={styles.settingRow}>
          <div className={styles.settingLabel}>
            <BellOutlined className={styles.settingIcon} />
            <div>
              <div className={styles.settingTitle}>
                {t("notifications.enableLabel")}
              </div>
              <div className={styles.settingHint}>
                {t("notifications.enableHint")}
              </div>
            </div>
          </div>
          <Switch
            checked={config.enabled}
            onChange={toggleEnabled}
            loading={saving}
          />
        </div>

        <div className={styles.settingRow}>
          <div className={styles.settingLabel}>
            <SoundOutlined className={styles.settingIcon} />
            <div>
              <div className={styles.settingTitle}>
                {t("notifications.soundLabel")}
              </div>
              <div className={styles.settingHint}>
                {t("notifications.soundHint")}
              </div>
            </div>
          </div>
          <Switch
            checked={config.sound}
            onChange={toggleSound}
            disabled={!config.enabled}
            loading={saving}
          />
        </div>

        <div className={styles.settingRow}>
          <div className={styles.settingLabel}>
            <div>
              <div className={styles.settingTitle}>
                {t("notifications.intervalLabel")}
              </div>
              <div className={styles.settingHint}>
                {t("notifications.intervalHint")}
              </div>
            </div>
          </div>
          <InputNumber
            min={1}
            max={3600}
            value={config.min_interval_seconds}
            onChange={(val) => val && updateMinInterval(val)}
            disabled={!config.enabled}
            addonAfter="s"
            className={styles.intervalInput}
          />
        </div>

        <div className={styles.settingRow}>
          <Button
            onClick={sendTest}
            loading={testing}
            disabled={!config.enabled}
          >
            {t("notifications.testButton")}
          </Button>
          {testResult && (
            <Tag color={testResult.success ? "success" : "error"}>
              {testResult.message}
            </Tag>
          )}
        </div>
      </Card>

      <Card className={styles.settingsCard}>
        <h3>{t("notifications.sourcesTitle")}</h3>
        <p className={styles.settingHint}>{t("notifications.sourcesHint")}</p>
        {SOURCE_KEYS.map(({ key, labelKey, hintKey }) => (
          <div key={key} className={styles.settingRow}>
            <div className={styles.settingLabel}>
              <div>
                <div className={styles.settingTitle}>{t(labelKey)}</div>
                <div className={styles.settingHint}>{t(hintKey)}</div>
              </div>
            </div>
            <Switch
              size="small"
              checked={config.sources[key]}
              onChange={(checked) => toggleSource(key, checked)}
              disabled={!config.enabled}
            />
          </div>
        ))}
      </Card>

      {agentOptions.length > 1 && (
        <Card className={styles.settingsCard}>
          <h3>{t("notifications.agentFilterTitle")}</h3>
          <p className={styles.settingHint}>
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
        </Card>
      )}
    </div>
  );
}
