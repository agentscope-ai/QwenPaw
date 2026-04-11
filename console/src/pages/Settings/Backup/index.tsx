import { useState, useEffect, useCallback, useRef } from "react";
import {
  Form,
  Switch,
  Button,
  Card,
  Select,
  Table,
  InputNumber,
  Checkbox,
  Tag,
} from "@agentscope-ai/design";
import {
  CloudUploadOutlined,
  DownloadOutlined,
  ReloadOutlined,
  HistoryOutlined,
  SettingOutlined,
  SwapOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PageHeader } from "@/components/PageHeader";
import api from "../../../api";
import type { BackupEntry } from "../../../api/modules/backup";
import { useAgentStore } from "../../../stores/agentStore";
import styles from "./index.module.less";

const ASSET_TYPES = [
  { label: "Preferences", value: "preferences" },
  { label: "Memories", value: "memories" },
  { label: "Skills", value: "skills" },
  { label: "Tools", value: "tools" },
];

const CONFLICT_STRATEGIES = [
  { label: "Skip existing", value: "skip" },
  { label: "Overwrite all", value: "overwrite" },
  { label: "Rename conflicts", value: "rename" },
];

const SCHEDULE_PRESETS = [
  { value: "0 2 * * *" },
  { value: "0 6 * * *" },
  { value: "0 0 * * *" },
  { value: "0 */12 * * *" },
  { value: "0 2 * * 1" },
  { value: "0 */6 * * *" },
];

function BackupPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [configForm] = Form.useForm();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { selectedAgent, agents } = useAgentStore();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [backups, setBackups] = useState<BackupEntry[]>([]);
  const [backupsLoading, setBackupsLoading] = useState(false);
  const [activeSection, setActiveSection] = useState<
    "config" | "history" | "transfer"
  >("config");

  // Export state
  const [exportTypes, setExportTypes] = useState<string[]>([
    "preferences",
    "memories",
    "skills",
    "tools",
  ]);
  const [exportAgents, setExportAgents] = useState<string[]>([selectedAgent]);
  const [exporting, setExporting] = useState(false);

  // Import state
  const [importFile, setImportFile] = useState<string>("");
  const [importStrategy, setImportStrategy] = useState("skip");
  const [importTypes, setImportTypes] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);

  // Restore state
  const [restoring, setRestoring] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const config = await api.getConfig();
      configForm.setFieldsValue(config);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load config");
    } finally {
      setLoading(false);
    }
  }, [configForm]);

  const fetchBackups = useCallback(async () => {
    try {
      setBackupsLoading(true);
      const res = await api.listBackups();
      setBackups(res.backups || []);
    } catch {
      // silently fail
    } finally {
      setBackupsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
    fetchBackups();
  }, [fetchConfig, fetchBackups]);

  const handleSaveConfig = useCallback(async () => {
    try {
      setSaving(true);
      const values = await configForm.validateFields();
      await api.updateConfig(values);
      message.success(t("backup.configSaved", "Configuration saved"));
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) return;
      message.error(
        err instanceof Error
          ? err.message
          : t("backup.configSaveFailed", "Save failed"),
      );
    } finally {
      setSaving(false);
    }
  }, [configForm, t, message]);

  const handleExport = useCallback(async () => {
    if (exportTypes.length === 0) {
      message.warning(
        t("backup.selectTypes", "Select at least one asset type"),
      );
      return;
    }
    if (exportAgents.length === 0) {
      message.warning(t("backup.selectAgent", "Select at least one agent"));
      return;
    }
    try {
      setExporting(true);
      const res = await api.exportAssets({ types: exportTypes });
      message.success(
        t("backup.exportSuccess", "Exported {{count}} assets", {
          count: res.asset_count,
        }),
      );

      // Trigger browser download
      if (res.download_url) {
        const { getApiUrl, getApiToken } = await import("../../../api/config");
        const url = getApiUrl(res.download_url);
        const token = getApiToken();
        const link = document.createElement("a");
        link.href = token ? `${url}&token=${token}` : url;
        link.download = res.filename || "backup.zip";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }
    } catch (err) {
      message.error(
        err instanceof Error
          ? err.message
          : t("backup.exportFailed", "Export failed"),
      );
    } finally {
      setExporting(false);
    }
  }, [exportTypes, exportAgents, t, message]);

  const handleImport = useCallback(async () => {
    if (!importFile.trim()) {
      message.warning(t("backup.selectFile", "Please select a file to import"));
      return;
    }
    try {
      setImporting(true);
      const res = await api.importAssets({
        zip_path: importFile.trim(),
        strategy: importStrategy,
        types: importTypes.length > 0 ? importTypes : undefined,
      });
      message.success(
        t("backup.importSuccess", "Imported {{count}} assets", {
          count: res.imported.length,
        }),
      );
      setImportFile("");
      fetchBackups();
    } catch (err) {
      message.error(
        err instanceof Error
          ? err.message
          : t("backup.importFailed", "Import failed"),
      );
    } finally {
      setImporting(false);
    }
  }, [importFile, importStrategy, importTypes, t, message, fetchBackups]);

  const handleRestore = useCallback(
    async (backupPath: string) => {
      try {
        setRestoring(backupPath);
        const filename = backupPath.split("/").pop() || backupPath;
        const res = await api.restore({
          backup_name: filename,
          strategy: "overwrite",
        });
        message.success(
          t("backup.restoreSuccess", "Restored {{count}} assets", {
            count: res.imported.length,
          }),
        );
      } catch (err) {
        message.error(
          err instanceof Error
            ? err.message
            : t("backup.restoreFailed", "Restore failed"),
        );
      } finally {
        setRestoring(null);
      }
    },
    [t, message],
  );

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  const formatTimestamp = (ts: string) => {
    // ts format: YYYYMMDD-HHmmss
    if (ts.length === 15 && ts[8] === "-") {
      return `${ts.slice(0, 4)}-${ts.slice(4, 6)}-${ts.slice(6, 8)} ${ts.slice(
        9,
        11,
      )}:${ts.slice(11, 13)}:${ts.slice(13, 15)}`;
    }
    return ts;
  };

  const backupColumns = [
    {
      title: t("backup.timestamp", "Time"),
      dataIndex: "timestamp",
      key: "timestamp",
      width: 180,
      render: (val: string) => (
        <span className={styles.monoText}>{formatTimestamp(val)}</span>
      ),
    },
    {
      title: t("backup.size", "Size"),
      dataIndex: "size_bytes",
      key: "size_bytes",
      width: 100,
      render: (val: number) => <Tag color="default">{formatBytes(val)}</Tag>,
    },
    {
      title: t("backup.file", "File"),
      dataIndex: "backup_path",
      key: "backup_path",
      ellipsis: true,
      render: (val: string) => (
        <span className={styles.fileName}>{val.split("/").pop() || val}</span>
      ),
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_: unknown, record: BackupEntry) => (
        <Button
          type="primary"
          size="small"
          ghost
          loading={restoring === record.backup_path}
          onClick={() => handleRestore(record.backup_path)}
        >
          {t("backup.restore", "Restore")}
        </Button>
      ),
    },
  ];

  const sectionTabs = [
    {
      key: "config",
      icon: <SettingOutlined />,
      label: t("backup.configTab", "Auto Backup"),
    },
    {
      key: "history",
      icon: <HistoryOutlined />,
      label: t("backup.historyTab", "History"),
    },
    {
      key: "transfer",
      icon: <SwapOutlined />,
      label: t("backup.transferTab", "Export / Import"),
    },
  ];

  if (loading) {
    return (
      <div className={styles.backupPage}>
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.backupPage}>
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="small" onClick={fetchConfig} style={{ marginTop: 12 }}>
            {t("environments.retry", "Retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.backupPage}>
      <PageHeader
        parent={t("nav.settings", "Settings")}
        current={t("nav.backup", "Backup")}
      />

      <div className={styles.tabBar}>
        {sectionTabs.map((tab) => (
          <button
            key={tab.key}
            className={`${styles.tabItem} ${
              activeSection === tab.key ? styles.tabItemActive : ""
            }`}
            onClick={() => setActiveSection(tab.key as typeof activeSection)}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      <div className={styles.content}>
        {activeSection === "config" && (
          <div className={styles.section}>
            <Card className={styles.card}>
              <Form form={configForm} layout="vertical" className={styles.form}>
                <div className={styles.switchRow}>
                  <div className={styles.switchInfo}>
                    <span className={styles.switchLabel}>
                      {t("backup.enabled", "Automatic Backup")}
                    </span>
                    <span className={styles.switchDesc}>
                      {t(
                        "backup.enabledDesc",
                        "Automatically back up your workspace on a schedule",
                      )}
                    </span>
                  </div>
                  <Form.Item name="enabled" valuePropName="checked" noStyle>
                    <Switch />
                  </Form.Item>
                </div>

                <div className={styles.configGrid}>
                  <Form.Item
                    label={t("backup.schedule", "Backup Frequency")}
                    name="schedule"
                    tooltip={t(
                      "backup.scheduleTooltip",
                      "How often backups run in the background",
                    )}
                  >
                    <Select
                      options={SCHEDULE_PRESETS.map((p) => ({
                        label: t(`backup.schedulePreset.${p.value}`, p.value),
                        value: p.value,
                      }))}
                      style={{ width: "100%" }}
                    />
                  </Form.Item>
                  <Form.Item
                    label={t("backup.retentionDays", "Keep backups for")}
                    name="retention_days"
                    tooltip={t(
                      "backup.retentionDaysTooltip",
                      "Backups older than this are automatically deleted",
                    )}
                  >
                    <InputNumber
                      min={1}
                      max={365}
                      style={{ width: "100%" }}
                      addonAfter={t("backup.days", "days")}
                    />
                  </Form.Item>
                  <Form.Item
                    label={t("backup.maxBackups", "Maximum backups")}
                    name="max_backups"
                    tooltip={t(
                      "backup.maxBackupsTooltip",
                      "Oldest backups are removed when this limit is reached",
                    )}
                  >
                    <InputNumber
                      min={1}
                      max={100}
                      style={{ width: "100%" }}
                      addonAfter={t("backup.copies", "copies")}
                    />
                  </Form.Item>
                </div>
              </Form>
            </Card>

            <div className={styles.footerButtons}>
              <Button onClick={fetchConfig} disabled={saving}>
                {t("common.reset", "Reset")}
              </Button>
              <Button
                type="primary"
                onClick={handleSaveConfig}
                loading={saving}
              >
                {t("common.save", "Save")}
              </Button>
            </div>
          </div>
        )}

        {activeSection === "history" && (
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionHint}>
                {t("backup.historyHint", "{{count}} backup(s) available", {
                  count: backups.length,
                })}
              </span>
              <Button
                icon={<ReloadOutlined />}
                onClick={fetchBackups}
                loading={backupsLoading}
                size="small"
              >
                {t("backup.refresh", "Refresh")}
              </Button>
            </div>
            <Card className={styles.card}>
              <Table
                dataSource={backups}
                columns={backupColumns}
                rowKey="backup_path"
                loading={backupsLoading}
                size="small"
                pagination={false}
                locale={{
                  emptyText: t(
                    "backup.noBackups",
                    "No backups yet. Enable automatic backup or export manually.",
                  ),
                }}
              />
            </Card>
          </div>
        )}

        {activeSection === "transfer" && (
          <div className={styles.section}>
            <div className={styles.transferGrid}>
              {/* Export */}
              <Card className={styles.transferCard}>
                <div className={styles.transferHeader}>
                  <DownloadOutlined className={styles.transferIcon} />
                  <div>
                    <h3 className={styles.transferTitle}>
                      {t("backup.export", "Export")}
                    </h3>
                    <p className={styles.transferDesc}>
                      {t(
                        "backup.exportDesc",
                        "Package your workspace assets into a portable ZIP file",
                      )}
                    </p>
                  </div>
                </div>

                <div className={styles.agentTip}>
                  <InfoCircleOutlined className={styles.tipIcon} />
                  <span>
                    {t(
                      "backup.currentAgentTip",
                      "Current agent: {{agent}}. Select which agents to export below.",
                      { agent: selectedAgent },
                    )}
                  </span>
                </div>

                <div className={styles.assetPicker}>
                  <span className={styles.pickerLabel}>
                    {t("backup.agentToExport", "Agents to export")}
                  </span>
                  <div style={{ marginBottom: 8 }}>
                    <Checkbox
                      checked={
                        exportAgents.length === agents.length &&
                        agents.length > 0
                      }
                      indeterminate={
                        exportAgents.length > 0 &&
                        exportAgents.length < agents.length
                      }
                      onChange={(e) => {
                        if (e.target.checked) {
                          setExportAgents(agents.map((a) => a.id));
                        } else {
                          setExportAgents([]);
                        }
                      }}
                    >
                      {t("backup.allAgents", "All agents")}
                    </Checkbox>
                  </div>
                  <Checkbox.Group
                    value={exportAgents}
                    onChange={(vals) => setExportAgents(vals as string[])}
                    className={styles.assetCheckboxes}
                  >
                    {agents.map((a) => (
                      <Checkbox
                        key={a.id}
                        value={a.id}
                        className={styles.assetCheckbox}
                      >
                        {a.name || a.id}
                        {a.id === selectedAgent && (
                          <Tag
                            color="orange"
                            style={{ marginLeft: 4, fontSize: 11 }}
                          >
                            {t("backup.current", "current")}
                          </Tag>
                        )}
                      </Checkbox>
                    ))}
                  </Checkbox.Group>
                </div>

                <div className={styles.assetPicker}>
                  <span className={styles.pickerLabel}>
                    {t("backup.whatToExport", "What to export")}
                  </span>
                  <Checkbox.Group
                    value={exportTypes}
                    onChange={(vals) => setExportTypes(vals as string[])}
                    className={styles.assetCheckboxes}
                  >
                    {ASSET_TYPES.map((at) => (
                      <Checkbox
                        key={at.value}
                        value={at.value}
                        className={styles.assetCheckbox}
                      >
                        {t(`backup.assetType.${at.value}`, at.label)}
                      </Checkbox>
                    ))}
                  </Checkbox.Group>
                </div>
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  onClick={handleExport}
                  loading={exporting}
                  block
                  size="large"
                  className={styles.actionBtn}
                >
                  {t("backup.exportBtn", "Export Assets")}
                </Button>
              </Card>

              {/* Import */}
              <Card className={styles.transferCard}>
                <div className={styles.transferHeader}>
                  <CloudUploadOutlined className={styles.transferIcon} />
                  <div>
                    <h3 className={styles.transferTitle}>
                      {t("backup.import", "Import")}
                    </h3>
                    <p className={styles.transferDesc}>
                      {t(
                        "backup.importDesc",
                        "Restore assets from a previously exported ZIP file",
                      )}
                    </p>
                  </div>
                </div>

                <div
                  className={styles.uploadArea}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <CloudUploadOutlined className={styles.uploadIcon} />
                  <span className={styles.uploadText}>
                    {importFile
                      ? importFile.split("/").pop()
                      : t("backup.dropOrBrowse", "Click to select a .zip file")}
                  </span>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".zip"
                    style={{ display: "none" }}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) setImportFile(file.name);
                    }}
                  />
                </div>

                <div className={styles.importOptions}>
                  <div className={styles.optionRow}>
                    <span className={styles.optionLabel}>
                      {t("backup.conflictStrategy", "If conflicts")}
                    </span>
                    <Select
                      value={importStrategy}
                      onChange={setImportStrategy}
                      options={CONFLICT_STRATEGIES.map((s) => ({
                        label: t(`backup.strategy.${s.value}`, s.label),
                        value: s.value,
                      }))}
                      size="small"
                      style={{ width: 160 }}
                    />
                  </div>
                  <div className={styles.optionRow}>
                    <span className={styles.optionLabel}>
                      {t("backup.filterTypes", "Import only")}
                    </span>
                    <Checkbox.Group
                      options={ASSET_TYPES.map((at) => ({
                        label: t(`backup.assetType.${at.value}`, at.label),
                        value: at.value,
                      }))}
                      value={importTypes}
                      onChange={(vals) => setImportTypes(vals as string[])}
                      className={styles.inlineCheckboxes}
                    />
                  </div>
                </div>

                <Button
                  type="primary"
                  icon={<CloudUploadOutlined />}
                  onClick={handleImport}
                  loading={importing}
                  disabled={!importFile}
                  block
                  size="large"
                  className={styles.actionBtn}
                >
                  {t("backup.importBtn", "Import Assets")}
                </Button>
              </Card>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default BackupPage;
