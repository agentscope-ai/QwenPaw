import { useState, useEffect, useMemo, useRef } from "react";
import type { KeyboardEvent, ReactNode, UIEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Network, ChevronDown, ChevronRight, X, Plus } from "lucide-react";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import type { BaseUrlOption } from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { getLocalizedTestConnectionMessage } from "./testConnectionMessage";
import styles from "../../index.module.less";

interface HeaderEntry {
  key: string;
  value: string;
}

interface JsonCodeEditorProps {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  rows?: number;
}

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

function JsonCodeEditor({
  value = "",
  onChange,
  placeholder,
  rows = 8,
}: JsonCodeEditorProps) {
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
    const hasSelection = selectionStart !== selectionEnd;
    const selectedText = value.slice(selectionStart, selectionEnd);

    if (!hasSelection || !selectedText.includes("\n")) {
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
      return;
    }

    const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
    const block = value.slice(lineStart, selectionEnd);
    const lines = block.split("\n");

    if (event.shiftKey) {
      const updatedLines = lines.map((line) =>
        line.startsWith(indentUnit) ? line.slice(indentUnit.length) : line,
      );
      const removedFromFirstLine = lines[0].startsWith(indentUnit)
        ? indentUnit.length
        : 0;
      const removedTotal = lines.reduce(
        (total, line) =>
          total + (line.startsWith(indentUnit) ? indentUnit.length : 0),
        0,
      );
      const nextValue =
        value.slice(0, lineStart) +
        updatedLines.join("\n") +
        value.slice(selectionEnd);
      onChange?.(nextValue);
      requestAnimationFrame(() => {
        textareaRef.current?.setSelectionRange(
          selectionStart - removedFromFirstLine,
          selectionEnd - removedTotal,
        );
      });
      return;
    }

    const updatedLines = lines.map((line) => `${indentUnit}${line}`);
    const nextValue =
      value.slice(0, lineStart) +
      updatedLines.join("\n") +
      value.slice(selectionEnd);
    onChange?.(nextValue);
    requestAnimationFrame(() => {
      textareaRef.current?.setSelectionRange(
        selectionStart + indentUnit.length,
        selectionEnd + indentUnit.length * lines.length,
      );
    });
  };

  return (
    <div className={styles.jsonEditorContainer}>
      <div
        ref={highlightRef}
        aria-hidden="true"
        className={styles.jsonEditorHighlight}
      >
        {value ? highlightJson(value) : placeholder}
        {!value && <span>{"\n"}</span>}
      </div>
      <textarea
        ref={textareaRef}
        rows={rows}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
        onKeyDown={handleKeyDown}
        onScroll={handleScroll}
        placeholder={placeholder}
        spellCheck={false}
        className={styles.jsonEditorTextarea}
      />
    </div>
  );
}

interface ProviderConfigModalProps {
  provider: {
    id: string;
    name: string;
    api_key?: string;
    api_key_prefix?: string;
    base_url?: string;
    is_custom: boolean;
    freeze_url: boolean;
    chat_model: string;
    support_connection_check: boolean;
    generate_kwargs: Record<string, unknown>;
    custom_headers?: Record<string, string>;
    auth_mode?: "api_key" | "auth_token";
    meta?: Record<string, unknown>;
  };
  activeModels: any;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function ProviderConfigModal({
  provider,
  activeModels,
  open,
  onClose,
  onSaved,
}: ProviderConfigModalProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [formDirty, setFormDirty] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [revokeDialogOpen, setRevokeDialogOpen] = useState(false);

  // Form fields
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(provider.base_url || "");
  const [chatModel, setChatModel] = useState(
    provider.chat_model || "OpenAIChatModel",
  );
  const [generateKwargsText, setGenerateKwargsText] = useState(
    provider.generate_kwargs && Object.keys(provider.generate_kwargs).length > 0
      ? JSON.stringify(provider.generate_kwargs, null, 2)
      : "",
  );
  const [baseUrlError, setBaseUrlError] = useState("");
  const [apiKeyError, setApiKeyError] = useState("");
  const [generateError, setGenerateError] = useState("");

  const { message } = useAppMessage();
  const [authMode, setAuthMode] = useState<"api_key" | "auth_token">(
    provider.auth_mode ?? "api_key",
  );
  const [customHeaders, setCustomHeaders] = useState<HeaderEntry[]>(
    Object.entries(provider.custom_headers ?? {}).map(([key, value]) => ({
      key,
      value,
    })),
  );
  const canEditBaseUrl = !provider.freeze_url;

  const baseUrlOptions = useMemo<BaseUrlOption[]>(() => {
    const raw = provider.meta?.base_url_options;
    if (!Array.isArray(raw)) return [];
    return raw.flatMap((item) => {
      if (
        item &&
        typeof item === "object" &&
        typeof (item as BaseUrlOption).label === "string" &&
        typeof (item as BaseUrlOption).value === "string"
      ) {
        return [item as BaseUrlOption];
      }
      return [];
    });
  }, [provider.meta]);

  const useBaseUrlSelect = canEditBaseUrl && baseUrlOptions.length > 0;

  const parseGenerateConfig = (value?: string) => {
    const trimmed = value?.trim();
    if (!trimmed) return undefined;
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      throw new Error(t("models.generateConfigInvalidJson"));
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(t("models.generateConfigMustBeObject"));
    }
    return parsed as Record<string, unknown>;
  };

  const effectiveChatModel = useMemo(() => {
    if (!provider.is_custom) return provider.chat_model;
    return chatModel || provider.chat_model || "OpenAIChatModel";
  }, [provider.chat_model, provider.is_custom, chatModel]);

  const isAnthropicProvider = useMemo(
    () =>
      provider.id === "anthropic" ||
      provider.chat_model === "AnthropicChatModel" ||
      effectiveChatModel === "AnthropicChatModel",
    [provider.id, provider.chat_model, effectiveChatModel],
  );

  const apiKeyPlaceholder = useMemo(() => {
    if (provider.api_key) return t("models.leaveBlankKeep");
    if (provider.api_key_prefix)
      return t("models.enterApiKey", { prefix: provider.api_key_prefix });
    return t("models.enterApiKeyOptional");
  }, [provider.api_key, provider.api_key_prefix, t]);

  const apiKeyLabel =
    isAnthropicProvider && authMode === "auth_token"
      ? t("models.authModeAuthToken")
      : t("models.apiKey");

  const baseUrlExtra = useMemo(() => {
    if (!canEditBaseUrl) return undefined;
    if (useBaseUrlSelect) return t("models.selectBaseURLHint");
    if (provider.id === "azure-openai") return t("models.azureEndpointHint");
    if (provider.id === "anthropic") return t("models.anthropicEndpointHint");
    if (provider.id === "openai") return t("models.openAIEndpoint");
    if (provider.id === "opencode") return t("models.openAICompatibleEndpoint");
    if (provider.id === "ollama") return t("models.ollamaEndpointHint");
    if (provider.id === "lmstudio") return t("models.lmstudioEndpointHint");
    if (provider.is_custom)
      return effectiveChatModel === "AnthropicChatModel"
        ? t("models.anthropicEndpointHint")
        : t("models.openAICompatibleEndpoint");
    return t("models.apiEndpointHint");
  }, [
    canEditBaseUrl,
    useBaseUrlSelect,
    provider.id,
    provider.is_custom,
    effectiveChatModel,
    t,
  ]);

  const baseUrlPlaceholder = useMemo(() => {
    if (!canEditBaseUrl) return "";
    if (provider.id === "azure-openai")
      return "https://<resource>.openai.azure.com/openai/v1";
    if (provider.id === "anthropic") return "https://api.anthropic.com";
    if (provider.id === "openai") return "https://api.openai.com/v1";
    if (provider.id === "opencode") return "https://opencode.ai/zen/v1";
    if (provider.id === "ollama") return "http://localhost:11434";
    if (provider.id === "lmstudio") return "http://localhost:1234/v1";
    if (provider.is_custom && effectiveChatModel === "AnthropicChatModel")
      return "https://api.anthropic.com";
    return "https://api.example.com";
  }, [canEditBaseUrl, provider.id, provider.is_custom, effectiveChatModel]);

  // Sync form when modal opens or provider data changes
  useEffect(() => {
    if (open) {
      setApiKey("");
      setBaseUrl(provider.base_url || "");
      setChatModel(provider.chat_model || "OpenAIChatModel");
      setGenerateKwargsText(
        provider.generate_kwargs &&
          Object.keys(provider.generate_kwargs).length > 0
          ? JSON.stringify(provider.generate_kwargs, null, 2)
          : "",
      );
      setBaseUrlError("");
      setApiKeyError("");
      setGenerateError("");
      setAdvancedOpen(false);
      setFormDirty(false);
      setAuthMode(provider.auth_mode ?? "api_key");
      setCustomHeaders(
        Object.entries(provider.custom_headers ?? {}).map(([key, value]) => ({
          key,
          value,
        })),
      );
    }
  }, [provider, open]);

  const validateForm = () => {
    let valid = true;

    if (canEditBaseUrl && !provider.freeze_url && !baseUrl.trim()) {
      setBaseUrlError(t("models.pleaseEnterBaseURL"));
      valid = false;
    } else if (baseUrl.trim()) {
      try {
        const url = new URL(baseUrl.trim());
        if (!["http:", "https:"].includes(url.protocol)) {
          setBaseUrlError(t("models.pleaseEnterValidURL"));
          valid = false;
        } else {
          setBaseUrlError("");
        }
      } catch {
        setBaseUrlError(t("models.pleaseEnterValidURL"));
        valid = false;
      }
    } else {
      setBaseUrlError("");
    }

    if (
      apiKey &&
      provider.api_key_prefix &&
      authMode !== "auth_token" &&
      !apiKey.startsWith(provider.api_key_prefix)
    ) {
      setApiKeyError(
        t("models.apiKeyShouldStart", { prefix: provider.api_key_prefix }),
      );
      valid = false;
    } else {
      setApiKeyError("");
    }

    try {
      parseGenerateConfig(generateKwargsText);
      setGenerateError("");
    } catch (e) {
      setGenerateError(
        e instanceof Error ? e.message : t("models.generateConfigInvalidJson"),
      );
      valid = false;
    }

    return valid;
  };

  const getHeaders = () =>
    customHeaders
      .filter((h) => h.key.trim())
      .reduce<Record<string, string>>((acc, h) => {
        acc[h.key.trim()] = h.value;
        return acc;
      }, {});

  const handleSubmit = async () => {
    if (!validateForm()) return;
    setSaving(true);
    try {
      const generateConfig = parseGenerateConfig(generateKwargsText);
      const hasGenerateConfigInput = Boolean(generateKwargsText?.trim());

      if (provider.support_connection_check) {
        const result = await api.testProviderConnection(provider.id, {
          api_key: apiKey || undefined,
          base_url: baseUrl || undefined,
          chat_model: chatModel,
          custom_headers: getHeaders(),
          auth_mode: isAnthropicProvider ? authMode : undefined,
        });
        if (!result.success) {
          message.error(getLocalizedTestConnectionMessage(result, t));
          return;
        }
      }

      await api.configureProvider(provider.id, {
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
        chat_model: chatModel,
        generate_kwargs: hasGenerateConfigInput ? generateConfig : {},
        custom_headers: getHeaders(),
        auth_mode: isAnthropicProvider ? authMode : undefined,
      });

      await onSaved();
      setFormDirty(false);
      onClose();
      message.success(t("models.configurationSaved", { name: provider.name }));
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSaveConfig");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const result = await api.testProviderConnection(provider.id, {
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
        chat_model: chatModel,
        custom_headers: getHeaders(),
        auth_mode: isAnthropicProvider ? authMode : undefined,
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
      setTesting(false);
    }
  };

  const isActiveLlmProvider =
    activeModels?.active_llm?.provider_id === provider.id;

  const confirmRevoke = async () => {
    setRevokeDialogOpen(false);
    try {
      await api.configureProvider(provider.id, { api_key: "" });
      await onSaved();
      onClose();
      if (isActiveLlmProvider) {
        message.success(
          t("models.authorizationRevoked", { name: provider.name }),
        );
      } else {
        message.success(
          t("models.authorizationRevokedSimple", { name: provider.name }),
        );
      }
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToRevoke");
      message.error(errMsg);
    }
  };

  const markDirty = () => setFormDirty(true);

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!v) onClose();
        }}
      >
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {t("models.configureProvider", { name: provider.name })}
            </DialogTitle>
          </DialogHeader>

          <div className="flex flex-col gap-4">
            {provider.is_custom && (
              <div>
                <Label className="mb-1 block">{t("models.protocol")}</Label>
                <Select
                  disabled
                  value={chatModel}
                  onValueChange={(v) => {
                    setChatModel(v);
                    markDirty();
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="OpenAIChatModel">
                      {t("models.protocolOpenAI")}
                    </SelectItem>
                    <SelectItem value="AnthropicChatModel">
                      {t("models.protocolAnthropic")}
                    </SelectItem>
                  </SelectContent>
                </Select>
                {t("models.protocolHint") && (
                  <p className="text-xs text-muted-foreground mt-1">
                    {t("models.protocolHint")}
                  </p>
                )}
              </div>
            )}

            {/* Base URL */}
            <div>
              <Label className="mb-1 block">{t("models.baseURL")}</Label>
              {useBaseUrlSelect ? (
                <Select
                  value={baseUrl}
                  onValueChange={(v) => {
                    setBaseUrl(v);
                    markDirty();
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("models.selectBaseURL")} />
                  </SelectTrigger>
                  <SelectContent>
                    {baseUrlOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label} — {option.value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  value={baseUrl}
                  onChange={(e) => {
                    setBaseUrl(e.target.value);
                    markDirty();
                  }}
                  placeholder={baseUrlPlaceholder}
                  disabled={!canEditBaseUrl}
                />
              )}
              {baseUrlExtra && (
                <p className="text-xs text-muted-foreground mt-1">
                  {baseUrlExtra}
                </p>
              )}
              {baseUrlError && (
                <p className="text-xs text-destructive mt-1">{baseUrlError}</p>
              )}
            </div>

            {/* API Key */}
            <div>
              <Label className="mb-1 block">{apiKeyLabel}</Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  markDirty();
                }}
                placeholder={apiKeyPlaceholder}
              />
              {apiKeyError && (
                <p className="text-xs text-destructive mt-1">{apiKeyError}</p>
              )}
            </div>

            {/* Advanced section */}
            <div className={styles.advancedConfigSection}>
              <button
                type="button"
                className={styles.advancedConfigToggle}
                onClick={() => setAdvancedOpen((prev) => !prev)}
              >
                <span className={styles.advancedConfigToggleLabel}>
                  {advancedOpen ? (
                    <ChevronDown className="inline h-4 w-4 mr-1" />
                  ) : (
                    <ChevronRight className="inline h-4 w-4 mr-1" />
                  )}
                  {t("models.advancedConfig")}
                </span>
              </button>

              {/* Anthropic auth mode selector */}
              {isAnthropicProvider && advancedOpen && (
                <div className="mt-3">
                  <Label className="mb-1 block">{t("models.authMode")}</Label>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="authMode"
                        value="api_key"
                        checked={authMode === "api_key"}
                        onChange={() => {
                          setAuthMode("api_key");
                          markDirty();
                        }}
                        className="accent-primary"
                      />
                      {t("models.authModeApiKey")}
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="authMode"
                        value="auth_token"
                        checked={authMode === "auth_token"}
                        onChange={() => {
                          setAuthMode("auth_token");
                          markDirty();
                        }}
                        className="accent-primary"
                      />
                      {t("models.authModeAuthToken")}
                    </label>
                  </div>
                </div>
              )}

              {/* Custom Headers editor */}
              {advancedOpen && (
                <div className="mt-3">
                  <Label className="mb-1 block">
                    {t("models.customHeaders")}
                  </Label>
                  <p className="text-xs text-muted-foreground mb-2">
                    {t("models.customHeadersHint")}
                  </p>
                  <div className={styles.customHeadersSection}>
                    {customHeaders.map((header, index) => (
                      <div key={index} className={styles.customHeaderRow}>
                        <Input
                          className={styles.customHeaderKey}
                          placeholder={t("models.customHeaderKey")}
                          value={header.key}
                          onChange={(e) => {
                            const next = [...customHeaders];
                            next[index] = {
                              ...next[index],
                              key: e.target.value,
                            };
                            setCustomHeaders(next);
                            markDirty();
                          }}
                        />
                        <Input
                          className={styles.customHeaderValue}
                          placeholder={t("models.customHeaderValue")}
                          value={header.value}
                          onChange={(e) => {
                            const next = [...customHeaders];
                            next[index] = {
                              ...next[index],
                              value: e.target.value,
                            };
                            setCustomHeaders(next);
                            markDirty();
                          }}
                        />
                        <button
                          type="button"
                          className={styles.customHeaderDelete}
                          onClick={() => {
                            setCustomHeaders(
                              customHeaders.filter((_, i) => i !== index),
                            );
                            markDirty();
                          }}
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className={styles.addHeaderBtn}
                      onClick={() => {
                        setCustomHeaders([
                          ...customHeaders,
                          { key: "", value: "" },
                        ]);
                        markDirty();
                      }}
                    >
                      <Plus className="inline h-3 w-3 mr-1" />
                      {t("models.addHeader")}
                    </button>
                  </div>
                </div>
              )}

              {advancedOpen && (
                <div className="mt-3">
                  <Label className="mb-1 block">
                    {t("models.generateConfig")}
                  </Label>
                  <p className="text-xs text-muted-foreground mb-2">
                    {t("models.generateConfigHint")}
                  </p>
                  <JsonCodeEditor
                    rows={8}
                    value={generateKwargsText}
                    onChange={(v) => {
                      setGenerateKwargsText(v);
                      markDirty();
                    }}
                    placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  },\n  "max_tokens": 2048\n}`}
                  />
                  {generateError && (
                    <p className="text-xs text-destructive mt-1">
                      {generateError}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>

          <DialogFooter className="flex-row justify-between gap-2 mt-4">
            <div className="flex gap-2">
              {provider.api_key && (
                <Button
                  variant="outline"
                  size="sm"
                  className="text-destructive border-destructive hover:bg-destructive/10"
                  onClick={() => setRevokeDialogOpen(true)}
                >
                  {t("models.revokeAuthorization")}
                </Button>
              )}
              {provider.support_connection_check && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={testing}
                  onClick={handleTest}
                >
                  <Network className="mr-2 h-4 w-4" />
                  {t("models.testConnection")}
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={onClose}>
                {t("models.cancel")}
              </Button>
              <Button disabled={!formDirty || saving} onClick={handleSubmit}>
                {t("models.save")}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={revokeDialogOpen} onOpenChange={setRevokeDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("models.revokeAuthorization")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {isActiveLlmProvider
                ? t("models.revokeConfirmContent", { name: provider.name })
                : t("models.revokeConfirmSimple", { name: provider.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("models.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={confirmRevoke}
            >
              {t("models.revokeAuthorization")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
