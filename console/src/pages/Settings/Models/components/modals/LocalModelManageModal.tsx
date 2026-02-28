import { useState, useEffect, useCallback, useRef } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Select,
  Tag,
  message,
} from "@agentscope-ai/design";
import {
  CloseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import type {
  ProviderInfo,
  LocalModelResponse,
  DownloadTaskResponse,
} from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

const POLL_INTERVAL_MS = 3000;

interface LocalModelManageModalProps {
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

export function LocalModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: LocalModelManageModalProps) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const [form] = Form.useForm();
  const [localModels, setLocalModels] = useState<LocalModelResponse[]>([]);
  const [loadingLocal, setLoadingLocal] = useState(false);
  const [activeTasks, setActiveTasks] = useState<DownloadTaskResponse[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const notifiedRef = useRef<Set<string>>(new Set());

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const fetchLocalModels = useCallback(async () => {
    setLoadingLocal(true);
    try {
      const data = await api.listLocalModels(provider.id);
      setLocalModels(Array.isArray(data) ? data : []);
    } catch {
      setLocalModels([]);
    } finally {
      setLoadingLocal(false);
    }
  }, [provider.id]);

  const pollDownloads = useCallback(async () => {
    try {
      const tasks = await api.getDownloadStatus(provider.id);
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
        if (!notifiedRef.current.has(task.task_id)) {
          notifiedRef.current.add(task.task_id);
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
        fetchLocalModels();
      }

      setActiveTasks(active);

      if (active.length === 0) {
        stopPolling();
      }
    } catch {
      /* ignore polling errors */
    }
  }, [provider.id, t, onSaved, fetchLocalModels, stopPolling]);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(pollDownloads, POLL_INTERVAL_MS);
  }, [pollDownloads]);

  useEffect(() => {
    if (!open) return;

    fetchLocalModels();
    setAdding(false);
    form.resetFields();
    notifiedRef.current.clear();

    api
      .getDownloadStatus(provider.id)
      .then((tasks) => {
        const taskList = Array.isArray(tasks) ? tasks : [];
        const active = taskList.filter(
          (t) => t.status === "pending" || t.status === "downloading",
        );
        setActiveTasks(active);
        if (active.length > 0) {
          startPolling();
        }
      })
      .catch(() => {});

    return () => stopPolling();
  }, [open, provider.id, fetchLocalModels, form, startPolling, stopPolling]);

  const handleDownload = async () => {
    try {
      const values = await form.validateFields();
      const task = await api.downloadModel({
        repo_id: values.repo_id.trim(),
        filename: values.filename?.trim() || undefined,
        backend: provider.id,
        source: values.source || "huggingface",
      });
      setActiveTasks((prev) => [...prev, task]);
      setAdding(false);
      form.resetFields();
      startPolling();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      const errMsg =
        error instanceof Error ? error.message : t("models.downloadFailed");
      message.error(errMsg);
    }
  };

  const handleDeleteLocal = (model: LocalModelResponse) => {
    Modal.confirm({
      title: t("models.localDeleteModel"),
      content: t("models.localDeleteConfirm", { name: model.display_name }),
      okText: t("common.delete"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.deleteLocalModel(model.id);
          message.success(
            t("models.localModelDeleted", { name: model.display_name }),
          );
          onSaved();
          fetchLocalModels();
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

  const handleCancelDownload = (task: DownloadTaskResponse) => {
    Modal.confirm({
      title: t("models.localCancelDownload"),
      content: t("models.localCancelDownloadConfirm", { repo: task.repo_id }),
      okText: t("models.localCancelDownload"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.cancelDownload(task.task_id);
          message.success(t("models.localDownloadCancelled"));
          setActiveTasks((prev) =>
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
      footer={null}
      width={600}
      destroyOnHidden
    >
      {/* Active download statuses */}
      {activeTasks.map((task) => (
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
              ? t("models.downloadPending")
              : t("models.localDownloading", { repo: task.repo_id })}
          </span>
          <Button
            type="text"
            size="small"
            danger
            icon={<CloseOutlined />}
            onClick={() => handleCancelDownload(task)}
            style={{ marginLeft: "auto" }}
          />
        </div>
      ))}

      {/* Downloaded models list */}
      <div className={styles.modelList}>
        {loadingLocal ? (
          <div className={styles.modelListEmpty}>{t("common.loading")}</div>
        ) : localModels.length === 0 ? (
          <div className={styles.modelListEmpty}>
            {t("models.localNoModels")}
          </div>
        ) : (
          localModels.map((m) => (
            <div key={m.id} className={styles.modelListItem}>
              <div className={styles.modelListItemInfo}>
                <span className={styles.modelListItemName}>
                  {m.display_name}
                </span>
                <span className={styles.modelListItemId}>
                  {m.repo_id}/{m.filename} &middot;{" "}
                  {formatFileSize(m.file_size)}
                </span>
              </div>
              <div className={styles.modelListItemActions}>
                <Tag
                  color={m.source === "huggingface" ? "orange" : "blue"}
                  style={{ fontSize: 11, marginRight: 4 }}
                >
                  {m.source === "huggingface" ? "HF" : "MS"}
                </Tag>
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => handleDeleteLocal(m)}
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
              name="repo_id"
              label={t("models.localRepoId")}
              rules={[
                { required: true, message: t("models.localRepoIdRequired") },
              ]}
              style={{ marginBottom: 12 }}
            >
              <Input placeholder={t("models.localRepoIdPlaceholder")} />
            </Form.Item>
            <Form.Item
              name="filename"
              label={t("models.localFilename")}
              extra={t("models.localFilenameHint")}
              style={{ marginBottom: 12 }}
            >
              <Input placeholder={t("models.localFilenamePlaceholder")} />
            </Form.Item>
            <Form.Item
              name="source"
              label={t("models.localSource")}
              initialValue="huggingface"
              style={{ marginBottom: 12 }}
            >
              <Select
                options={[
                  { value: "huggingface", label: "Hugging Face" },
                  { value: "modelscope", label: "ModelScope" },
                ]}
              />
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
                onClick={handleDownload}
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
