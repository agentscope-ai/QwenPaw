import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Button, Card, Switch, Table } from "@agentscope-ai/design";
import { Modal, Space, message } from "antd";
import { useTranslation } from "react-i18next";
import api from "@/api";
import type { IntegrityProtectionSettings } from "@/api/modules/security";
import { useFileBaselineDriftWatch } from "../hooks/useFileBaselineDriftWatch";
import {
  acceptFileBaselineAlert,
  restoreFileBaselineAlert,
} from "../lib/alertActions";
import type {
  FileBaselineProtectionAlert,
  FileBaselineProtectionSettings,
} from "../api/client";
import styles from "@/pages/Settings/Security/index.module.less";
import { FileBaselineProtectionFileList } from "./FileBaselineProtectionFileList";

interface FileBaselineProtectionContextValue {
  fileBaselineSettings: FileBaselineProtectionSettings | null;
  fileBaselineAlerts: FileBaselineProtectionAlert[];
  fileBaselineSwitchLoading: boolean;
  pathsSaving: boolean;
  restoringAlertId: string | null;
  acceptingAlertId: string | null;
  protectedPaths: string[];
  loadFileBaselineData: () => Promise<void>;
  onFileBaselineSwitchChange: (checked: boolean) => Promise<void>;
  toggleProtectedPath: (path: string, enabled: boolean) => Promise<void>;
  restoreAlert: (alert: FileBaselineProtectionAlert) => Promise<void>;
  acceptAlert: (alert: FileBaselineProtectionAlert) => Promise<void>;
}

const FileBaselineProtectionContext =
  createContext<FileBaselineProtectionContextValue | null>(null);

function useFileBaselineProtectionContext(): FileBaselineProtectionContextValue {
  const value = useContext(FileBaselineProtectionContext);
  if (!value) {
    throw new Error("FileBaselineProtection components must be used within Provider");
  }
  return value;
}

export interface FileBaselineProtectionProviderProps {
  children: ReactNode;
  highlightAlertId?: string;
  onAlertCountChange?: (count: number) => void;
  onIntegritySettingsSync?: (settings: IntegrityProtectionSettings) => void;
}

export function FileBaselineProtectionProvider({
  children,
  highlightAlertId,
  onAlertCountChange,
  onIntegritySettingsSync,
}: FileBaselineProtectionProviderProps) {
  const { t } = useTranslation();
  const [fileBaselineSettings, setFileBaselineSettings] =
    useState<FileBaselineProtectionSettings | null>(null);
  const [fileBaselineAlerts, setFileBaselineAlerts] = useState<
    FileBaselineProtectionAlert[]
  >([]);
  const [fileBaselineSwitchLoading, setFileBaselineSwitchLoading] = useState(false);
  const [pathsSaving, setPathsSaving] = useState(false);
  const [restoringAlertId, setRestoringAlertId] = useState<string | null>(null);
  const [acceptingAlertId, setAcceptingAlertId] = useState<string | null>(null);

  const loadFileBaselineData = useCallback(async () => {
    const [settings, alerts] = await Promise.all([
      api.getFileBaselineProtectionSettings(),
      api.getFileBaselineProtectionAlerts(),
    ]);
    setFileBaselineSettings(settings);
    setFileBaselineAlerts(alerts.alerts);
    onAlertCountChange?.(alerts.open_alert_count);
  }, [onAlertCountChange]);

  useFileBaselineDriftWatch(
    (event) => {
      if (
        event.type === "file_baseline_drift" ||
        event.type === "file_baseline_alert_resolved" ||
        event.type === "file_baseline_updated"
      ) {
        void loadFileBaselineData();
      }
    },
    Boolean(fileBaselineSettings?.enabled),
  );

  useEffect(() => {
    if (!highlightAlertId || fileBaselineAlerts.length === 0) {
      return;
    }
    const matched = fileBaselineAlerts.some(
      (alert) => alert.alert_id === highlightAlertId,
    );
    if (!matched) {
      return;
    }
    const row = document.getElementById(`file-baseline-alert-${highlightAlertId}`);
    row?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlightAlertId, fileBaselineAlerts]);

  const persistProtectedPaths = useCallback(
    async (nextPaths: string[]) => {
      setPathsSaving(true);
      try {
        const updated = await api.updateFileBaselineProtectionSettings({
          protected_targets: nextPaths,
        });
        setFileBaselineSettings(updated);
        const aggregate = await api.getIntegrityProtectionSettings();
        onIntegritySettingsSync?.(aggregate);
      } catch {
        message.error(t("security.integrityProtection.loadFailed"));
        throw new Error("protected paths update failed");
      } finally {
        setPathsSaving(false);
      }
    },
    [onIntegritySettingsSync, t],
  );

  const toggleProtectedPath = useCallback(
    async (path: string, enabled: boolean) => {
      const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "").trim();
      if (!normalized) {
        return;
      }
      const current = fileBaselineSettings?.protected_targets ?? [];
      if (enabled) {
        if (current.includes(normalized)) {
          return;
        }
        await persistProtectedPaths([...current, normalized]);
        message.success(t("security.integrityProtection.protectedPathAddSuccess"));
      } else {
        if (!current.includes(normalized)) {
          return;
        }
        await persistProtectedPaths(current.filter((item) => item !== normalized));
        message.success(t("security.integrityProtection.protectedPathRemoveSuccess"));
      }
      await loadFileBaselineData();
    },
    [fileBaselineSettings?.protected_targets, loadFileBaselineData, persistProtectedPaths, t],
  );

  const applyFileBaselineToggle = useCallback(
    async (checked: boolean, confirmationPhrase?: string) => {
      if (checked && (fileBaselineSettings?.protected_targets?.length ?? 0) === 0) {
        message.warning(t("security.integrityProtection.protectedPathEmpty"));
        return;
      }
      setFileBaselineSwitchLoading(true);
      try {
        const updated = await api.updateFileBaselineProtectionSettings({
          enabled: checked,
          confirmation_phrase: confirmationPhrase,
        });
        setFileBaselineSettings(updated);
        const aggregate = await api.getIntegrityProtectionSettings();
        onIntegritySettingsSync?.(aggregate);
        await loadFileBaselineData();
        message.success(
          checked
            ? t("security.integrityProtection.fileBaselineEnableSuccess")
            : t("security.integrityProtection.fileBaselineDisableSuccess"),
        );
      } catch {
        message.error(t("security.integrityProtection.loadFailed"));
        throw new Error("file baseline toggle failed");
      } finally {
        setFileBaselineSwitchLoading(false);
      }
    },
    [fileBaselineSettings?.protected_targets, loadFileBaselineData, onIntegritySettingsSync, t],
  );

  const onFileBaselineSwitchChange = useCallback(
    async (checked: boolean) => {
      if (checked) {
        if (fileBaselineSettings?.baseline_cleared_at) {
          Modal.confirm({
            title: t("security.integrityProtection.fileBaselineReestablishTitle"),
            content: t("security.integrityProtection.fileBaselineReestablishBody"),
            okText: t("common.confirm"),
            cancelText: t("common.cancel"),
            onOk: async () => {
              await applyFileBaselineToggle(
                true,
                t(
                  "security.integrityProtection.confirmReestablishFileBaselinePhrase",
                ),
              );
            },
          });
          return;
        }
      } else if ((fileBaselineSettings?.open_alert_count ?? 0) > 0) {
        Modal.confirm({
          title: t("security.integrityProtection.fileBaselineDisableWarningTitle"),
          content: t("security.integrityProtection.disableWithOpenDriftsWarning"),
          okText: t("common.confirm"),
          cancelText: t("common.cancel"),
          onOk: async () => {
            await applyFileBaselineToggle(false);
          },
        });
        return;
      }

      await applyFileBaselineToggle(checked);
    },
    [applyFileBaselineToggle, fileBaselineSettings, t],
  );

  const restoreAlert = useCallback(
    async (alert: FileBaselineProtectionAlert) => {
      setRestoringAlertId(alert.alert_id);
      try {
        const ok = await restoreFileBaselineAlert(alert.alert_id);
        if (!ok) {
          message.error(t("security.integrityProtection.loadFailed"));
          return;
        }
        message.success(t("security.integrityProtection.restoreSuccess"));
        await loadFileBaselineData();
      } finally {
        setRestoringAlertId(null);
      }
    },
    [loadFileBaselineData, t],
  );

  const acceptAlert = useCallback(
    async (alert: FileBaselineProtectionAlert) => {
      setAcceptingAlertId(alert.alert_id);
      try {
        const ok = await acceptFileBaselineAlert(alert.alert_id);
        if (!ok) {
          message.error(t("security.integrityProtection.loadFailed"));
          return;
        }
        message.success(t("security.integrityProtection.acceptSuccess"));
        await loadFileBaselineData();
      } finally {
        setAcceptingAlertId(null);
      }
    },
    [loadFileBaselineData, t],
  );

  const protectedPaths = fileBaselineSettings?.protected_targets ?? [];

  const value = useMemo(
    () => ({
      fileBaselineSettings,
      fileBaselineAlerts,
      fileBaselineSwitchLoading,
      pathsSaving,
      restoringAlertId,
      acceptingAlertId,
      protectedPaths,
      loadFileBaselineData,
      onFileBaselineSwitchChange,
      toggleProtectedPath,
      restoreAlert,
      acceptAlert,
    }),
    [
      acceptAlert,
      acceptingAlertId,
      fileBaselineAlerts,
      fileBaselineSettings,
      fileBaselineSwitchLoading,
      loadFileBaselineData,
      onFileBaselineSwitchChange,
      pathsSaving,
      protectedPaths,
      restoreAlert,
      restoringAlertId,
      toggleProtectedPath,
    ],
  );

  return (
    <FileBaselineProtectionContext.Provider value={value}>
      {children}
    </FileBaselineProtectionContext.Provider>
  );
}

export function FileBaselineProtectionSwitchRow() {
  const { t } = useTranslation();
  const { fileBaselineSettings, fileBaselineSwitchLoading, onFileBaselineSwitchChange } =
    useFileBaselineProtectionContext();

  return (
    <div className={styles.integrityConfigItem}>
      <span className={styles.skillScannerLabel}>
        {t("security.integrityProtection.fileBaselineProtection")}
      </span>
      <Switch
        checked={fileBaselineSettings?.enabled ?? false}
        loading={fileBaselineSwitchLoading}
        onChange={(checked) => {
          void onFileBaselineSwitchChange(checked);
        }}
      />
    </div>
  );
}

export { FileBaselineProtectionFileList } from "./FileBaselineProtectionFileList";

/** @deprecated Use FileBaselineProtectionFileList */
export function FileBaselineProtectionProtectedPaths() {
  return <FileBaselineProtectionFileList />;
}

export function FileBaselineProtectionAlertsCard({
  highlightAlertId,
}: {
  highlightAlertId?: string;
}) {
  const { t } = useTranslation();
  const {
    fileBaselineSettings,
    fileBaselineAlerts,
    restoringAlertId,
    acceptingAlertId,
    restoreAlert,
    acceptAlert,
  } = useFileBaselineProtectionContext();

  if (!fileBaselineSettings?.enabled) {
    return null;
  }

  return (
    <>
      {fileBaselineAlerts.length > 0 && (
        <div className={styles.fileBaselineAlertBanner}>
          {t("security.integrityProtection.fileBaselineAlertsTitle")}:{" "}
          {fileBaselineAlerts.length}
        </div>
      )}
      <Card className={styles.tableCard}>
        <div className={styles.sectionHeader}>
          <h3 className={styles.sectionTitle}>
            {t("security.integrityProtection.fileBaselineAlertsTitle")}
          </h3>
        </div>
        <Table
          rowKey="alert_id"
          dataSource={fileBaselineAlerts}
          pagination={false}
          size="small"
          rowClassName={(record) =>
            record.alert_id === highlightAlertId
              ? styles.fileBaselineAlertHighlightRow
              : ""
          }
          onRow={(record) => ({
            id: `file-baseline-alert-${record.alert_id}`,
          })}
          locale={{
            emptyText: t("security.integrityProtection.fileBaselineAlertsEmpty"),
          }}
          columns={[
            {
              title: t("security.integrityProtection.columns.file"),
              dataIndex: "path",
              key: "path",
            },
            {
              title: t("security.integrityProtection.columns.reason"),
              dataIndex: "provenance",
              key: "provenance",
            },
            {
              title: t("security.integrityProtection.columns.detail"),
              key: "detail",
              render: (_, record) =>
                `${record.approved_sha256.slice(0, 8)} → ${record.current_sha256.slice(0, 8)}`,
            },
            {
              title: t("security.integrityProtection.columns.actions"),
              key: "actions",
              render: (_, record) => (
                <Space>
                  <Button
                    size="small"
                    loading={restoringAlertId === record.alert_id}
                    onClick={() => {
                      void restoreAlert(record);
                    }}
                  >
                    {t("security.integrityProtection.restoreAction")}
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    loading={acceptingAlertId === record.alert_id}
                    onClick={() => {
                      void acceptAlert(record);
                    }}
                  >
                    {t("security.integrityProtection.acceptAction")}
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </>
  );
}

export { useFileBaselineProtectionContext };
