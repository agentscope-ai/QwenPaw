import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Button,
  Input,
  Table,
  Popconfirm,
  Tag,
  Switch,
  Alert,
} from "@agentscope-ai/design";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { Space } from "antd";
import {
  PlusCircleOutlined,
  DeleteOutlined,
  FolderOutlined,
  FileOutlined,
  LockOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import styles from "../index.module.less";

interface FileGuardSectionProps {
  onSave?: (handlers: {
    save: () => Promise<void>;
    reset: () => void;
    saving: boolean;
  }) => void;
  denyPathsActive?: boolean;
  denyPathsLoading?: boolean;
  denyPathsProtectedPaths?: string[];
  denyPathsPlatformSupported?: boolean;
  sandboxEnabled?: boolean;
  sandboxReason?: string | null;
  toggleDenyPaths?: (val: boolean) => void;
}

export function FileGuardSection({
  onSave,
  denyPathsActive = false,
  denyPathsLoading = false,
  denyPathsProtectedPaths = [],
  denyPathsPlatformSupported = false,
  sandboxEnabled = false,
  sandboxReason = null,
  toggleDenyPaths,
}: FileGuardSectionProps = {}) {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(true);
  const [allowPreviewOutsideWorkspace, setAllowPreviewOutsideWorkspace] =
    useState(false);
  const [paths, setPaths] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [newPath, setNewPath] = useState("");
  const { message } = useAppMessage();

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getFileGuard();
      setEnabled(data?.enabled ?? true);
      setAllowPreviewOutsideWorkspace(
        data?.allow_preview_outside_workspace ?? false,
      );
      setPaths(data?.paths ?? []);
    } catch {
      message.error(t("security.fileGuard.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleToggle = useCallback(
    async (checked: boolean) => {
      setEnabled(checked);
      try {
        await api.updateFileGuard({ enabled: checked });
        message.success(t("security.fileGuard.saveSuccess"));
      } catch {
        setEnabled(!checked);
        message.error(t("security.fileGuard.saveFailed"));
      }
    },
    [t],
  );

  const handlePreviewToggle = useCallback(
    async (checked: boolean) => {
      setAllowPreviewOutsideWorkspace(checked);
      try {
        await api.updateFileGuard({
          allow_preview_outside_workspace: checked,
        });
        message.success(t("security.fileGuard.saveSuccess"));
      } catch {
        setAllowPreviewOutsideWorkspace(!checked);
        message.error(t("security.fileGuard.saveFailed"));
      }
    },
    [t],
  );

  const handleAdd = useCallback(() => {
    const trimmed = newPath.trim();
    if (!trimmed) return;
    if (paths.includes(trimmed)) {
      message.warning(t("security.fileGuard.duplicate"));
      return;
    }
    setPaths((prev) => [...prev, trimmed]);
    setNewPath("");
  }, [newPath, paths, t]);

  const handleRemove = useCallback((path: string) => {
    setPaths((prev) => prev.filter((p) => p !== path));
  }, []);

  const handleSave = useCallback(async () => {
    try {
      setSaving(true);
      await api.updateFileGuard({ paths });
      message.success(t("security.fileGuard.saveSuccess"));
    } catch {
      message.error(t("security.fileGuard.saveFailed"));
    } finally {
      setSaving(false);
    }
  }, [paths, t]);

  const handleReset = useCallback(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    onSave?.({ save: handleSave, reset: handleReset, saving });
  }, [handleSave, handleReset, saving, onSave]);

  const columns = [
    {
      title: t("security.fileGuard.path"),
      dataIndex: "path",
      key: "path",
      render: (path: string) => {
        const isDir = path.endsWith("/") || path.endsWith("\\");
        return (
          <Space>
            {isDir ? (
              <FolderOutlined style={{ color: "#faad14" }} />
            ) : (
              <FileOutlined style={{ color: "#1890ff" }} />
            )}
            <code>{path}</code>
            {isDir && (
              <Tag color="orange">{t("security.fileGuard.directory")}</Tag>
            )}
          </Space>
        );
      },
    },
    {
      title: t("security.fileGuard.actions"),
      key: "actions",
      width: 80,
      render: (_: unknown, record: { path: string }) => (
        <Popconfirm
          title={t("security.fileGuard.removeConfirm")}
          onConfirm={() => handleRemove(record.path)}
          okText={t("common.delete")}
          cancelText={t("common.cancel")}
        >
          <Button type="text" danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ];

  const dataSource = paths.map((path) => ({ key: path, path }));

  return (
    <>
      <Card className={styles.formCard}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 16,
          }}
        >
          <span style={{ fontWeight: 500 }}>
            {t("security.fileGuard.enableLabel")}
          </span>
          <Switch checked={enabled} onChange={handleToggle} />
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 16,
          }}
        >
          <div>
            <span style={{ fontWeight: 500 }}>
              {t("security.fileGuard.allowPreviewOutsideWorkspace")}
            </span>
            <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>
              {t("security.fileGuard.allowPreviewOutsideWorkspaceDesc")}
            </div>
          </div>
          <Switch
            checked={allowPreviewOutsideWorkspace}
            onChange={handlePreviewToggle}
          />
        </div>

        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            placeholder={t("security.fileGuard.inputPlaceholder")}
            onPressEnter={handleAdd}
            allowClear
            disabled={!enabled}
          />
          <Button
            type="primary"
            icon={<PlusCircleOutlined />}
            onClick={handleAdd}
            disabled={!newPath.trim() || !enabled}
          >
            {t("security.fileGuard.add")}
          </Button>
        </Space.Compact>
      </Card>

      <Card className={styles.tableCard}>
        <Table
          columns={columns}
          dataSource={dataSource}
          loading={loading}
          pagination={false}
          size="middle"
          locale={{
            emptyText: t("security.fileGuard.empty"),
          }}
        />
      </Card>

      {denyPathsPlatformSupported &&
        sandboxEnabled &&
        sandboxReason === "unelevated" &&
        toggleDenyPaths && (
          <Card className={styles.formCard} style={{ marginTop: 16 }}>
            <div style={{ marginBottom: 12 }}>
              <h3 style={{ margin: 0, marginBottom: 4 }}>
                <LockOutlined style={{ marginRight: 6 }} />
                {t("security.denyPathsProtection")}
              </h3>
              <p style={{ margin: 0, fontSize: 13, color: "#666" }}>
                {t("security.denyPathsSandboxEnhancement")}
              </p>
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: denyPathsActive ? 12 : 0,
              }}
            >
              <span style={{ fontWeight: 500 }}>
                {t("security.denyPathsProtectionTooltip")}
              </span>
              <Switch
                checked={denyPathsActive}
                loading={denyPathsLoading}
                onChange={(val) => toggleDenyPaths(val)}
              />
            </div>
            {denyPathsActive && (
              <Alert
                type="info"
                showIcon
                message={t("security.denyPathsActiveMessage")}
                description={
                  <>
                    <p>{t("security.denyPathsActiveDescription")}</p>
                    <div
                      style={{
                        marginTop: 8,
                        maxHeight: 120,
                        overflow: "auto",
                      }}
                    >
                      {denyPathsProtectedPaths.map((p) => (
                        <Tag key={p} style={{ marginBottom: 4 }}>
                          {p}
                        </Tag>
                      ))}
                    </div>
                  </>
                }
              />
            )}
          </Card>
        )}
    </>
  );
}
