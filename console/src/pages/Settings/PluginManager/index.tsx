import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Modal,
  Input,
  Form,
  Tabs,
  Upload,
  Tag,
  Tooltip,
  Empty,
  Spin,
  Typography,
  Space,
  Table,
} from "antd";
import type { UploadFile } from "antd";
import {
  Package,
  Plus,
  Trash2,
  CheckCircle,
  XCircle,
  Upload as UploadIcon,
  Link,
} from "lucide-react";
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

export default function PluginManagerPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [installOpen, setInstallOpen] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [uninstallingId, setUninstallingId] = useState<string | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [form] = Form.useForm<{ source: string }>();

  const {
    data: plugins,
    loading,
    refresh,
  } = useRequest(fetchPlugins, {
    onError: () => {
      message.error(t("pluginManager.loadFailed"));
    },
  });

  // ── Install handlers ───────────────────────────────────────────────

  const handleInstallUrl = useCallback(async () => {
    const values = await form.validateFields();
    const source = values.source.trim();
    setInstalling(true);
    try {
      const result = await installPlugin(source);
      message.success(
        `${t("pluginManager.installSuccess")}: ${result.name}`,
      );
      setInstallOpen(false);
      form.resetFields();
      refresh();
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : t("pluginManager.installFailed");
      message.error(msg);
    } finally {
      setInstalling(false);
    }
  }, [form, message, t, refresh]);

  const handleInstallZip = useCallback(async () => {
    if (fileList.length === 0) {
      message.warning(t("pluginManager.uploadLabel"));
      return;
    }
    const file = fileList[0].originFileObj as File;
    setInstalling(true);
    try {
      const result = await uploadPlugin(file);
      message.success(
        `${t("pluginManager.installSuccess")}: ${result.name}`,
      );
      setInstallOpen(false);
      setFileList([]);
      refresh();
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : t("pluginManager.installFailed");
      message.error(msg);
    } finally {
      setInstalling(false);
    }
  }, [fileList, message, t, refresh]);

  // ── Uninstall handler ──────────────────────────────────────────────

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
          } catch (err: unknown) {
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

  // ── Table columns ──────────────────────────────────────────────────

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

  // ── Render ─────────────────────────────────────────────────────────

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

      {/* Install modal */}
      <Modal
        open={installOpen}
        title={
          <Space>
            <Package size={18} />
            {t("pluginManager.installTitle")}
          </Space>
        }
        onCancel={() => {
          if (!installing) {
            setInstallOpen(false);
            form.resetFields();
            setFileList([]);
          }
        }}
        footer={null}
        destroyOnHidden
        centered
        width={520}
      >
        <Tabs
          defaultActiveKey="url"
          items={[
            {
              key: "url",
              label: (
                <Space size={6}>
                  <Link size={14} />
                  {t("pluginManager.tabUrl")}
                </Space>
              ),
              children: (
                <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
                  <Form.Item
                    name="source"
                    label={t("pluginManager.urlLabel")}
                    extra={t("pluginManager.urlHint")}
                    rules={[{ required: true, message: " " }]}
                  >
                    <Input
                      placeholder={t("pluginManager.urlPlaceholder")}
                      allowClear
                    />
                  </Form.Item>
                  <Form.Item style={{ marginBottom: 0 }}>
                    <Button
                      type="primary"
                      block
                      loading={installing}
                      onClick={handleInstallUrl}
                    >
                      {installing
                        ? t("pluginManager.installing")
                        : t("pluginManager.installBtn")}
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
            {
              key: "upload",
              label: (
                <Space size={6}>
                  <UploadIcon size={14} />
                  {t("pluginManager.tabUpload")}
                </Space>
              ),
              children: (
                <div style={{ marginTop: 16 }}>
                  <Upload.Dragger
                    accept=".zip"
                    maxCount={1}
                    fileList={fileList}
                    beforeUpload={() => false}
                    onChange={({ fileList: fl }) => setFileList(fl)}
                  >
                    <div className={styles.uploadArea}>
                      <UploadIcon size={32} strokeWidth={1.5} />
                      <Text style={{ marginTop: 8 }}>
                        {t("pluginManager.uploadLabel")}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {t("pluginManager.uploadHint")}
                      </Text>
                    </div>
                  </Upload.Dragger>
                  <Button
                    type="primary"
                    block
                    style={{ marginTop: 16 }}
                    loading={installing}
                    disabled={fileList.length === 0}
                    onClick={handleInstallZip}
                  >
                    {installing
                      ? t("pluginManager.installing")
                      : t("pluginManager.installBtn")}
                  </Button>
                </div>
              ),
            },
          ]}
        />
      </Modal>
    </div>
  );
}
