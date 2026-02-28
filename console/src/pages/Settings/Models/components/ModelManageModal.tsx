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
  PlusOutlined,
} from "@ant-design/icons";
import type {
  ProviderInfo,
  LocalModelResponse,
  DownloadTaskResponse,
  OllamaModelResponse,
  OllamaDownloadTaskResponse,
} from "../../../../api/types";
import api from "../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

const POLL_INTERVAL_MS = 3000;

interface ModelManageModalProps {
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

export function ModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: ModelManageModalProps) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  // --- Local provider state ---
  const [localModels, setLocalModels] = useState<LocalModelResponse[]>([]);
  const [loadingLocal, setLoadingLocal] = useState(false);
  const [activeTasks, setActiveTasks] = useState<DownloadTaskResponse[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Track task IDs we've already shown completion/failure messages for
  const notifiedRef = useRef<Set<string>>(new Set());

  // --- Ollama provider state ---
  const [ollamaModels, setOllamaModels] = useState<OllamaModelResponse[]>([]);
  const [loadingOllama, setLoadingOllama] = useState(false);
  const [ollamaTasks, setOllamaTasks] = useState<OllamaDownloadTaskResponse[]>(
    [],
  );
  const ollamaPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const ollamaNotifiedRef = useRef<Set<string>>(new Set());

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const stopOllamaPolling = useCallback(() => {
    if (ollamaPollRef.current) {
      clearInterval(ollamaPollRef.current);
      ollamaPollRef.current = null;
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

      // Notify for newly completed/failed/cancelled tasks
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

      // Stop polling when no active tasks remain
      if (active.length === 0) {
        stopPolling();
      }
    } catch {
      /* ignore polling errors */
    }
  }, [provider.id, t, onSaved, fetchLocalModels, stopPolling]);

  const startPolling = useCallback(() => {
    if (pollRef.current) return; // already polling
    pollRef.current = setInterval(pollDownloads, POLL_INTERVAL_MS);
  }, [pollDownloads]);

  // --- Ollama-specific fetch & poll functions ---

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

  // On open for local providers: fetch models and check for active downloads
  useEffect(() => {
    if (!open || !provider.is_local) return;

    fetchLocalModels();
    setAdding(false);
    form.resetFields();
    notifiedRef.current.clear();

    // Initial check
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
  }, [
    open,
    provider.is_local,
    provider.id,
    fetchLocalModels,
    form,
    startPolling,
    stopPolling,
  ]);

  // On open for Ollama provider: fetch models and check for active downloads
  useEffect(() => {
    if (!open || provider.id !== "ollama") return;

    fetchOllamaModels();
    setAdding(false);
    form.resetFields();
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
  }, [
    open,
    provider.id,
    fetchOllamaModels,
    form,
    startOllamaPolling,
    stopOllamaPolling,
  ]);

  // --- Remote provider logic ---

  // For custom providers ALL models are deletable.
  // For built-in providers only extra_models are deletable.
  const extraModelIds = new Set(
    provider.is_custom
      ? provider.models.map((m) => m.id)
      : (provider.extra_models || []).map((m) => m.id),
  );

  const handleAddModel = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const id = values.id.trim();
      const name = values.name?.trim() || id;
      await api.addModel(provider.id, { id, name });
      message.success(t("models.modelAdded", { name }));
      form.resetFields();
      setAdding(false);
      onSaved();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      const errMsg =
        error instanceof Error ? error.message : t("models.modelAddFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveModel = (modelId: string, modelName: string) => {
    Modal.confirm({
      title: t("models.removeModel"),
      content: t("models.removeModelConfirm", {
        name: modelName,
        provider: provider.name,
      }),
      okText: t("common.delete"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.removeModel(provider.id, modelId);
          message.success(t("models.modelRemoved", { name: modelName }));
          onSaved();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.modelRemoveFailed");
          message.error(errMsg);
        }
      },
    });
  };

  // --- Local provider: download & delete ---

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

  // --- Ollama provider: download & delete ---

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
          // Remove from active tasks immediately
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
          // Remove from active tasks immediately
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

  // --- Render: Ollama provider ---
  if (provider.id === "ollama") {
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
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => handleOllamaDelete(m)}
                  />
                </div>
              </div>
            ))
          )}
        </div>

        {/* Download form — always available */}
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

  // --- Render: local provider ---
  if (provider.is_local) {
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

        {/* Download form — always available */}
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

  // --- Remote provider ---
  return (
    <Modal
      title={t("models.manageModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={560}
      destroyOnHidden
    >
      {/* Model list */}
      <div className={styles.modelList}>
        {provider.models.length === 0 ? (
          <div className={styles.modelListEmpty}>{t("models.noModels")}</div>
        ) : (
          provider.models.map((m) => {
            const isDeletable = extraModelIds.has(m.id);
            return (
              <div key={m.id} className={styles.modelListItem}>
                <div className={styles.modelListItemInfo}>
                  <span className={styles.modelListItemName}>{m.name}</span>
                  <span className={styles.modelListItemId}>{m.id}</span>
                </div>
                <div className={styles.modelListItemActions}>
                  {isDeletable ? (
                    <>
                      <Tag
                        color="blue"
                        style={{ fontSize: 11, marginRight: 4 }}
                      >
                        {t("models.userAdded")}
                      </Tag>
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => handleRemoveModel(m.id, m.name)}
                      />
                    </>
                  ) : (
                    <Tag color="green" style={{ fontSize: 11 }}>
                      {t("models.builtin")}
                    </Tag>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Add model section */}
      {adding ? (
        <div className={styles.modelAddForm}>
          <Form form={form} layout="vertical" style={{ marginBottom: 0 }}>
            <Form.Item
              name="id"
              label={t("models.modelIdLabel")}
              rules={[{ required: true, message: t("models.modelIdLabel") }]}
              style={{ marginBottom: 12 }}
            >
              <Input placeholder={t("models.modelIdPlaceholder")} />
            </Form.Item>
            <Form.Item
              name="name"
              label={t("models.modelNameLabel")}
              style={{ marginBottom: 12 }}
            >
              <Input placeholder={t("models.modelNamePlaceholder")} />
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
                loading={saving}
                onClick={handleAddModel}
              >
                {t("models.addModel")}
              </Button>
            </div>
          </Form>
        </div>
      ) : (
        <Button
          type="dashed"
          block
          icon={<PlusOutlined />}
          onClick={() => setAdding(true)}
          style={{ marginTop: 12 }}
        >
          {t("models.addModel")}
        </Button>
      )}
    </Modal>
  );
}
