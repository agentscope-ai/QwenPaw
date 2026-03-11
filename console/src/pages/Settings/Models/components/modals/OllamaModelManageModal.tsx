import { useState, useEffect, useCallback, useRef } from "react";
import { Button, Form, Input, Modal, message } from "@agentscope-ai/design";
import {
  CloseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  LoadingOutlined,
  ApiOutlined,
} from "@ant-design/icons";
import type {
  ProviderInfo,
  OllamaModelResponse,
  OllamaDownloadTaskResponse,
} from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

const POLL_INTERVAL_MS = 3000;

interface OllamaModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function OllamaModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: OllamaModelManageModalProps) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [ollamaModels, setOllamaModels] = useState<OllamaModelResponse[]>([]);
  const [loadingOllama, setLoadingOllama] = useState(false);
  const [ollamaTasks, setOllamaTasks] = useState<OllamaDownloadTaskResponse[]>(
    [],
  );
  const ollamaPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const ollamaNotifiedRef = useRef<Set<string>>(new Set());

  const stopOllamaPolling = useCallback(() => {
    if (ollamaPollRef.current) {
      clearInterval(ollamaPollRef.current);
      ollamaPollRef.current = null;
    }
  }, []);

  const fetchOllamaModels = useCallback(async () => {
    setLoadingOllama(true);
    try {
      const data = await api.listOllamaModels();
      setOllamaModels(Array.isArray(data) ? data : []);
    } catch {
      setOllamaModels([]);
    } finally {
      setLoadingOllama(false);
    }
  }, []);

  const pollOllamaDownloads = useCallback(async () => {
    try {
      const tasksStatus = await api.getOllamaDownloadStatus();
      const tasks = Array.isArray(tasksStatus) ? tasksStatus : [];
      const active = tasks.filter(
        (t) => t.status === "pending" || t.status === "downloading",
      );
      const terminal = tasks.filter(
        (t) =>
          t.status === "completed" ||
          t.status === "failed" ||
          t.status === "cancelled",
      );

      let needsRefresh = false;
      for (const task of terminal) {
        if (!ollamaNotifiedRef.current.has(task.task_id)) {
          ollamaNotifiedRef.current.add(task.task_id);
          if (task.status === "completed") {
            message.success(t("models.localDownloadSuccess"));
            needsRefresh = true;
          } else if (task.status === "cancelled") {
            message.info(t("models.localDownloadCancelled"));
          } else {
            message.error(task.error || t("models.localDownloadFailed"));
          }
        }
      }

      if (needsRefresh) {
        onSaved();
        fetchOllamaModels();
      }

      setOllamaTasks(active);

      if (active.length === 0) {
        stopOllamaPolling();
      }
    } catch {
      /* ignore polling errors */
    }
  }, [t, onSaved, fetchOllamaModels, stopOllamaPolling]);

  const startOllamaPolling = useCallback(() => {
    if (ollamaPollRef.current) return;
    ollamaPollRef.current = setInterval(pollOllamaDownloads, POLL_INTERVAL_MS);
  }, [pollOllamaDownloads]);

  useEffect(() => {
    if (!open) return;

    fetchOllamaModels();
    ollamaNotifiedRef.current.clear();

    api
      .getOllamaDownloadStatus()
      .then((tasks) => {
        const active = tasks.filter(
          (t) => t.status === "pending" || t.status === "downloading",
        );
        setOllamaTasks(active);
        if (active.length > 0) {
          startOllamaPolling();
        }
      })
      .catch(() => {});

    return () => stopOllamaPolling();
  }, [open, fetchOllamaModels, form, startOllamaPolling, stopOllamaPolling]);

  const handleOllamaDownload = async () => {
    try {
      const values = await form.validateFields();
      const task = await api.downloadOllamaModel({ name: values.name.trim() });
      setOllamaTasks((prev) => [...prev, task]);
      setAdding(false);
      form.resetFields();
      startOllamaPolling();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      const errMsg =
        error instanceof Error ? error.message : t("models.downloadFailed");
      message.error(errMsg);
    }
  };

  const handleOllamaDelete = (model: OllamaModelResponse) => {
    Modal.confirm({
      title: t("models.localDeleteModel"),
      content: t("models.localDeleteConfirm", { name: model.name }),
      okText: t("common.delete"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.deleteOllamaModel(model.name);
          message.success(t("models.localModelDeleted", { name: model.name }));
          onSaved();
          fetchOllamaModels();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.localDeleteFailed");
          message.error(errMsg);
        }
      },
    });
  };

  const handleCancelOllamaDownload = (task: OllamaDownloadTaskResponse) => {
    Modal.confirm({
      title: t("models.localCancelDownload"),
      content: t("models.localCancelDownloadConfirm", { repo: task.name }),
      okText: t("models.localCancelDownload"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.cancelOllamaDownload(task.task_id);
          message.success(t("models.localDownloadCancelled"));
          setOllamaTasks((prev) =>
            prev.filter((t) => t.task_id !== task.task_id),
          );
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.localCancelDownloadFailed");
          message.error(errMsg);
        }
      },
    });
  };

  const handleTest = async (modelName: string) => {
    setTestingModelId(modelName);
    try {
      const result = await api.testModelConnection(provider.id, {
        model_id: modelName,
      });
      if (result.success) {
        message.success(result.message || t("models.testConnectionSuccess"));
        // Refresh model list on successful test
        fetchOllamaModels();
      } else {
        message.warning(result.message || t("models.testConnectionFailed"));
      }
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.testConnectionError");
      message.error(errMsg);
    } finally {
      setTestingModelId(null);
    }
  };

  const handleClose = () => {
    setAdding(false);
    form.resetFields();
    onClose();
  };

  return (
    <Modal
      title={t("models.localModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={
        <div className={styles.modalFooter}>
          <div className={styles.modalFooterRight}>
            <Button onClick={handleClose}>{t("models.cancel")}</Button>
          </div>
        </div>
      }
      width={600}
      destroyOnHidden
    >
      {/* Active download statuses */}
      {ollamaTasks.map((task) => (
        <div
          key={task.task_id}
          style={{
            padding: "12px 16px",
            marginBottom: 8,
            background: "#f6f8fa",
            borderRadius: 8,
            border: "1px solid #e8e8e8",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <LoadingOutlined spin style={{ fontSize: 16, color: "#615CED" }} />
          <span style={{ color: "#333", fontSize: 13, flex: 1 }}>
            {task.status === "pending"
              ? t("models.localDownloadPending")
              : t("models.localDownloading", { repo: task.name })}
          </span>
          <Button
            type="text"
            size="small"
            danger
            icon={<CloseOutlined />}
            onClick={() => handleCancelOllamaDownload(task)}
            style={{ marginLeft: "auto" }}
          />
        </div>
      ))}

      {/* Downloaded models list */}
      <div className={styles.modelList}>
        {loadingOllama ? (
          <div className={styles.modelListEmpty}>{t("common.loading")}</div>
        ) : ollamaModels.length === 0 ? (
          <div className={styles.modelListEmpty}>
            {t("models.localNoModels")}
          </div>
        ) : (
          ollamaModels.map((m) => (
            <div key={m.name} className={styles.modelListItem}>
              <div className={styles.modelListItemInfo}>
                <span className={styles.modelListItemName}>{m.name}</span>
              </div>
              <div className={styles.modelListItemActions}>
                <span
                  className={styles.modelListItemId}
                  style={{ marginRight: 8 }}
                >
                  {formatFileSize(m.size)}
                </span>
                <Button
                  type="text"
                  size="small"
                  icon={<ApiOutlined />}
                  onClick={() => handleTest(m.name)}
                  loading={testingModelId === m.name}
                  style={{ marginRight: 4 }}
                >
                  {t("models.testConnection")}
                </Button>
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => handleOllamaDelete(m)}
                />
              </div>
            </div>
          ))
        )}
      </div>

      {/* Download form */}
      {adding ? (
        <div className={styles.modelAddForm}>
          <Form form={form} layout="vertical" style={{ marginBottom: 0 }}>
            <Form.Item
              name="name"
              label={t("models.modelNameLabel")}
              rules={[
                { required: true, message: t("models.modelNameRequired") },
              ]}
              style={{ marginBottom: 12 }}
            >
              <Input placeholder={t("models.ollamaModelNamePlaceholder")} />
            </Form.Item>
            <div
              style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}
            >
              <Button
                size="small"
                onClick={() => {
                  setAdding(false);
                  form.resetFields();
                }}
              >
                {t("models.cancel")}
              </Button>
              <Button
                type="primary"
                size="small"
                onClick={handleOllamaDownload}
                icon={<DownloadOutlined />}
              >
                {t("models.localDownloadModel")}
              </Button>
            </div>
          </Form>
        </div>
      ) : (
        <Button
          type="dashed"
          block
          icon={<DownloadOutlined />}
          onClick={() => setAdding(true)}
          style={{ marginTop: 12 }}
        >
          {t("models.localDownloadModel")}
        </Button>
      )}
    </Modal>
  );
}
