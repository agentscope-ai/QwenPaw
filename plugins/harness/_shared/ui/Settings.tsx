import { getHost, type HarnessSettingsProps } from "@qwenpaw/plugin-sdk";
import {
  Check,
  CircleAlert,
  CircleHelp,
  Copy,
  ExternalLink,
  LogOut,
  Network,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import settingsCss from "./Settings.css?inline";
import { useHarnessConnection } from "./useHarnessConnection";

const host = getHost().host;
const React = host.React;
const { Button, Input, Tooltip } = host.antd;
export interface HarnessStatus {
  installed: boolean;
  authenticated: boolean;
  runtime_path?: string | null;
  error?: string | null;
  account?: { type?: string; email?: string; username?: string } | null;
  capabilities?: {
    qwenpaw_skills_projection?: boolean;
    qwenpaw_mcp_projection?: boolean;
    mcp_tool_allowlist?: boolean;
  };
}

export interface HarnessText {
  hint: string;
  account: string;
  binary: string;
  binaryHelp: string;
  binaryPlaceholder: string;
  detected: string;
  notFound: string;
  authHint: string;
  notSupported: string;
  policyLimited: string;
  inheritedMcp: string;
  capabilityTitle: string;
  inheritedSkills: string;
  toolAllowlistSupported: string;
  runtimeInherited: string;
  chatSettingsHint: string;
  detect: string;
  policyCompatibility: string;
  connected: string;
  disconnected: string;
  notConnected: string;
  connect: string;
  disconnect: string;
  apiKeyAuthenticated: string;
  chatGptAuthenticated: string;
  cliAuthenticated: string;
  copy: string;
  copied: string;
  copyFailed: string;
}

export interface SharedSettingsProps extends HarnessSettingsProps {
  backendId: string;
  providerName: string;
  text: HarnessText;
  loginMode: "browser" | "external";
  canDisconnect?: (status: HarnessStatus) => boolean;
}

export function Settings({
  value,
  onChange,
  open,
  backendId,
  providerName,
  text,
  loginMode,
  canDisconnect,
}: SharedSettingsProps) {
  const {
    status,
    checking,
    connecting,
    error,
    check,
    connect,
    disconnect,
    copyPath,
  } = useHarnessConnection({ value, open, backendId, text, loginMode });
  const binaryId = React.useId();
  const identity = status?.account?.email ?? status?.account?.username;
  const kind = status?.account?.type;
  const token = kind === "apiKey" || kind === "accessToken";
  const account = token
    ? text.apiKeyAuthenticated
    : kind === "chatgpt"
    ? text.chatGptAuthenticated
    : text.cliAuthenticated.replace("{{type}}", providerName);
  return (
    <div className={`harness-settings harness-${backendId}-settings`}>
      <style>{settingsCss}</style>
      <p className="providerHint">{text.hint}</p>
      <div className="binaryField">
        <label className="binaryLabel" htmlFor={binaryId}>
          {text.binary}
        </label>
        <Tooltip title={text.binaryHelp}>
          <button
            type="button"
            className="helpIcon"
            aria-label={text.binaryHelp}
          >
            <CircleHelp size={14} aria-hidden="true" focusable="false" />
          </button>
        </Tooltip>
        <Input
          id={binaryId}
          value={String(value.binary ?? "")}
          placeholder={text.binaryPlaceholder}
          allowClear
          onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
            onChange({ ...value, binary: event.target.value })
          }
          onBlur={(event: React.FocusEvent<HTMLInputElement>) =>
            onChange({
              ...value,
              binary: event.target.value.trim() || undefined,
            })
          }
          suffix={
            <Button
              type="text"
              size="small"
              aria-label={text.detect}
              icon={
                <RefreshCw size={14} aria-hidden="true" focusable="false" />
              }
              loading={checking}
              onClick={() => void check()}
            >
              <span className="detectLabel">{text.detect}</span>
            </Button>
          }
        />
      </div>
      {status?.runtime_path && (
        <div className="binaryStatus detected">
          <strong className="binaryStatusLabel">
            <Check size={14} aria-hidden="true" focusable="false" />
            {text.detected}
          </strong>{" "}
          <Tooltip title={status.runtime_path}>
            <code className="binaryPath">{status.runtime_path}</code>
          </Tooltip>{" "}
          <Tooltip title={text.copy}>
            <button
              className="copyPathButton"
              type="button"
              aria-label={text.copy}
              onClick={() => void copyPath(status.runtime_path!)}
            >
              <Copy size={13} aria-hidden="true" focusable="false" />
            </button>
          </Tooltip>
        </div>
      )}
      {!checking && status && !status.installed && (
        <p className="binaryStatus notDetected" role="status">
          <CircleAlert size={14} aria-hidden="true" focusable="false" />
          {text.notFound}
        </p>
      )}
      <div className="accountRow">
        <div className="accountState">
          <strong className="accountLabel">{text.account}</strong>
          <span
            className={
              status?.authenticated ? "connectedState" : "disconnectedState"
            }
          >
            {status?.authenticated ? (
              <Check size={14} aria-hidden="true" focusable="false" />
            ) : (
              <CircleAlert size={14} aria-hidden="true" focusable="false" />
            )}
            {status?.authenticated
              ? `${account}${identity ? ` · ${identity}` : ""}`
              : text.notConnected}
          </span>
        </div>
        <div className="accountAction">
          {!status?.authenticated && (
            <Button
              icon={
                <ExternalLink size={14} aria-hidden="true" focusable="false" />
              }
              disabled={!status?.installed}
              loading={connecting}
              onClick={() => void connect()}
            >
              {text.connect}
            </Button>
          )}
          {status?.authenticated && canDisconnect?.(status) && (
            <Button
              icon={<LogOut size={14} aria-hidden="true" focusable="false" />}
              onClick={() => void disconnect()}
            >
              {text.disconnect}
            </Button>
          )}
        </div>
      </div>
      {!status?.authenticated && status?.installed && (
        <p className="authHint">{text.authHint}</p>
      )}
      {status?.authenticated && (
        <p className="chatSettingsHint">{text.chatSettingsHint}</p>
      )}
      {error && (
        <p className="authHint" role="alert">
          {error}
        </p>
      )}
      {status && (
        <div className="capabilityPanel">
          <strong className="capabilityTitle">{text.capabilityTitle}</strong>
          <div className="capabilityGrid">
            <div className="capabilityItem">
              <Sparkles size={16} aria-hidden="true" focusable="false" />
              <span>
                <strong>{text.inheritedSkills}</strong>
                <small>
                  {status.capabilities?.qwenpaw_skills_projection
                    ? text.runtimeInherited
                    : text.notSupported}
                </small>
              </span>
            </div>
            <div className="capabilityItem">
              <Network size={16} aria-hidden="true" focusable="false" />
              <span>
                <strong>{text.inheritedMcp}</strong>
                <small>
                  {status.capabilities?.qwenpaw_mcp_projection
                    ? text.runtimeInherited
                    : text.notSupported}
                </small>
              </span>
            </div>
            <div className="capabilityItem">
              <ShieldCheck size={16} aria-hidden="true" focusable="false" />
              <span>
                <strong>{text.policyCompatibility}</strong>
                <small>
                  {status.capabilities?.mcp_tool_allowlist
                    ? text.toolAllowlistSupported
                    : text.policyLimited}
                </small>
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
