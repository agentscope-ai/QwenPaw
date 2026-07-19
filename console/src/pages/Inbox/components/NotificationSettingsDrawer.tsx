import {
  Drawer,
  Switch,
  Select,
  InputNumber,
  Button,
  Tag,
  Tooltip,
} from "antd";
import { InfoCircleOutlined } from "@agentscope-ai/icons-override-antd";
import { useTranslation } from "react-i18next";
import { useNotifications } from "../../Settings/Notifications/useNotifications";
import { useAgentStore } from "../../../stores/agentStore";
import { getAgentDisplayName } from "../../../utils/agentDisplayName";
import {
  NOTIFICATION_SOURCE_KEYS,
  type NotificationSourceToggles,
} from "../../../api/modules/notifications";
import styles from "./NotificationSettingsDrawer.module.less";

interface Props {
  open: boolean;
  onClose: () => void;
}

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
        width={400}
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
      width={400}
    >
      <div className={styles.container}>
        {/* Part 1: Basic switches - no title */}
        <div className={styles.section}>
          <div className={styles.row}>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span className={styles.labelBold}>
                {t("notifications.enableLabel")}
              </span>
              <Tooltip
                title={t("notifications.osPermissionHint")}
                overlayStyle={{ maxWidth: 320 }}
              >
                <span className={styles.tooltipTrigger}>
                  <InfoCircleOutlined />
                </span>
              </Tooltip>
            </div>
            <Switch
              size="small"
              checked={config.enabled}
              onChange={toggleEnabled}
              loading={saving}
            />
          </div>
          <div className={styles.row}>
            <span className={styles.labelBold}>
              {t("notifications.soundLabelShort")}
            </span>
            <Switch
              size="small"
              checked={config.sound}
              onChange={toggleSound}
              disabled={!config.enabled}
              loading={saving}
            />
          </div>
        </div>

        {/* Part 2: Sources */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            {t("notifications.sourcesTitle")}
          </div>
          {NOTIFICATION_SOURCE_KEYS.map(
            ({ key, labelKey, hintKey, indent, isLabel }) =>
              isLabel ? (
                <div key={key} className={styles.row}>
                  <span className={styles.labelMuted}>{t(labelKey)}</span>
                </div>
              ) : (
                <div
                  key={key}
                  className={styles.row}
                  style={indent ? { paddingLeft: 16 } : undefined}
                >
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 4 }}
                  >
                    <span className={styles.label}>{t(labelKey)}</span>
                    {hintKey && (
                      <Tooltip title={t(hintKey)}>
                        <span className={styles.tooltipTrigger}>
                          <InfoCircleOutlined />
                        </span>
                      </Tooltip>
                    )}
                  </div>
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

        {/* Part 3: Advanced */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            {t("notifications.advancedTitle")}
          </div>

          {agentOptions.length > 1 && (
            <div className={styles.fieldBlock}>
              <div
                className={styles.fieldLabel}
                style={{ display: "flex", alignItems: "center", gap: 4 }}
              >
                {t("notifications.agentFilterTitle")}
                <Tooltip title={t("notifications.agentFilterHint")}>
                  <span className={styles.tooltipTrigger}>
                    <InfoCircleOutlined />
                  </span>
                </Tooltip>
              </div>
              <Select
                mode="multiple"
                allowClear
                size="small"
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

          <div className={styles.row}>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span className={styles.label}>
                {t("notifications.intervalLabel")}
              </span>
              <Tooltip title={t("notifications.intervalHint")}>
                <span className={styles.tooltipTrigger}>
                  <InfoCircleOutlined />
                </span>
              </Tooltip>
            </div>
            <InputNumber
              size="small"
              min={1}
              max={3600}
              value={config.min_interval_seconds}
              onChange={(val) => val && updateMinInterval(val)}
              disabled={!config.enabled}
              addonAfter="s"
              style={{ width: 100 }}
            />
          </div>

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
      </div>
    </Drawer>
  );
}
