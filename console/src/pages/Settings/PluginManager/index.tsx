import { useState, useCallback, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Modal,
  Input,
  Form,
  Tag,
  Tooltip,
  Empty,
  Spin,
  Typography,
  Space,
  Table,
  Divider,
} from "antd";
import {
  Package,
  Plus,
  Trash2,
  CheckCircle,
  XCircle,
  Link,
  FolderOpen,
  FileArchive,
  X,
  Wrench,
  BrainCircuit,
  Zap,
  Terminal,
  LayoutDashboard,
} from "lucide-react";
import type { PluginType } from "@/api/modules/plugin";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchPlugins,
  installPlugin,
  uploadPlugin,
  uninstallPlugin,
} from "@/api/modules/plugin";
import type { PluginInfo } from "@/api/modules/plugin";
import { useRequest } from "ahooks";
import styles from "./index.module.less";

const { Text } = Typography;

// ── Plugin type display config ───────────────────────────────────────────────

const PLUGIN_TYPE_CONFIG: Record<
  PluginType,
  { label: string; color: string; icon: React.ReactNode }
> = {
  tool: {
    label: "Tool",
    color: "blue",
    icon: <Wrench size={11} />,
  },
  provider: {
    label: "Provider",
    color: "purple",
    icon: <BrainCircuit size={11} />,
  },
  hook: {
    label: "Hook",
    color: "orange",
    icon: <Zap size={11} />,
  },
  command: {
    label: "Command",
    color: "cyan",
    icon: <Terminal size={11} />,
  },
  frontend: {
    label: "Frontend",
    color: "green",
    icon: <LayoutDashboard size={11} />,
  },
  general: {
    label: "General",
    color: "default",
    icon: <Package size={11} />,
  },
};

function PluginTypeTag({ type }: { type: PluginType }) {
  const cfg = PLUGIN_TYPE_CONFIG[type] ?? PLUGIN_TYPE_CONFIG.general;
  return (
    <Tag
      color={cfg.color}
      icon={cfg.icon}
      style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
    >
      {cfg.label}
    </Tag>
  );
}

// ── Drag-and-drop folder reading ────────────────────────────────────────────

/** Recursively read a directory entry into flat {path, file} pairs. */
async function readDirEntry(
  entry: FileSystemDirectoryEntry,
): Promise<Array<{ path: string; file: File }>> {
  const result: Array<{ path: string; file: File }> = [];
  const reader = entry.createReader();

  const readBatch = (): Promise<FileSystemEntry[]> =>
    new Promise((resolve, reject) => reader.readEntries(resolve, reject));

  let batch: FileSystemEntry[];
  do {
    batch = await readBatch();
    for (const e of batch) {
      if (e.isFile) {
        const file = await new Promise<File>((resolve, reject) =>
          (e as FileSystemFileEntry).file(resolve, reject),
        );
        result.push({ path: e.fullPath.replace(/^\//, ""), file });
      } else if (e.isDirectory) {
        const sub = await readDirEntry(e as FileSystemDirectoryEntry);
        result.push(...sub);
      }
    }
  } while (batch.length > 0);

  return result;
}

// ── Types ───────────────────────────────────────────────────────────────────

type LocalSelection =
  | { kind: "zip"; name: string; file: File }
  | {
      kind: "folder";
      name: string;
      entries: Array<{ path: string; file: File }>;
    };

// ── Component ───────────────────────────────────────────────────────────────

export default function PluginManagerPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [installOpen, setInstallOpen] = useState(false);
  const [localInstalling, setLocalInstalling] = useState(false);
  const [urlInstalling, setUrlInstalling] = useState(false);
  const [uninstallingId, setUninstallingId] = useState<string | null>(null);
  const [localSel, setLocalSel] = useState<LocalSelection | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [form] = Form.useForm<{ source: string }>();

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Reset drag state if the user cancels the drag outside the window.
  useEffect(() => {
    const cancel = () => setDragOver(false);
    window.addEventListener("dragend", cancel);
    window.addEventListener("drop", cancel);
    return () => {
      window.removeEventListener("dragend", cancel);
      window.removeEventListener("drop", cancel);
    };
  }, []);

  const {
    data: plugins,
    loading,
    refresh,
  } = useRequest(fetchPlugins, {
    onError: () => message.error(t("pluginManager.loadFailed")),
  });

  const closeModal = useCallback(() => {
    if (localInstalling || urlInstalling) return;
    setInstallOpen(false);
    setLocalSel(null);
    setDragOver(false);
    form.resetFields();
  }, [localInstalling, urlInstalling, form]);

  // ── Click-to-browse (ZIP only via native input) ─────────────────────────

  const handleZipPicked = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) setLocalSel({ kind: "zip", name: file.name, file });
      e.target.value = "";
    },
    [],
  );

  // ── Drag-and-drop (folder or ZIP) ───────────────────────────────────────

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);

      const items = Array.from(e.dataTransfer.items);
      if (items.length === 0) return;

      const entry = items[0].webkitGetAsEntry();
      if (!entry) return;

      if (entry.isDirectory) {
        try {
          const entries = await readDirEntry(entry as FileSystemDirectoryEntry);
          setLocalSel({ kind: "folder", name: entry.name, entries });
        } catch {
          message.error(t("pluginManager.dropFailed"));
        }
      } else if (entry.isFile) {
        const file = e.dataTransfer.files[0];
        if (!file.name.endsWith(".zip")) {
          message.warning(t("pluginManager.zipOnly"));
          return;
        }
        setLocalSel({ kind: "zip", name: file.name, file });
      }
    },
    [message, t],
  );

  // ── Install: local ──────────────────────────────────────────────────────

  const handleInstallLocal = useCallback(async () => {
    if (!localSel) return;
    setLocalInstalling(true);
    try {
      let uploadFile: File;

      if (localSel.kind === "zip") {
        uploadFile = localSel.file;
      } else {
        const { default: JSZip } = await import("jszip");
        const zip = new JSZip();
        for (const { path, file } of localSel.entries) {
          zip.file(path, file);
        }
        const blob = await zip.generateAsync({ type: "blob" });
        uploadFile = new File([blob], `${localSel.name}.zip`, {
          type: "application/zip",
        });
      }

      const result = await uploadPlugin(uploadFile);
      message.success(`${t("pluginManager.installSuccess")}: ${result.name}`);
      setInstallOpen(false);
      setLocalSel(null);
      refresh();
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("pluginManager.installFailed");
      message.error(msg);
    } finally {
      setLocalInstalling(false);
    }
  }, [localSel, message, t, refresh]);

  // ── Install: URL ────────────────────────────────────────────────────────

  const handleInstallUrl = useCallback(async () => {
    let values: { source: string };
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const source = values.source.trim();
    setUrlInstalling(true);
    try {
      const result = await installPlugin(source);
      message.success(`${t("pluginManager.installSuccess")}: ${result.name}`);
      setInstallOpen(false);
      form.resetFields();
      refresh();
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("pluginManager.installFailed");
      message.error(msg);
    } finally {
      setUrlInstalling(false);
    }
  }, [form, message, t, refresh]);

  // ── Uninstall ───────────────────────────────────────────────────────────

  const handleUninstall = useCallback(
    (plugin: PluginInfo) => {
      Modal.confirm({
        title: t("pluginManager.confirmTitle"),
        content: t("pluginManager.uninstallConfirm", { name: plugin.name }),
        okType: "danger",
        okText: t("pluginManager.uninstall"),
        cancelText: t("common.cancel"),
        onOk: async () => {
          setUninstallingId(plugin.id);
          try {
            await uninstallPlugin(plugin.id);
            message.success(t("pluginManager.uninstallSuccess"));
            refresh();
          } catch (err) {
            const msg =
              err instanceof Error
                ? err.message
                : t("pluginManager.uninstallFailed");
            message.error(msg);
          } finally {
            setUninstallingId(null);
          }
        },
      });
    },
    [message, t, refresh],
  );

  // ── Table columns ───────────────────────────────────────────────────────

  const columns = [
    {
      title: t("pluginManager.title"),
      dataIndex: "name",
      key: "name",
      render: (name: string, record: PluginInfo) => (
        <Space direction="vertical" size={2}>
          <Space size={8}>
            <Package size={16} style={{ flexShrink: 0 }} />
            <Text strong>{name}</Text>
          </Space>
          {record.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: t("pluginManager.type"),
      dataIndex: "plugin_type",
      key: "plugin_type",
      width: 110,
      render: (type: PluginType) => <PluginTypeTag type={type ?? "general"} />,
    },
    {
      title: t("pluginManager.version"),
      dataIndex: "version",
      key: "version",
      width: 100,
      render: (v: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {v}
        </Text>
      ),
    },
    {
      title: t("pluginManager.author"),
      dataIndex: "author",
      key: "author",
      width: 140,
      render: (author: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {author || t("pluginManager.unknown")}
        </Text>
      ),
    },
    {
      title: "Status",
      dataIndex: "loaded",
      key: "loaded",
      width: 110,
      render: (loaded: boolean) =>
        loaded ? (
          <Tag
            icon={<CheckCircle size={12} />}
            color="success"
            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
          >
            {t("pluginManager.statusLoaded")}
          </Tag>
        ) : (
          <Tag
            icon={<XCircle size={12} />}
            color="default"
            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
          >
            {t("pluginManager.statusUnloaded")}
          </Tag>
        ),
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_: unknown, record: PluginInfo) => (
        <Tooltip title={t("pluginManager.uninstall")}>
          <Button
            type="text"
            danger
            size="small"
            icon={<Trash2 size={14} />}
            loading={uninstallingId === record.id}
            onClick={() => handleUninstall(record)}
          />
        </Tooltip>
      ),
    },
  ];

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.pluginManager")}
        extra={
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={() => setInstallOpen(true)}
          >
            {t("pluginManager.installBtn")}
          </Button>
        }
      />

      <div className={styles.content}>
        <Spin spinning={loading}>
          {!loading && (!plugins || plugins.length === 0) ? (
            <Empty
              image={<Package size={48} strokeWidth={1} />}
              description={t("pluginManager.noPlugins")}
              style={{ marginTop: 80 }}
            />
          ) : (
            <Table
              dataSource={plugins}
              columns={columns}
              rowKey="id"
              pagination={false}
              className={styles.table}
            />
          )}
        </Spin>
      </div>

      {/* Hidden ZIP file input — click-to-browse shortcut */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".zip"
        style={{ display: "none" }}
        onChange={handleZipPicked}
      />

      {/* Install modal */}
      <Modal
        open={installOpen}
        title={
          <Space>
            <Package size={18} />
            {t("pluginManager.installTitle")}
          </Space>
        }
        onCancel={closeModal}
        footer={null}
        destroyOnHidden
        centered
        width={480}
      >
        <div style={{ paddingTop: 16 }}>
          {/* Drop zone / selection display */}
          {localSel ? (
            <div className={styles.selectionCard}>
              {localSel.kind === "folder" ? (
                <FolderOpen size={18} />
              ) : (
                <FileArchive size={18} />
              )}
              <Text className={styles.selectionName}>{localSel.name}</Text>
              <Button
                type="text"
                size="small"
                icon={<X size={14} />}
                onClick={() => setLocalSel(null)}
              />
            </div>
          ) : (
            <div
              className={`${styles.dropZone} ${
                dragOver ? styles.dropZoneActive : ""
              }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <Package
                size={36}
                strokeWidth={1.2}
                className={styles.dropIcon}
              />
              <Text className={styles.dropPrimary}>
                {t("pluginManager.dropPrimary")}
              </Text>
              <Text type="secondary" className={styles.dropSecondary}>
                {t("pluginManager.dropSecondary")}
              </Text>
            </div>
          )}

          <Button
            type="primary"
            block
            style={{ marginTop: 12 }}
            disabled={!localSel}
            loading={localInstalling}
            onClick={handleInstallLocal}
          >
            {localInstalling
              ? t("pluginManager.installing")
              : t("pluginManager.installBtn")}
          </Button>

          <Divider style={{ margin: "20px 0 16px" }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("pluginManager.orFromUrl")}
            </Text>
          </Divider>

          <Form form={form} layout="vertical">
            <Form.Item
              name="source"
              style={{ marginBottom: 8 }}
              rules={[{ required: true, message: " " }]}
            >
              <Input
                prefix={
                  <Link
                    size={14}
                    style={{ color: "var(--ant-color-text-quaternary)" }}
                  />
                }
                placeholder={t("pluginManager.urlPlaceholder")}
                allowClear
                onPressEnter={handleInstallUrl}
              />
            </Form.Item>
            <Button block loading={urlInstalling} onClick={handleInstallUrl}>
              {urlInstalling
                ? t("pluginManager.installing")
                : t("pluginManager.installFromUrl")}
            </Button>
          </Form>

          <Text
            type="secondary"
            style={{ fontSize: 11, display: "block", marginTop: 14 }}
          >
            {t("pluginManager.restartHint")}
          </Text>
        </div>
      </Modal>
    </div>
  );
}
