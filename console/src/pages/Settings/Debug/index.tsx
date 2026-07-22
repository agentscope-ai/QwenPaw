import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { HelpCircle } from "lucide-react";
import dayjs from "dayjs";
import { PageHeader } from "@/components/PageHeader";
import { useDebugLogs, backendLevelColor } from "./useDebugLogs";
import { useMessageRecording } from "./useMessageRecording";
import { LogViewer } from "./components";
import styles from "./index.module.less";

const { Text } = Typography;

export default function DebugPage() {
  const { t } = useTranslation();
  const {
    backendLogs,
    initialLoading,
    backendError,
    autoRefresh,
    setAutoRefresh,
    backendNewestFirst,
    setBackendNewestFirst,
    backendLevel,
    setBackendLevel,
    backendQuery,
    setBackendQuery,
    filteredBackendLines,
    loadBackendLogs,
    handleCopyBackend,
  } = useDebugLogs();

  const {
    enabled,
    storagePath,
    loading: recordingLoading,
    toggleEnabled,
    draftMaxLen,
    setDraftMaxLen,
    commitMaxContentLength,
    draftRetention,
    setDraftRetention,
    commitRetentionDays,
  } = useMessageRecording();

  return (
    <div className={styles.debugPage}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("debug.title", "Debug")}
      />

      <div className={styles.content}>
        <Alert
          type="info"
          showIcon
          className={styles.tipAlert}
          message={t(
            "debug.desc",
            "View backend daemon log file to help diagnose issues. Logs refresh automatically while this page is open.",
          )}
        />

        <Card
          title={t("debug.backend.title", "Backend logs")}
          extra={
            <Space size="middle" className={styles.cardExtra}>
              <Text type="secondary">
                {t("debug.backend.newestFirst", "Newest first")}
              </Text>
              <Switch
                checked={backendNewestFirst}
                onChange={setBackendNewestFirst}
              />
              <Text type="secondary">
                {t("debug.backend.autoRefresh", "Auto refresh")}
              </Text>
              <Switch checked={autoRefresh} onChange={setAutoRefresh} />
            </Space>
          }
        >
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <div className={styles.toolbar}>
              <div className={styles.toolbarLeft}>
                <Select
                  className={styles.levelSelect}
                  value={backendLevel}
                  onChange={(v) => setBackendLevel(v)}
                  options={[
                    { value: "all", label: t("debug.level.all", "All") },
                    {
                      value: "error",
                      label: (
                        <Tag color={backendLevelColor("error")}>ERROR</Tag>
                      ),
                    },
                    {
                      value: "warning",
                      label: (
                        <Tag color={backendLevelColor("warning")}>WARNING</Tag>
                      ),
                    },
                    {
                      value: "info",
                      label: <Tag color={backendLevelColor("info")}>INFO</Tag>,
                    },
                    {
                      value: "debug",
                      label: (
                        <Tag color={backendLevelColor("debug")}>DEBUG</Tag>
                      ),
                    },
                  ]}
                />
                <Input
                  className={styles.searchInput}
                  value={backendQuery}
                  onChange={(e) => setBackendQuery(e.target.value)}
                  placeholder={t(
                    "debug.backend.searchPlaceholder",
                    "Search backend logs...",
                  )}
                  allowClear
                />
                {backendLogs?.updated_at && (
                  <Text type="secondary" className={styles.updatedAt}>
                    {t("debug.backend.updatedAt", "Updated at")}:{" "}
                    {dayjs(backendLogs.updated_at * 1000).format(
                      "YYYY-MM-DD HH:mm:ss",
                    )}
                  </Text>
                )}
              </div>
              <div className={styles.toolbarRight}>
                <Button
                  onClick={() => void loadBackendLogs({ successToast: true })}
                >
                  {t("debug.actions.refreshBackend", "Refresh backend logs")}
                </Button>
                <Button onClick={() => void handleCopyBackend()}>
                  {t("debug.actions.copyBackend", "Copy backend logs")}
                </Button>
              </div>
            </div>

            {backendLogs?.path && (
              <div className={styles.logPath}>
                <Text type="secondary" className={styles.logPathLabel}>
                  {t("debug.backend.path", "Log file")}
                </Text>
                <code className={styles.logPathValue}>{backendLogs.path}</code>
              </div>
            )}

            {backendError ? (
              <Alert message={backendError} type="error" showIcon />
            ) : !backendLogs?.exists ? (
              <Alert
                message={t(
                  "debug.backend.notFound",
                  "Backend log file was not found yet.",
                )}
                type="warning"
                showIcon
              />
            ) : null}

            <LogViewer
              lines={filteredBackendLines}
              query={backendQuery}
              loading={initialLoading}
            />
          </Space>
        </Card>

        <Card
          title={t("debug.messageRecording.title", "Message Recording")}
          extra={
            <Switch
              checked={enabled}
              loading={recordingLoading}
              disabled={recordingLoading}
              onChange={toggleEnabled}
            />
          }
        >
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Text type="secondary">
              {t(
                "debug.messageRecording.desc",
                "Record LLM call inputs and outputs to JSONL files for debugging.",
              )}
            </Text>
            <div className={styles.recordingFields}>
              <div className={styles.recordingField}>
                <Text>
                  {t(
                    "debug.messageRecording.maxContentLength",
                    "Max content length",
                  )}
                  <Tooltip
                    title={t(
                      "debug.messageRecording.maxContentLengthTooltip",
                      "Truncate text content exceeding this length. Leave empty for no truncation.",
                    )}
                  >
                    <HelpCircle
                      size={14}
                      style={{ marginLeft: 4, color: "rgba(0,0,0,0.45)" }}
                    />
                  </Tooltip>
                </Text>
                <InputNumber
                  min={1}
                  value={draftMaxLen}
                  onChange={(v) => setDraftMaxLen(v)}
                  onBlur={() => commitMaxContentLength()}
                  onPressEnter={() => commitMaxContentLength()}
                  style={{ width: 200 }}
                  disabled={!enabled || recordingLoading}
                />
              </div>
              <div className={styles.recordingField}>
                <Text>
                  {t("debug.messageRecording.retentionDays", "Retention days")}
                  <Tooltip
                    title={t(
                      "debug.messageRecording.retentionDaysTooltip",
                      "Automatically delete JSONL files older than this many days.",
                    )}
                  >
                    <HelpCircle
                      size={14}
                      style={{ marginLeft: 4, color: "rgba(0,0,0,0.45)" }}
                    />
                  </Tooltip>
                </Text>
                <InputNumber
                  min={1}
                  max={90}
                  value={draftRetention}
                  onChange={(v) => setDraftRetention(v ?? 3)}
                  onBlur={() => commitRetentionDays()}
                  onPressEnter={() => commitRetentionDays()}
                  style={{ width: 200 }}
                  disabled={!enabled || recordingLoading}
                />
              </div>
            </div>
            <div className={styles.recordingStatus}>
              <Text type="secondary">
                {t("debug.messageRecording.status", "Status")}:{" "}
                {enabled
                  ? t("debug.messageRecording.statusRecording", "Recording")
                  : t("debug.messageRecording.statusStopped", "Stopped")}
              </Text>
              {storagePath && (
                <Text type="secondary">
                  {t("debug.messageRecording.storagePath", "Storage path")}:{" "}
                  <code>{storagePath}</code>
                </Text>
              )}
            </div>
          </Space>
        </Card>
      </div>
    </div>
  );
}
