import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Form, Input, Tooltip } from "antd";
import {
  Blocks,
  Check,
  CircleAlert,
  CircleHelp,
  Clock3,
  Copy,
  ExternalLink,
  LogOut,
  Network,
  PawPrint,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { harnessApi, type HarnessProvider } from "@/api/modules/harness";
import type { AgentBackend } from "@/api/types/agents";
import { useAppMessage } from "@/hooks/useAppMessage";
import { copyText } from "@/utils/clipboard";
import styles from "./AgentBackendFields.module.less";

const POLL_INTERVAL_MS = 2_000;

type ProviderId = "codex" | "qoder";

interface ProviderOption {
  id: ProviderId;
  name: string;
  hintKey: string;
  accountKey: string;
  binaryKey: string;
  binaryHelpKey: string;
  binaryPlaceholderKey: string;
  detectedKey: string;
  notFoundKey: string;
  authHintKey: string;
  connectKey: string;
}

const PROVIDERS: ProviderOption[] = [
  {
    id: "codex",
    name: "Codex",
    hintKey: "agent.backend.codexHint",
    accountKey: "agent.backend.account",
    binaryKey: "agent.backend.binary",
    binaryHelpKey: "agent.backend.binaryHelp",
    binaryPlaceholderKey: "agent.backend.binaryPlaceholder",
    detectedKey: "agent.backend.detectedBinary",
    notFoundKey: "agent.backend.codexNotFound",
    authHintKey: "agent.backend.apiKeyLoginHint",
    connectKey: "harnesses.connect",
  },
  {
    id: "qoder",
    name: "Qoder",
    hintKey: "agent.backend.qoderHint",
    accountKey: "agent.backend.qoderAccount",
    binaryKey: "agent.backend.qoderBinary",
    binaryHelpKey: "agent.backend.qoderBinaryHelp",
    binaryPlaceholderKey: "agent.backend.qoderBinaryPlaceholder",
    detectedKey: "agent.backend.qoderDetectedBinary",
    notFoundKey: "agent.backend.qoderNotFound",
    authHintKey: "agent.backend.qoderAuthHint",
    connectKey: "agent.backend.qoderConnect",
  },
];

interface AgentBackendFieldsProps {
  form: ReturnType<typeof Form.useForm>[0];
  open: boolean;
}

function providerOption(backend: AgentBackend): ProviderOption {
  return PROVIDERS.find((item) => item.id === backend) ?? PROVIDERS[0];
}

export function AgentBackendFields({ form, open }: AgentBackendFieldsProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const backend =
    (Form.useWatch("backend", form) as AgentBackend | undefined) ?? "qwenpaw";
  const selectedProvider = providerOption(backend);
  const [provider, setProvider] = useState<HarnessProvider | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [checking, setChecking] = useState(false);
  const pollTimer = useRef<number | undefined>(undefined);
  const pollTimeout = useRef<number | undefined>(undefined);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    if (pollTimeout.current) window.clearTimeout(pollTimeout.current);
    pollTimer.current = undefined;
    pollTimeout.current = undefined;
  }, []);

  const providerSettings = useCallback(() => {
    const value = form.getFieldValue(["backend_settings", "binary"]);
    const binary = typeof value === "string" ? value.trim() : "";
    return binary ? { binary } : {};
  }, [form]);

  const loadStatus = useCallback(async () => {
    const result = await harnessApi.status(
      selectedProvider.id,
      providerSettings(),
    );
    setProvider(result);
    return result;
  }, [providerSettings, selectedProvider.id]);

  const checkStatus = useCallback(async () => {
    setChecking(true);
    try {
      return await loadStatus();
    } finally {
      setChecking(false);
    }
  }, [loadStatus]);

  useEffect(() => {
    if (!open || backend === "qwenpaw") {
      setProvider(null);
      return stopPolling;
    }
    void checkStatus().catch(() => setProvider(null));
    return stopPolling;
  }, [backend, checkStatus, open, stopPolling]);

  const beginPolling = useCallback(() => {
    stopPolling();
    const poll = async () => {
      try {
        const result = await loadStatus();
        if (pollTimeout.current === undefined) return;
        if (result.authenticated) {
          stopPolling();
          setConnecting(false);
          message.success(t("harnesses.connected"));
          return;
        }
      } catch {
        // Keep polling until the overall login timeout expires.
      }
      if (pollTimeout.current !== undefined) {
        pollTimer.current = window.setTimeout(
          () => void poll(),
          POLL_INTERVAL_MS,
        );
      }
    };
    pollTimer.current = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
    pollTimeout.current = window.setTimeout(() => {
      stopPolling();
      setConnecting(false);
    }, 120_000);
  }, [loadStatus, message, stopPolling, t]);

  const connect = useCallback(async () => {
    const popup =
      selectedProvider.id === "codex"
        ? window.open("about:blank", "_blank")
        : null;
    if (popup) popup.opener = null;
    setConnecting(true);
    try {
      const login = await harnessApi.login(
        selectedProvider.id,
        false,
        providerSettings(),
      );
      if (login.authUrl) {
        if (popup) popup.location.href = login.authUrl;
        else window.open(login.authUrl, "_blank", "noopener,noreferrer");
      } else if (login.type !== "external") {
        throw new Error(`${selectedProvider.name} did not start login`);
      }
      beginPolling();
    } catch (error) {
      popup?.close();
      setConnecting(false);
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [
    beginPolling,
    message,
    providerSettings,
    selectedProvider.id,
    selectedProvider.name,
  ]);

  const disconnect = useCallback(async () => {
    try {
      await harnessApi.logout(selectedProvider.id, providerSettings());
      await loadStatus();
      message.success(t("harnesses.disconnected"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [loadStatus, message, providerSettings, selectedProvider.id, t]);

  const accountType = provider?.account?.type;
  const tokenAuthenticated =
    provider?.authenticated &&
    (accountType === "apiKey" || accountType === "accessToken");
  const chatGptAuthenticated =
    provider?.authenticated && accountType === "chatgpt";
  const accountIdentity =
    provider?.account?.email ?? provider?.account?.username;

  const selectBackend = useCallback(
    (next: AgentBackend) => {
      const switchingProvider =
        next !== "qwenpaw" && next !== form.getFieldValue("backend");
      form.setFieldsValue({
        backend: next,
        ...(next === "qwenpaw" || switchingProvider
          ? { backend_settings: {} }
          : {}),
      });
    },
    [form],
  );

  return (
    <section className={styles.section}>
      <Form.Item name="backend" hidden>
        <Input />
      </Form.Item>

      <div className={styles.sectionHeading}>
        <span className={styles.eyebrow}>{t("agent.backend.eyebrow")}</span>
        <h3>{t("agent.backend.typeTitle")}</h3>
        <p>{t("agent.backend.typeDescription")}</p>
      </div>

      <div className={styles.typeGrid}>
        <button
          type="button"
          className={`${styles.typeCard} ${
            backend === "qwenpaw" ? styles.selected : ""
          }`}
          onClick={() => selectBackend("qwenpaw")}
        >
          <span className={styles.typeIcon}>
            <PawPrint size={20} />
          </span>
          <span className={styles.typeCopy}>
            <strong>{t("agent.backend.nativeTitle")}</strong>
            <small>{t("agent.backend.nativeDescription")}</small>
          </span>
          <span className={styles.radioMark} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`${styles.typeCard} ${
            backend !== "qwenpaw" ? styles.selected : ""
          }`}
          onClick={() =>
            selectBackend(backend === "qwenpaw" ? "codex" : backend)
          }
        >
          <span className={styles.typeIcon}>
            <Blocks size={20} />
          </span>
          <span className={styles.typeCopy}>
            <strong>{t("agent.backend.thirdPartyTitle")}</strong>
            <small>{t("agent.backend.thirdPartyDescription")}</small>
          </span>
          <span className={styles.radioMark} aria-hidden="true" />
        </button>
      </div>

      {backend !== "qwenpaw" && (
        <div className={styles.thirdPartyPanel}>
          <div className={styles.panelHeading}>
            <h4>{t("agent.backend.providerTitle")}</h4>
            <p>{t("agent.backend.providerDescription")}</p>
          </div>

          <div className={styles.providerGrid}>
            {PROVIDERS.map((item) => {
              const selected = backend === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={
                    selected ? styles.providerCardSelected : styles.providerCard
                  }
                  onClick={() => selectBackend(item.id)}
                >
                  <span className={styles.providerIcon}>
                    <SquareTerminal size={18} />
                  </span>
                  <span className={styles.providerCopy}>
                    <strong>{item.name}</strong>
                    <small>{t(item.hintKey)}</small>
                  </span>
                  {selected && (
                    <Check size={15} className={styles.providerCheck} />
                  )}
                </button>
              );
            })}
            <div className={styles.providerCardDisabled}>
              <span className={styles.providerIcon}>
                <Blocks size={18} />
              </span>
              <span className={styles.providerCopy}>
                <strong>Claude Code</strong>
                <small>{t("harnesses.comingSoon")}</small>
              </span>
              <Clock3 size={14} />
            </div>
          </div>

          <div className={styles.providerConfig}>
            <Form.Item
              name={["backend_settings", "binary"]}
              label={
                <span className={styles.binaryLabel}>
                  {t(selectedProvider.binaryKey)}
                  <Tooltip title={t(selectedProvider.binaryHelpKey)}>
                    <span
                      className={styles.helpIcon}
                      aria-label={t("common.help")}
                      role="img"
                    >
                      <CircleHelp size={14} />
                    </span>
                  </Tooltip>
                </span>
              }
              className={styles.binaryField}
            >
              <Input
                allowClear
                placeholder={t(selectedProvider.binaryPlaceholderKey)}
                onBlur={(event) => {
                  const value = event.target.value.trim();
                  form.setFieldValue(
                    ["backend_settings", "binary"],
                    value || undefined,
                  );
                }}
                suffix={
                  <Button
                    type="text"
                    size="small"
                    icon={<RefreshCw size={14} />}
                    loading={checking}
                    onClick={() => void checkStatus()}
                  >
                    <span className={styles.detectLabel}>
                      {t("agent.backend.detect")}
                    </span>
                  </Button>
                }
              />
            </Form.Item>
            {provider?.runtime_path && (
              <div className={`${styles.binaryStatus} ${styles.detected}`}>
                <span className={styles.binaryStatusLabel}>
                  <Check size={14} />
                  {t(selectedProvider.detectedKey)}
                </span>
                <Tooltip title={provider.runtime_path}>
                  <code className={styles.binaryPath}>
                    {provider.runtime_path}
                  </code>
                </Tooltip>
                <Tooltip title={t("common.copy")}>
                  <button
                    type="button"
                    className={styles.copyPathButton}
                    aria-label={t("common.copy")}
                    onClick={() => {
                      void copyText(provider.runtime_path as string)
                        .then(() => message.success(t("common.copied")))
                        .catch(() => message.error(t("common.copyFailed")));
                    }}
                  >
                    <Copy size={13} />
                  </button>
                </Tooltip>
              </div>
            )}
            {!checking && provider && !provider.runtime_path && (
              <div className={`${styles.binaryStatus} ${styles.notDetected}`}>
                <span className={styles.binaryStatusLabel}>
                  <CircleAlert size={14} />
                  {t(selectedProvider.notFoundKey)}
                </span>
              </div>
            )}
            <div className={styles.accountRow}>
              <div className={styles.accountState}>
                <span className={styles.accountLabel}>
                  {t(selectedProvider.accountKey)}
                </span>
                {provider?.authenticated ? (
                  <span className={styles.connectedState}>
                    <Check size={14} />
                    {tokenAuthenticated
                      ? t("harnesses.apiKeyAuthenticated")
                      : chatGptAuthenticated
                      ? t("harnesses.chatGptAuthenticated")
                      : t("harnesses.cliAuthenticated", {
                          type: selectedProvider.name,
                        })}
                    {accountIdentity ? ` · ${accountIdentity}` : ""}
                  </span>
                ) : (
                  <span className={styles.disconnectedState}>
                    <CircleAlert size={14} />
                    {provider?.installed
                      ? t("harnesses.notConnected")
                      : t(selectedProvider.notFoundKey)}
                  </span>
                )}
              </div>
              <div className={styles.accountAction}>
                {!provider?.authenticated && (
                  <Button
                    icon={<ExternalLink size={14} />}
                    loading={connecting}
                    disabled={provider ? !provider.installed : true}
                    onClick={() => void connect()}
                  >
                    {t(selectedProvider.connectKey)}
                  </Button>
                )}
                {chatGptAuthenticated && (
                  <Button
                    icon={<LogOut size={14} />}
                    onClick={() => void disconnect()}
                  >
                    {t("harnesses.disconnect")}
                  </Button>
                )}
              </div>
            </div>
            {!provider?.authenticated && provider?.installed && (
              <p className={styles.authHint}>
                {t(selectedProvider.authHintKey)}
              </p>
            )}
            {provider?.authenticated && (
              <p className={styles.chatSettingsHint}>
                {t("agent.backend.chatSettingsHint")}
              </p>
            )}
            {provider && (
              <div className={styles.capabilityPanel}>
                <span className={styles.capabilityTitle}>
                  {t("agent.backend.capabilityTitle")}
                </span>
                <div className={styles.capabilityGrid}>
                  <div className={styles.capabilityItem}>
                    <Sparkles size={16} />
                    <span>
                      <strong>{t("agent.backend.inheritedSkills")}</strong>
                      <small>
                        {provider.capabilities.qwenpaw_skills_projection
                          ? t("agent.backend.runtimeInherited")
                          : t("agent.backend.notSupported")}
                      </small>
                    </span>
                  </div>
                  <div className={styles.capabilityItem}>
                    <Network size={16} />
                    <span>
                      <strong>{t("agent.backend.inheritedMcp")}</strong>
                      <small>
                        {provider.capabilities.qwenpaw_mcp_projection
                          ? t("agent.backend.runtimeInherited")
                          : t("agent.backend.notSupported")}
                      </small>
                    </span>
                  </div>
                  <div className={styles.capabilityItem}>
                    <ShieldCheck size={16} />
                    <span>
                      <strong>{t("agent.backend.policyCompatibility")}</strong>
                      <small>
                        {provider.capabilities.mcp_tool_allowlist
                          ? t("agent.backend.toolAllowlistSupported")
                          : t("agent.backend.policyLimited")}
                      </small>
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
