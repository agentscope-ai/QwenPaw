import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import type { KeyboardEvent, ReactNode, UIEvent } from "react";
import { Button, Form, Input, Modal, Tag } from "@agentscope-ai/design";
import {
  DeleteOutlined,
  PlusOutlined,
  ApiOutlined,
  SyncOutlined,
  EyeOutlined,
  SettingOutlined,
  DownOutlined,
} from "@ant-design/icons";
import type { ProviderInfo, ModelInfo } from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useTheme } from "../../../../../contexts/ThemeContext";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import {
  getLocalizedTestConnectionMessage,
  getTestConnectionFailureDetail,
} from "./testConnectionMessage";
import styles from "../../index.module.less";

function highlightJson(text: string): ReactNode[] {
  const tokens: ReactNode[] = [];
  const pattern =
    /("(?:\\.|[^"\\])*")(\s*:)?|\btrue\b|\bfalse\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],:]/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    const [token, stringToken, keySuffix] = match;

    if (match.index > lastIndex) {
      tokens.push(text.slice(lastIndex, match.index));
    }

    if (stringToken) {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={
            keySuffix ? styles.jsonEditorTokenKey : styles.jsonEditorTokenString
          }
        >
          {token}
        </span>,
      );
    } else if (token === "true" || token === "false") {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={styles.jsonEditorTokenBoolean}
        >
          {token}
        </span>,
      );
    } else if (token === "null") {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={styles.jsonEditorTokenNull}
        >
          {token}
        </span>,
      );
    } else if (/^-?\d/.test(token)) {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={styles.jsonEditorTokenNumber}
        >
          {token}
        </span>,
      );
    } else {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={styles.jsonEditorTokenPunctuation}
        >
          {token}
        </span>,
      );
    }

    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) {
    tokens.push(text.slice(lastIndex));
  }

  return tokens;
}

function MiniJsonEditor({
  value = "",
  onChange,
  placeholder,
}: {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
}) {
  const indentUnit = "  ";
  const highlightRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleScroll = (event: UIEvent<HTMLTextAreaElement>) => {
    if (!highlightRef.current) return;
    highlightRef.current.scrollTop = event.currentTarget.scrollTop;
    highlightRef.current.scrollLeft = event.currentTarget.scrollLeft;
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Tab") return;
    event.preventDefault();

    const textarea = event.currentTarget;
    const selectionStart = textarea.selectionStart;
    const selectionEnd = textarea.selectionEnd;

    if (event.shiftKey) {
      const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
      const linePrefix = value.slice(lineStart, selectionStart);
      if (!linePrefix.endsWith(indentUnit)) return;
      const nextValue =
        value.slice(0, selectionStart - indentUnit.length) +
        value.slice(selectionStart);
      onChange?.(nextValue);
      requestAnimationFrame(() => {
        textareaRef.current?.setSelectionRange(
          selectionStart - indentUnit.length,
          selectionStart - indentUnit.length,
        );
      });
      return;
    }

    const nextValue =
      value.slice(0, selectionStart) + indentUnit + value.slice(selectionEnd);
    onChange?.(nextValue);
    requestAnimationFrame(() => {
      const nextCursor = selectionStart + indentUnit.length;
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  };

  return (
    <div className={styles.jsonEditorContainer} style={{ marginTop: 8 }}>
      <div
        ref={highlightRef}
        aria-hidden="true"
        className={styles.jsonEditorHighlight}
        style={{ minHeight: 100 }}
      >
        {value ? highlightJson(value) : placeholder}
        {!value && <span>{"\n"}</span>}
      </div>
      <textarea
        ref={textareaRef}
        rows={5}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
        onKeyDown={handleKeyDown}
        onScroll={handleScroll}
        placeholder={placeholder}
        spellCheck={false}
        className={styles.jsonEditorTextarea}
        style={{ minHeight: 100 }}
      />
    </div>
  );
}

function ModelConfigEditor({
  providerId,
  model,
  onSaved,
  onClose,
  isDark,
}: {
  providerId: string;
  model: ModelInfo;
  onSaved: () => void | Promise<void>;
  onClose: () => void;
  isDark: boolean;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);

  const initialText = useMemo(
    () =>
      model.generate_kwargs && Object.keys(model.generate_kwargs).length > 0
        ? JSON.stringify(model.generate_kwargs, null, 2)
        : "",
    [model.generate_kwargs],
  );

  const [text, setText] = useState(initialText);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setText(initialText);
    setDirty(false);
  }, [initialText]);

  const handleChange = useCallback(
    (val: string) => {
      setText(val);
      setDirty(val !== initialText);
    },
    [initialText],
  );

  const handleSave = async () => {
    const trimmed = text.trim();
    let parsed: Record<string, unknown> = {};
    if (trimmed) {
      try {
        const obj = JSON.parse(trimmed);
        if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
          message.error(t("models.generateConfigMustBeObject"));
          return;
        }
        parsed = obj;
      } catch {
        message.error(t("models.generateConfigInvalidJson"));
        return;
      }
    }

    setSaving(true);
    try {
      await api.configureModel(providerId, model.id, {
        generate_kwargs: parsed,
      });
      message.success(t("models.modelConfigSaved", { name: model.name }));
      setDirty(false);
      await onSaved();
      onClose();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.modelConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: "8px 0 4px" }}>
      <div
        style={{
          fontSize: 12,
          color: isDark ? "rgba(255,255,255,0.45)" : "#888",
          marginBottom: 4,
        }}
      >
        {t("models.modelGenerateConfigHint")}
      </div>
      <MiniJsonEditor
        value={text}
        onChange={handleChange}
        placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  },\n  "max_tokens": 2048\n}`}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginTop: 8,
          gap: 8,
        }}
      >
        <Button
          type="primary"
          size="small"
          loading={saving}
          disabled={!dirty}
          onClick={handleSave}
        >
          {t("models.save")}
        </Button>
      </div>
    </div>
  );
}

interface RemoteModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

export function RemoteModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: RemoteModelManageModalProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { message } = useAppMessage();
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [probingModelId, setProbingModelId] = useState<string | null>(null);
  const [configOpenModelId, setConfigOpenModelId] = useState<string | null>(
    null,
  );
  const [form] = Form.useForm();
  const canDiscover = provider.support_model_discovery;

  // For custom providers ALL models are deletable.
  // For built-in providers only extra_models are deletable.
  const extraModelIds = new Set((provider.extra_models || []).map((m) => m.id));

  const doAddModel = async (id: string, name: string) => {
    await api.addModel(provider.id, { id, name });
    message.success(t("models.modelAdded", { name }));
    form.resetFields();
    setAdding(false);
    onSaved();
  };

  const handleAddModel = async () => {
    try {
      const values = await form.validateFields();
      const id = values.id.trim();
      const name = values.name?.trim() || id;

      // Step 1: Test the model connection first
      setSaving(true);
      const testResult = await api.testModelConnection(provider.id, {
        model_id: id,
      });

      if (!testResult.success) {
        // Test failed – ask user whether to proceed anyway
        setSaving(false);
        const failureDetail =
          getTestConnectionFailureDetail(testResult.message) ||
          t("models.modelTestFailed");
        Modal.confirm({
          title: t("models.testConnectionFailed"),
          content: t("models.modelTestFailedConfirm", {
            message: failureDetail,
          }),
          okText: t("models.addModel"),
          cancelText: t("models.cancel"),
          onOk: async () => {
            setSaving(true);
            try {
              await doAddModel(id, name);
            } catch (error) {
              const errMsg =
                error instanceof Error
                  ? error.message
                  : t("models.modelAddFailed");
              message.error(errMsg);
            } finally {
              setSaving(false);
            }
          },
        });
        return;
      }

      // Step 2: If test passed, add the model
      await doAddModel(id, name);
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      const errMsg =
        error instanceof Error ? error.message : t("models.modelAddFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleTestModel = async (modelId: string) => {
    setTestingModelId(modelId);
    try {
      const result = await api.testModelConnection(provider.id, {
        model_id: modelId,
      });
      if (result.success) {
        message.success(getLocalizedTestConnectionMessage(result, t));
      } else {
        message.warning(getLocalizedTestConnectionMessage(result, t));
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

  const handleProbeMultimodal = async (modelId: string) => {
    setProbingModelId(modelId);
    try {
      const result = await api.probeMultimodal(provider.id, modelId);
      const parts: string[] = [];
      if (result.supports_image) parts.push(t("models.probeImage", "图片"));
      if (result.supports_video) parts.push(t("models.probeVideo", "视频"));
      if (parts.length > 0) {
        message.success(
          t("models.probeSupported", {
            types: parts.join(", "),
            defaultValue: `支持: ${parts.join(", ")}`,
          }),
        );
      } else {
        message.info(t("models.probeNotSupported", "该模型不支持多模态输入"));
      }
      await onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.probeFailed", "探测失败");
      message.error(errMsg);
    } finally {
      setProbingModelId(null);
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
          await onSaved();
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

  const handleClose = () => {
    setAdding(false);
    setConfigOpenModelId(null);
    form.resetFields();
    onClose();
  };

  const handleDiscoverModels = async () => {
    setDiscovering(true);
    try {
      const result = await api.discoverModels(provider.id);
      if (!result.success) {
        message.warning(result.message || t("models.discoverModelsFailed"));
        return;
      }

      if (result.added_count > 0) {
        message.success(
          t("models.autoDiscoveredAndAdded", {
            count: result.models.length,
            added: result.added_count,
          }),
        );
        await onSaved();
      } else if (result.models.length > 0) {
        message.info(
          t("models.autoDiscoveredNoNew", { count: result.models.length }),
        );
        await onSaved();
      } else {
        message.info(result.message || t("models.noModels"));
      }
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.discoverModelsFailed");
      message.error(errMsg);
    } finally {
      setDiscovering(false);
    }
  };

  useEffect(() => {
    // Do not auto-discover models when modal opens, as it may take some time and we don't want to block the UI.
    // Instead, users can click the "Discover Models" button to trigger discovery when needed.
  }, [open, canDiscover, provider.id, provider.models.length]);

  const all_models = [
    ...(provider.models ?? []),
    ...(provider.extra_models ?? []),
  ];

  return (
    <Modal
      title={t("models.manageModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={
        <div className={styles.modalFooter}>
          <div className={styles.modalFooterRight}>
            <Button onClick={handleClose}>{t("models.cancel")}</Button>
          </div>
        </div>
      }
      width={560}
      destroyOnHidden
    >
      {/* Model list */}
      <div className={styles.modelList}>
        {all_models.length === 0 ? (
          <div className={styles.modelListEmpty}>{t("models.noModels")}</div>
        ) : (
          all_models.map((m) => {
            const isDeletable = extraModelIds.has(m.id);
            const isConfigOpen = configOpenModelId === m.id;
            return (
              <div key={m.id}>
                <div className={styles.modelListItem}>
                  <div className={styles.modelListItemInfo}>
                    <span className={styles.modelListItemName}>
                      {m.name}
                      {m.supports_image === true && (
                        <Tag
                          color="blue"
                          style={{ fontSize: 11, marginLeft: 6 }}
                        >
                          {t("models.tagImage", "图片")}
                        </Tag>
                      )}
                      {m.supports_video === true && (
                        <Tag
                          color="purple"
                          style={{ fontSize: 11, marginLeft: 4 }}
                        >
                          {t("models.tagVideo", "视频")}
                        </Tag>
                      )}
                      {m.supports_multimodal === false && (
                        <Tag style={{ fontSize: 11, marginLeft: 6 }}>
                          {t("models.tagTextOnly", "纯文本")}
                        </Tag>
                      )}
                      {m.supports_multimodal === null && (
                        <Tag
                          color="default"
                          style={{ fontSize: 11, marginLeft: 6 }}
                        >
                          {t("models.tagNotProbed", "未检测")}
                        </Tag>
                      )}
                    </span>
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
                          icon={<EyeOutlined />}
                          onClick={() => handleProbeMultimodal(m.id)}
                          loading={probingModelId === m.id}
                          style={{
                            marginRight: 4,
                            color: isDark
                              ? "rgba(255,255,255,0.65)"
                              : undefined,
                          }}
                        >
                          {t("models.probeMultimodal", "测试多模态")}
                        </Button>
                        <Button
                          type="text"
                          size="small"
                          icon={<ApiOutlined />}
                          onClick={() => handleTestModel(m.id)}
                          loading={testingModelId === m.id}
                          style={{
                            marginRight: 4,
                            color: isDark
                              ? "rgba(255,255,255,0.65)"
                              : undefined,
                          }}
                        >
                          {t("models.testConnection")}
                        </Button>
                        <Button
                          type="text"
                          size="small"
                          icon={
                            isConfigOpen ? (
                              <DownOutlined />
                            ) : (
                              <SettingOutlined />
                            )
                          }
                          onClick={() =>
                            setConfigOpenModelId(isConfigOpen ? null : m.id)
                          }
                          style={{
                            marginRight: 4,
                            color: isDark
                              ? "rgba(255,255,255,0.65)"
                              : undefined,
                          }}
                        />
                        <Button
                          type="text"
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => handleRemoveModel(m.id, m.name)}
                        />
                      </>
                    ) : (
                      <>
                        <Tag
                          color="green"
                          style={{ fontSize: 11, marginRight: 4 }}
                        >
                          {t("models.builtin")}
                        </Tag>
                        <Button
                          type="text"
                          size="small"
                          icon={<EyeOutlined />}
                          onClick={() => handleProbeMultimodal(m.id)}
                          loading={probingModelId === m.id}
                          style={{
                            marginRight: 4,
                            color: isDark
                              ? "rgba(255,255,255,0.65)"
                              : undefined,
                          }}
                        >
                          {t("models.probeMultimodal", "测试多模态")}
                        </Button>
                        <Button
                          type="text"
                          size="small"
                          icon={<ApiOutlined />}
                          onClick={() => handleTestModel(m.id)}
                          loading={testingModelId === m.id}
                          style={{
                            marginRight: 4,
                            color: isDark
                              ? "rgba(255,255,255,0.65)"
                              : undefined,
                          }}
                        >
                          {t("models.testConnection")}
                        </Button>
                        <Button
                          type="text"
                          size="small"
                          icon={
                            isConfigOpen ? (
                              <DownOutlined />
                            ) : (
                              <SettingOutlined />
                            )
                          }
                          onClick={() =>
                            setConfigOpenModelId(isConfigOpen ? null : m.id)
                          }
                          style={{
                            color: isDark
                              ? "rgba(255,255,255,0.65)"
                              : undefined,
                          }}
                        />
                      </>
                    )}
                  </div>
                </div>
                {isConfigOpen && (
                  <div
                    style={{
                      padding: "0 16px 12px",
                      borderBottom: isDark
                        ? "1px solid rgba(255,255,255,0.06)"
                        : "1px solid #f5f5f5",
                    }}
                  >
                    <ModelConfigEditor
                      providerId={provider.id}
                      model={m}
                      onSaved={onSaved}
                      onClose={() => setConfigOpenModelId(null)}
                      isDark={isDark}
                    />
                  </div>
                )}
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
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <Button
            icon={<SyncOutlined />}
            onClick={handleDiscoverModels}
            loading={discovering}
            disabled={!canDiscover}
            style={{ flex: 1 }}
          >
            {t("models.discoverModels")}
          </Button>
          <Button
            type="dashed"
            icon={<PlusOutlined />}
            onClick={() => setAdding(true)}
            style={{ flex: 1 }}
          >
            {t("models.addModel")}
          </Button>
        </div>
      )}
    </Modal>
  );
}
