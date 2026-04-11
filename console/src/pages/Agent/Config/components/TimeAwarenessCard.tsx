import { useState, useEffect, useCallback } from "react";
import { Switch, Card, Input, Tag, Tooltip } from "@agentscope-ai/design";
import { Typography, Space } from "antd";
import {
  ClockCircleOutlined,
  InfoCircleOutlined,
  CheckCircleOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type { TimeAwarenessConfig } from "../../../../api/modules/timeAwareness";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import styles from "../index.module.less";

const { Text, Paragraph } = Typography;

interface TimeAwarenessCardProps {}

export function TimeAwarenessCard(_props: TimeAwarenessCardProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [enabled, setEnabled] = useState(false);
  const [format, setFormat] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const config = await api.getTimeAwareness();
      setEnabled(config.enabled);
      setFormat(config.format || "");
    } catch (err) {
      console.error("Failed to fetch time awareness config:", err);
      message.error(t("timeAwareness.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t, message]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleToggle = useCallback(
    async (checked: boolean) => {
      setSaving(true);
      try {
        await api.updateTimeAwareness({ enabled: checked, format: format || null });
        setEnabled(checked);
        message.success(
          checked
            ? t("timeAwareness.enableSuccess")
            : t("timeAwareness.disableSuccess"),
        );
      } catch (err) {
        console.error("Failed to update time awareness:", err);
        message.error(t("timeAwareness.saveFailed"));
        // Revert on error
        setEnabled(!checked);
      } finally {
        setSaving(false);
      }
    },
    [format, t, message],
  );

  const handleFormatChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const newFormat = e.target.value;
      setFormat(newFormat);

      if (enabled) {
        setSaving(true);
        try {
          await api.updateTimeAwareness({
            enabled,
            format: newFormat || null,
          });
          message.success(t("timeAwareness.formatSaveSuccess"));
        } catch (err) {
          console.error("Failed to update time format:", err);
          message.error(t("timeAwareness.formatSaveFailed"));
          // Revert on error
          setFormat(format);
        } finally {
          setSaving(false);
        }
      }
    },
    [enabled, format, t, message],
  );

  if (loading) {
    return (
      <Card className={styles.formCard} loading={loading}>
        <div style={{ height: 200 }} />
      </Card>
    );
  }

  return (
    <Card
      className={styles.formCard}
      title={
        <Space>
          <ClockCircleOutlined />
          <span>{t("timeAwareness.title")}</span>
          {enabled ? (
            <Tag color="success" icon={<CheckCircleOutlined />}>
              {t("timeAwareness.enabled")}
            </Tag>
          ) : (
            <Tag>{t("timeAwareness.disabled")}</Tag>
          )}
        </Space>
      }
    >
      <div className={styles.timeAwarenessContainer}>
        <Paragraph className={styles.description}>
          {t("timeAwareness.description")}
        </Paragraph>

        <div className={styles.switchRow}>
          <Space direction="vertical" size="small" style={{ flex: 1 }}>
            <Text strong>{t("timeAwareness.enableLabel")}</Text>
            <Text type="secondary" className={styles.hintText}>
              {t("timeAwareness.enableHint")}
            </Text>
          </Space>

          <Switch
            checked={enabled}
            onChange={handleToggle}
            loading={saving}
            checkedChildren={t("timeAwareness.on")}
            unCheckedChildren={t("timeAwareness.off")}
            style={{ marginLeft: "auto" }}
          />
        </div>

        {enabled && (
          <div className={styles.formatSection}>
            <Space direction="vertical" size="small" style={{ width: "100%" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Text strong>{t("timeAwareness.formatLabel")}</Text>
                <Tooltip title={t("timeAwareness.formatTooltip")}>
                  <InfoCircleOutlined style={{ color: "#999" }} />
                </Tooltip>
              </div>

              <Input
                value={format}
                onChange={handleFormatChange}
                placeholder={t("timeAwareness.formatPlaceholder")}
                disabled={!enabled || saving}
                allowClear
                suffix={
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    strftime
                  </Text>
                }
              />

              <div className={styles.formatExamples}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t("timeAwareness.examples")}:
                </Text>
                <Space size={4} wrap>
                  <Tag
                    onClick={() => setFormat("%Y-%m-%d %H:%M:%S")}
                    style={{ cursor: "pointer" }}
                  >
                    Default
                  </Tag>
                  <Tag
                    onClick={() => setFormat("%Y-%m-%d %H:%M")}
                    style={{ cursor: "pointer" }}
                  >
                    Compact
                  </Tag>
                  <Tag
                    onClick={() => setFormat("%H:%M")}
                    style={{ cursor: "pointer" }}
                  >
                    Time Only
                  </Tag>
                </Space>
              </div>
            </Space>

            <div className={styles.previewSection}>
              <Text strong>{t("timeAwareness.previewLabel")}</Text>
              <div className={styles.previewBox}>
                <Text code style={{ fontSize: 13 }}>
                  {[t("timeAwareness.previewPrefix"), ": 2026-04-11 14:30:45 Asia/Shanghai (Saturday)"].join("")}
                </Text>
                <Text type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
                  {t("timeAwareness.previewHint")}
                </Text>
              </div>
            </div>
          </div>
        )}

        {!enabled && (
          <div className={styles.disabledHint}>
            <Text type="warning">
              ⚠️ {t("timeAwareness.disabledHint")}
            </Text>
          </div>
        )}
      </div>
    </Card>
  );
}