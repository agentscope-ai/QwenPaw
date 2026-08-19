// Chrome plugin UI. React and antd are provided by the QwenPaw console host.
import type * as ReactNS from "react";

import {
  resolveChromeLocale,
  t as translate,
  type ChromeLocale,
  type MessageKey,
} from "./locale";

const host = window.QwenPaw.host;
const React: typeof ReactNS = host.React;
const antd = host.antd;
const getApiUrl = host.getApiUrl;
const getApiToken = host.getApiToken;

const { Alert, Button, Collapse, Space, Spin, Typography, message } = antd;
const { Text, Title } = Typography;

type InstallMode = "unpacked" | "cws";
type ShortcutPlatform = "mac" | "windows" | "linux";
type InlineIconName = "chromeExtensions" | "copy" | "folderPlus" | "sliders";
type StatusKey =
  | "extension_dir"
  | "native_manifest_path"
  | "native_host_path"
  | "config_path";

interface ExtensionStatus {
  installed: boolean;
  install_mode: InstallMode | string | null;
  extension_id?: string;
  extension_dir?: string;
  native_manifest_path?: string;
  native_host_path?: string;
  config_path?: string;
  canonical_setup_url?: string;
  setup_phase?: string;
  recommended_action?: string;
  recovery_copy?: string;
  bridge_endpoint?: string;
  configured_endpoint?: string | null;
  bridge_endpoint_stale?: boolean;
  chrome_extensions_url?: string;
  native_host_repair_required?: boolean;
  native_host_repair_instruction?: string;
  version?: string | null;
}

interface SelfTestCheck {
  name: string;
  passed: boolean;
  status: string;
  severity?: "none" | "warn" | "error";
  code: string;
  message: string;
  repair_action: string;
}

interface SelfTestResult {
  status: string;
  checked_at?: string;
  checks: SelfTestCheck[];
}

interface CoreConnectionStatus {
  connected: boolean;
  connected_since?: string | null;
  extension_version?: string;
  last_self_test?: SelfTestResult | null;
}

interface ExtensionSetupRequest {
  install_mode: InstallMode;
  reset?: boolean;
}

interface OpenChromeExtensionsResult {
  opened: boolean;
  url: string;
  error?: string | null;
}

interface OpenExtensionFolderResult {
  opened: boolean;
  path: string;
  error?: string | null;
}

interface PathRow {
  key: StatusKey;
  label: MessageKey;
}

const PROBE_LABEL_KEYS: Record<string, MessageKey> = {
  extension_bridge: "checkExtensionBridge",
  nm_host: "checkNmHost",
  extension_assets: "checkExtensionAssets",
  bridge_lifecycle: "checkBridgeLifecycle",
  contract_drift: "checkContractDrift",
};

const REPAIR_KEYS: Record<string, MessageKey> = {
  reinstall_nm_host: "repairReinstallNmHost",
  reload_unpacked_extension: "repairReloadUnpackedExtension",
  wait_or_restart_chrome: "repairWaitOrRestartChrome",
  reload_extension: "repairReloadExtension",
  reload_or_update_extension: "repairReloadOrUpdateExtension",
};

const baseStyles: Record<string, ReactNS.CSSProperties> = {
  page: {
    minHeight: "100%",
    overflowY: "auto",
    padding: 24,
    background: "transparent",
  },
  shell: {
    width: "min(100%, 900px)",
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    flexWrap: "wrap",
  },
  titleRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    minWidth: 0,
  },
  chromeIcon: {
    position: "relative",
    width: 42,
    height: 42,
    flex: "0 0 42px",
    borderRadius: "50%",
    background:
      "radial-gradient(circle at center, #fff 0 18%, transparent 19%), " +
      "radial-gradient(circle at center, #1a73e8 0 36%, transparent 37%), " +
      "conic-gradient(#ea4335 0 34%, #fbbc04 0 67%, #34a853 0 100%)",
  },
  panel: {
    borderRadius: 8,
    padding: 24,
  },
  statusBlock: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: 20,
    alignItems: "start",
  },
  statusTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 8,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    flexShrink: 0,
  },
  statusCopy: {
    maxWidth: 610,
    lineHeight: 1.55,
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 8,
    flexWrap: "wrap",
  },
  section: {
    marginTop: 22,
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  methodGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 12,
  },
  methodTile: {
    minHeight: 128,
    padding: 14,
    borderRadius: 8,
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  disabledTile: {
    minHeight: 128,
    padding: 14,
    borderRadius: 8,
    display: "flex",
    flexDirection: "column",
    gap: 10,
    opacity: 0.72,
  },
  methodHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  badge: {
    minHeight: 22,
    padding: "1px 8px",
    borderRadius: 999,
    fontSize: 12,
    whiteSpace: "nowrap",
  },
  installSupportGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 16,
    alignItems: "stretch",
  },
  installBox: {
    flex: "1.55 1 520px",
    minWidth: 0,
    padding: 16,
    borderRadius: 8,
  },
  installTipsBox: {
    flex: "0.85 1 280px",
    minWidth: 0,
    padding: 16,
    borderRadius: 8,
  },
  installBoxHead: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 14,
    flexWrap: "wrap",
  },
  installBoxNote: {
    fontSize: 12,
    lineHeight: "18px",
    whiteSpace: "nowrap",
  },
  steps: {
    margin: 0,
    padding: 0,
    listStyle: "none",
    display: "flex",
    flexDirection: "column",
    gap: 13,
  },
  stepItem: {
    display: "grid",
    gridTemplateColumns: "28px minmax(0, 1fr)",
    gap: 10,
    alignItems: "start",
  },
  stepIndex: {
    width: 28,
    height: 28,
    borderRadius: 8,
    display: "grid",
    placeItems: "center",
    fontSize: 13,
    fontWeight: 700,
  },
  stepBody: {
    minWidth: 0,
  },
  stepLine: {
    marginTop: 5,
    display: "flex",
    alignItems: "center",
    gap: 6,
    flexWrap: "wrap",
    fontSize: 13,
    lineHeight: "26px",
  },
  stepControl: {
    height: 26,
    borderRadius: 7,
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "0 9px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 700,
    whiteSpace: "nowrap",
  },
  stepControlPrimary: {},
  stepControlIconOnly: {
    width: 34,
    margin: "0 4px",
    padding: 0,
    justifyContent: "center",
    gap: 0,
    verticalAlign: "middle",
  },
  stepControlBlue: {},
  stepControlPlaceholder: {
    cursor: "default",
  },
  inlineIcon: {
    width: 14,
    height: 14,
    flex: "0 0 14px",
  },
  shortcutBox: {
    width: "100%",
    minWidth: 0,
  },
  shortcutHead: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    flexWrap: "wrap",
    marginBottom: 14,
  },
  osTabs: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    width: "min(100%, 210px)",
    padding: 2,
    borderRadius: 8,
    overflow: "hidden",
  },
  osTab: {
    height: 26,
    border: 0,
    borderRadius: 6,
    background: "transparent",
    padding: "0 8px",
    cursor: "pointer",
    fontSize: 12,
    lineHeight: "26px",
    whiteSpace: "nowrap",
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  osTabActive: {
    fontWeight: 700,
  },
  shortcutSteps: {
    margin: 0,
    padding: "11px 12px",
    listStyle: "none",
    display: "grid",
    gap: 8,
    borderRadius: 8,
    fontSize: 13,
    lineHeight: "18px",
  },
  shortcutStep: {
    display: "grid",
    gridTemplateColumns: "18px minmax(0, 1fr)",
    gap: 8,
    alignItems: "start",
  },
  shortcutStepCopy: {
    display: "block",
    minWidth: 0,
    lineHeight: "26px",
  },
  tipDot: {
    width: 18,
    height: 18,
    borderRadius: 999,
    display: "inline-grid",
    placeItems: "center",
    fontSize: 11,
    fontWeight: 700,
    lineHeight: "18px",
  },
  checkGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12,
  },
  checkTile: {
    minHeight: 86,
    padding: 14,
    borderRadius: 8,
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  checkTitle: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  advanced: {
    marginTop: 18,
    borderRadius: 8,
  },
  advancedRows: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  advancedRow: {
    display: "grid",
    gridTemplateColumns: "minmax(128px, 180px) minmax(0, 1fr) auto",
    gap: 8,
    alignItems: "center",
  },
  advancedValue: {
    minWidth: 0,
    overflowWrap: "anywhere",
    wordBreak: "break-word",
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    lineHeight: 1.45,
    borderRadius: 4,
    padding: "4px 8px",
  },
};

function createStyles(
  token: Record<string, string>,
): Record<string, ReactNS.CSSProperties> {
  return {
    ...baseStyles,
    chromeIcon: {
      ...baseStyles.chromeIcon,
      boxShadow: token.boxShadowSecondary,
    },
    panel: {
      ...baseStyles.panel,
      background: token.colorBgContainer,
      border: `1px solid ${token.colorBorderSecondary}`,
      boxShadow: token.boxShadowTertiary,
    },
    methodTile: {
      ...baseStyles.methodTile,
      background: token.colorBgContainer,
      border: `1px solid ${token.colorBorderSecondary}`,
    },
    disabledTile: {
      ...baseStyles.disabledTile,
      background: token.colorFillQuaternary,
      border: `1px dashed ${token.colorBorder}`,
    },
    statusCopy: { ...baseStyles.statusCopy, color: token.colorTextSecondary },
    badge: {
      ...baseStyles.badge,
      border: `1px solid ${token.colorPrimaryBorder}`,
      color: token.colorPrimaryText,
      background: token.colorPrimaryBg,
    },
    installBox: {
      ...baseStyles.installBox,
      border: `1px solid ${token.colorBorderSecondary}`,
      background: token.colorFillQuaternary,
    },
    installTipsBox: {
      ...baseStyles.installTipsBox,
      border: `1px solid ${token.colorBorderSecondary}`,
      background: token.colorFillTertiary,
    },
    installBoxNote: {
      ...baseStyles.installBoxNote,
      color: token.colorTextTertiary,
    },
    stepIndex: {
      ...baseStyles.stepIndex,
      color: token.colorText,
      background: token.colorFillTertiary,
    },
    stepLine: { ...baseStyles.stepLine, color: token.colorTextSecondary },
    stepControl: {
      ...baseStyles.stepControl,
      border: `1px solid ${token.colorBorderSecondary}`,
      background: token.colorFillSecondary,
      color: token.colorText,
      boxShadow: token.boxShadowSecondary,
    },
    stepControlPrimary: {
      ...baseStyles.stepControlPrimary,
      borderColor: token.colorPrimary,
      background: token.colorPrimary,
      color: token.colorTextLightSolid,
    },
    stepControlBlue: {
      ...baseStyles.stepControlBlue,
      borderColor: token.colorPrimaryBorder,
      background: token.colorPrimaryBg,
      color: token.colorPrimaryText,
    },
    stepControlPlaceholder: {
      ...baseStyles.stepControlPlaceholder,
      color: token.colorTextSecondary,
      background: token.colorFillSecondary,
    },
    osTabs: {
      ...baseStyles.osTabs,
      border: `1px solid ${token.colorBorderSecondary}`,
      background: token.colorFillQuaternary,
    },
    osTab: { ...baseStyles.osTab, color: token.colorTextSecondary },
    osTabActive: {
      ...baseStyles.osTabActive,
      background: token.colorBgContainer,
      color: token.colorText,
      boxShadow: token.boxShadowSecondary,
    },
    shortcutSteps: {
      ...baseStyles.shortcutSteps,
      border: `1px solid ${token.colorBorderSecondary}`,
      background: token.colorBgContainer,
      color: token.colorTextSecondary,
    },
    tipDot: {
      ...baseStyles.tipDot,
      background: token.colorFillTertiary,
      color: token.colorText,
    },
    checkTile: {
      ...baseStyles.checkTile,
      border: `1px solid ${token.colorSuccessBorder}`,
      background: token.colorSuccessBg,
    },
    advanced: { ...baseStyles.advanced, background: token.colorBgContainer },
    advancedValue: {
      ...baseStyles.advancedValue,
      background: token.colorFillQuaternary,
      border: `1px solid ${token.colorBorderSecondary}`,
      color: token.colorText,
    },
  };
}

function useChromeStyles(): Record<string, ReactNS.CSSProperties> {
  const { token } = host.antd.theme.useToken();
  return React.useMemo(() => createStyles(token), [token]);
}

function ChromeSidebarIcon(): ReactNS.ReactElement {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 24 24"
      width={16}
      height={16}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      shapeRendering="geometricPrecision"
    >
      <circle cx={12} cy={12} r={9} />
      <circle cx={12} cy={12} r={3.375} />
      <line x1={12} y1={8.625} x2={20.344} y2={8.625} />
      <line x1={9.075} y1={13.688} x2={4.903} y2={6.459} />
      <line x1={14.925} y1={13.688} x2={10.753} y2={20.916} />
    </svg>
  );
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getApiToken?.();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(getApiUrl(path), {
    ...init,
    headers: {
      ...(init?.headers || {}),
      ...authHeaders(),
    },
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(
      typeof data?.detail === "string" ? data.detail : response.statusText,
    );
  }
  return data as T;
}

function getStatus(): Promise<ExtensionStatus> {
  return apiRequest<ExtensionStatus>("/chrome/install-status");
}

async function getCoreConnectionStatus(): Promise<CoreConnectionStatus | null> {
  try {
    return await apiRequest<CoreConnectionStatus>("/browser/chrome/status");
  } catch {
    return null;
  }
}

async function runCoreSelfTest(): Promise<SelfTestResult | null> {
  try {
    return await apiRequest<SelfTestResult>("/browser/chrome/self-test", {
      method: "POST",
    });
  } catch {
    return null;
  }
}

function setupExtension(
  payload: ExtensionSetupRequest,
): Promise<ExtensionStatus> {
  return apiRequest<ExtensionStatus>("/chrome/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function openChromeExtensionsPage(): Promise<OpenChromeExtensionsResult> {
  return apiRequest<OpenChromeExtensionsResult>(
    "/chrome/open-chrome-extensions",
    {
      method: "POST",
    },
  );
}

function openExtensionFolder(): Promise<OpenExtensionFolderResult> {
  return apiRequest<OpenExtensionFolderResult>(
    "/chrome/open-extension-folder",
    {
      method: "POST",
    },
  );
}

function formatConnectedSince(
  value: string | null | undefined,
  locale: ChromeLocale,
) {
  if (!value) {
    return translate(locale, "justNow");
  }
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return translate(locale, "justNow");
  }
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) {
    return translate(locale, "justNow");
  }
  if (minutes < 60) {
    return translate(locale, "minutesAgo", { count: minutes });
  }
  return translate(locale, "hoursAgo", { count: Math.floor(minutes / 60) });
}

function repairText(locale: ChromeLocale, action: string): string {
  const key = REPAIR_KEYS[action];
  return key ? translate(locale, key) : "";
}

function probeLabel(locale: ChromeLocale, name: string): string {
  const key = PROBE_LABEL_KEYS[name];
  return key
    ? translate(locale, key)
    : translate(locale, "checkUnknown", { name });
}

function checkNeedsAttention(check: SelfTestCheck): boolean {
  return (
    !check.passed || check.severity === "warn" || check.severity === "error"
  );
}

function StatusDot({ ready }: { ready: boolean }) {
  const { token } = host.antd.theme.useToken();
  const styles = useChromeStyles();
  return (
    <span
      aria-hidden="true"
      style={{
        ...styles.statusDot,
        background: ready ? token.colorSuccess : token.colorWarning,
      }}
    />
  );
}

function InlineIcon({ name, size }: { name: InlineIconName; size?: number }) {
  const styles = useChromeStyles();
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  const paths: Record<InlineIconName, ReactNS.ReactNode> = {
    chromeExtensions: (
      <>
        <path d="M8 6h12v12H8z" />
        <path d="M4 10h4M4 14h4" />
      </>
    ),
    copy: (
      <>
        <rect x="9" y="9" width="11" height="11" rx="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </>
    ),
    folderPlus: (
      <>
        <path d="M12 5v14" />
        <path d="M5 12h14" />
        <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
      </>
    ),
    sliders: (
      <>
        <path d="M4 7h10" />
        <path d="M20 7h-2" />
        <circle cx="16" cy="7" r="2" />
        <path d="M20 17H10" />
        <path d="M4 17h2" />
        <circle cx="8" cy="17" r="2" />
      </>
    ),
  };

  return (
    <svg
      viewBox="0 0 24 24"
      style={
        size
          ? {
              ...styles.inlineIcon,
              width: size,
              height: size,
              flex: `0 0 ${size}px`,
            }
          : styles.inlineIcon
      }
      {...common}
    >
      {paths[name]}
    </svg>
  );
}

function StepControl({
  icon,
  label,
  loading,
  onClick,
  tone = "default",
  iconOnly = false,
}: {
  icon: InlineIconName;
  label: string;
  loading?: boolean;
  onClick?: () => void;
  tone?: "blue" | "default" | "placeholder" | "primary";
  iconOnly?: boolean;
}) {
  const styles = useChromeStyles();
  const toneStyle =
    tone === "primary"
      ? styles.stepControlPrimary
      : tone === "blue"
      ? styles.stepControlBlue
      : tone === "placeholder"
      ? styles.stepControlPlaceholder
      : null;

  return (
    <Button
      aria-label={iconOnly ? label : undefined}
      loading={loading}
      onClick={onClick}
      style={{
        ...styles.stepControl,
        ...toneStyle,
        ...(iconOnly ? styles.stepControlIconOnly : null),
      }}
      title={iconOnly ? label : undefined}
      type="text"
    >
      <InlineIcon name={icon} size={iconOnly ? 16 : undefined} />
      {iconOnly ? null : label}
    </Button>
  );
}

function detectShortcutPlatform(): ShortcutPlatform {
  const platform = window.navigator?.platform || "";
  const userAgent = window.navigator?.userAgent || "";
  const value = `${platform} ${userAgent}`.toLowerCase();
  if (value.includes("mac")) {
    return "mac";
  }
  if (value.includes("win")) {
    return "windows";
  }
  return "linux";
}

function AdvancedInfo({
  locale,
  onCopy,
  status,
}: {
  locale: ChromeLocale;
  onCopy: (value: string) => void;
  status: ExtensionStatus | null;
}) {
  const styles = useChromeStyles();
  const rows: PathRow[] = [
    { key: "extension_dir", label: "extensionDir" },
    { key: "native_manifest_path", label: "nativeManifest" },
    { key: "native_host_path", label: "nativeHost" },
    { key: "config_path", label: "config" },
  ];
  const wsUrl = status?.bridge_endpoint || "not ready";

  return (
    <Collapse
      style={styles.advanced}
      items={[
        {
          key: "advanced",
          label: translate(locale, "advancedInfo"),
          children: (
            <div style={styles.advancedRows}>
              {rows.map((row) => {
                const value = status?.[row.key] || "-";
                return (
                  <div key={row.key} style={styles.advancedRow}>
                    <Text type="secondary">{translate(locale, row.label)}</Text>
                    <code style={styles.advancedValue}>{value}</code>
                    <Button
                      disabled={!status?.[row.key]}
                      onClick={() => onCopy(value)}
                    >
                      {translate(locale, "copyPath")}
                    </Button>
                  </div>
                );
              })}
              <div style={styles.advancedRow}>
                <Text type="secondary">
                  {translate(locale, "bridgeEndpoint")}
                </Text>
                <code style={styles.advancedValue}>{wsUrl}</code>
                <Button onClick={() => onCopy(wsUrl)}>
                  {translate(locale, "copyPath")}
                </Button>
              </div>
            </div>
          ),
        },
      ]}
    />
  );
}

function ChromeSetupPage() {
  const styles = useChromeStyles();
  const locale = resolveChromeLocale();
  const [status, setStatus] = React.useState<ExtensionStatus | null>(null);
  const [coreStatus, setCoreStatus] =
    React.useState<CoreConnectionStatus | null>(null);
  const [selfTest, setSelfTest] = React.useState<SelfTestResult | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [setupLoading, setSetupLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [silentPrepareStarted, setSilentPrepareStarted] = React.useState(false);
  const [shortcutPlatform, setShortcutPlatform] =
    React.useState<ShortcutPlatform>(() => detectShortcutPlatform());

  const refreshStatus = React.useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setLoading(true);
      }
      setError(null);
      try {
        const [next, nextCoreStatus] = await Promise.all([
          getStatus(),
          getCoreConnectionStatus(),
        ]);
        setStatus(next);
        setCoreStatus(nextCoreStatus);
        return next;
      } catch (err) {
        const messageText = err instanceof Error ? err.message : String(err);
        setError(messageText);
        return null;
      } finally {
        if (!options?.silent) {
          setLoading(false);
        }
      }
    },
    [],
  );

  React.useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const prepareLocalFiles = React.useCallback(
    async (options?: { silent?: boolean; refresh?: boolean }) => {
      if (status?.extension_dir && status.installed && !options?.refresh) {
        return status;
      }
      setSetupLoading(true);
      setError(null);
      try {
        const next = await setupExtension({
          install_mode: "unpacked",
          reset: false,
        });
        setStatus(next);
        if (!options?.silent) {
          if (next.native_host_repair_required) {
            message.error(
              next.native_host_repair_instruction ||
                translate(locale, "installFailed"),
            );
          } else {
            message.success(
              translate(
                locale,
                status?.native_host_repair_required
                  ? "repairSuccess"
                  : "installSuccess",
              ),
            );
          }
        }
        return next;
      } catch (err) {
        const messageText = err instanceof Error ? err.message : String(err);
        setError(messageText);
        if (!options?.silent) {
          message.error(translate(locale, "installFailed"));
        }
        return null;
      } finally {
        setSetupLoading(false);
      }
    },
    [locale, status],
  );

  const copyValue = React.useCallback(
    async (value: string, feedback: MessageKey = "copied") => {
      try {
        if (!navigator.clipboard?.writeText) {
          throw new Error("clipboard API is unavailable");
        }
        await navigator.clipboard.writeText(value);
        message.success(translate(locale, feedback));
        return true;
      } catch {
        message.error(translate(locale, "copyFailed"));
        return false;
      }
    },
    [locale],
  );

  const handleCopyPath = React.useCallback(async () => {
    const next = await prepareLocalFiles({ refresh: true });
    if (next?.extension_dir) {
      await copyValue(next.extension_dir);
    }
  }, [copyValue, prepareLocalFiles]);

  const copyChromeExtensionsUrl = React.useCallback(
    async (fallback = false) =>
      copyValue(
        status?.chrome_extensions_url ?? "chrome://extensions",
        fallback ? "chromeExtensionsCopiedFallback" : "chromeExtensionsCopied",
      ),
    [copyValue, status?.chrome_extensions_url],
  );

  const handleOpenChrome = React.useCallback(async () => {
    try {
      const result = await openChromeExtensionsPage();
      if (result.opened) {
        return;
      }
    } catch {
      // The copied address is the safe fallback if the local backend is gone.
    }
    await copyChromeExtensionsUrl(true);
  }, [copyChromeExtensionsUrl]);

  const shortcutTipsSteps: Record<ShortcutPlatform, [MessageKey, MessageKey]> =
    {
      mac: ["shortcutMacStep1", "shortcutMacStep2"],
      windows: ["shortcutWindowsStep1", "shortcutWindowsStep2"],
      linux: ["shortcutLinuxStep1", "shortcutLinuxStep2"],
    };

  React.useEffect(() => {
    if (loading || silentPrepareStarted || status?.extension_dir) {
      return;
    }
    setSilentPrepareStarted(true);
    void prepareLocalFiles({ silent: true });
  }, [loading, prepareLocalFiles, silentPrepareStarted, status?.extension_dir]);

  const isConnected = Boolean(status?.installed && coreStatus?.connected);
  const needsRepair = Boolean(
    status?.native_host_repair_required && !coreStatus?.connected,
  );
  const isAwaitingConnection = Boolean(
    status?.installed && !needsRepair && !coreStatus?.connected,
  );

  React.useEffect(() => {
    if (!isConnected) {
      setSelfTest(null);
      return;
    }
    let cancelled = false;
    void runCoreSelfTest().then((result) => {
      if (!cancelled) {
        setSelfTest(result ?? coreStatus?.last_self_test ?? null);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [isConnected, coreStatus?.last_self_test]);

  React.useEffect(() => {
    if (isConnected) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshStatus({ silent: true });
    }, 5000);
    return () => {
      window.clearInterval(timer);
    };
  }, [isConnected, refreshStatus]);

  return (
    <div style={styles.page}>
      <div style={styles.shell}>
        <div style={styles.panel}>
          <div style={styles.statusBlock}>
            <div>
              <div style={styles.header}>
                <div style={styles.titleRow}>
                  <span style={styles.chromeIcon} />
                  <div>
                    <Title level={3} style={{ margin: 0 }}>
                      {translate(locale, "pageTitle")}
                    </Title>
                    <Text type="secondary">
                      {translate(locale, "pageSubtitle")}
                    </Text>
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 22 }}>
                <div style={styles.statusTitleRow}>
                  {isConnected || isAwaitingConnection ? (
                    <StatusDot ready={isConnected} />
                  ) : null}
                  <Title level={4} style={{ margin: 0 }}>
                    {translate(
                      locale,
                      isConnected
                        ? "readyTitle"
                        : needsRepair
                        ? "repairTitle"
                        : isAwaitingConnection
                        ? "awaitingTitle"
                        : "installTitle",
                    )}
                  </Title>
                </div>
                <div style={styles.statusCopy}>
                  {needsRepair
                    ? translate(locale, "repairDescription")
                    : isConnected
                    ? translate(locale, "readyDescription", {
                        version:
                          coreStatus?.extension_version ||
                          translate(locale, "versionUnknown"),
                        connectedSince: formatConnectedSince(
                          coreStatus?.connected_since,
                          locale,
                        ),
                      })
                    : isAwaitingConnection
                    ? translate(locale, "awaitingDescription")
                    : status?.recovery_copy ||
                      translate(locale, "installDescription")}
                </div>
              </div>
            </div>
            <div style={styles.actions}>
              {isConnected ? (
                <>
                  <Button
                    loading={loading}
                    onClick={() => void refreshStatus()}
                  >
                    {translate(locale, "refreshStatus")}
                  </Button>
                  <Button
                    type="primary"
                    onClick={() => void handleOpenChrome()}
                  >
                    {translate(locale, "openChrome")}
                  </Button>
                </>
              ) : needsRepair ? (
                <Button
                  type="primary"
                  loading={setupLoading}
                  onClick={() => void prepareLocalFiles({ refresh: true })}
                >
                  {translate(locale, "repairBrowserConnector")}
                </Button>
              ) : (
                <Button
                  type="primary"
                  loading={loading}
                  onClick={() => void refreshStatus()}
                >
                  {translate(locale, "installedRefresh")}
                </Button>
              )}
            </div>
          </div>

          {error ? (
            <Alert
              showIcon
              type="error"
              message={error}
              style={{ marginTop: 16 }}
            />
          ) : null}

          {needsRepair && status?.native_host_repair_instruction ? (
            <Alert
              showIcon
              type="error"
              message={status?.native_host_repair_instruction}
              style={{ marginTop: 16 }}
            />
          ) : null}

          {isConnected ? (
            <div style={styles.section}>
              <Text strong>{translate(locale, "checksTitle")}</Text>
              {selfTest?.checks?.length ? (
                <div style={styles.checkGrid}>
                  {selfTest.checks
                    .filter((check) => check.name !== "semantic_control")
                    .map((check) => {
                      const needsAttention = checkNeedsAttention(check);
                      return (
                        <div key={check.name} style={styles.checkTile}>
                          <div style={styles.checkTitle}>
                            <StatusDot ready={!needsAttention} />
                            <Text strong>{probeLabel(locale, check.name)}</Text>
                          </div>
                          <Text type="secondary">
                            {needsAttention
                              ? `${check.message} ${repairText(
                                  locale,
                                  check.repair_action,
                                )}`.trim()
                              : translate(locale, "checkReady")}
                          </Text>
                        </div>
                      );
                    })}
                </div>
              ) : (
                <Text type="secondary">
                  {translate(locale, "checksPending")}
                </Text>
              )}
            </div>
          ) : (
            <>
              <div style={styles.section}>
                <Text strong>{translate(locale, "installMethodsTitle")}</Text>
                <div style={styles.methodGrid}>
                  <div style={styles.methodTile}>
                    <div style={styles.methodHeader}>
                      <Text strong>
                        {translate(locale, "localMethodTitle")}
                      </Text>
                      <span style={styles.badge}>
                        {translate(locale, "recommendedBadge")}
                      </span>
                    </div>
                    <Text type="secondary">
                      {translate(locale, "localMethodDescription")}
                    </Text>
                    <Button
                      type="primary"
                      onClick={() => void copyChromeExtensionsUrl()}
                    >
                      <InlineIcon name="copy" />
                      {translate(locale, "copyChromeExtensionsPage")}
                    </Button>
                  </div>
                  <div style={styles.disabledTile} aria-disabled="true">
                    <div style={styles.methodHeader}>
                      <Text strong>
                        {translate(locale, "chromeWebStoreTitle")}
                      </Text>
                      <span style={styles.badge}>
                        {translate(locale, "comingSoon")}
                      </span>
                    </div>
                    <Text type="secondary">
                      {translate(locale, "chromeWebStoreDescription")}
                    </Text>
                    <Button disabled>{translate(locale, "comingSoon")}</Button>
                  </div>
                </div>
              </div>

              <div style={styles.section}>
                <div style={styles.installSupportGrid}>
                  <div style={styles.installBox}>
                    <div style={styles.installBoxHead}>
                      <Text strong>{translate(locale, "localStepsTitle")}</Text>
                      <span style={styles.installBoxNote}>
                        {translate(locale, "localStepsOnce")}
                      </span>
                    </div>
                    <ol style={styles.steps}>
                      <li style={styles.stepItem}>
                        <span style={styles.stepIndex}>1</span>
                        <div style={styles.stepBody}>
                          <Text strong>
                            {translate(locale, "openExtensionsStepTitle")}
                          </Text>
                          <div style={styles.stepLine}>
                            {translate(locale, "openExtensionsPrefix")}
                            <StepControl
                              icon="copy"
                              label={translate(locale, "openExtensionsAction")}
                              onClick={() => void copyChromeExtensionsUrl()}
                              tone="blue"
                            />
                            {translate(locale, "openExtensionsSuffix")}
                          </div>
                        </div>
                      </li>
                      <li style={styles.stepItem}>
                        <span style={styles.stepIndex}>2</span>
                        <div style={styles.stepBody}>
                          <Text strong>
                            {translate(locale, "developerModeStepTitle")}
                          </Text>
                          <div style={styles.stepLine}>
                            {translate(locale, "developerModePrefix")}
                            <StepControl
                              icon="sliders"
                              label={translate(locale, "developerModeAction")}
                              tone="placeholder"
                            />
                            {translate(locale, "developerModeSuffix")}
                          </div>
                        </div>
                      </li>
                      <li style={styles.stepItem}>
                        <span style={styles.stepIndex}>3</span>
                        <div style={styles.stepBody}>
                          <Text strong>
                            {translate(locale, "loadUnpackedStepTitle")}
                          </Text>
                          <div style={styles.stepLine}>
                            {translate(locale, "loadUnpackedPrefix")}
                            <StepControl
                              icon="folderPlus"
                              label={translate(locale, "loadUnpackedAction")}
                              tone="placeholder"
                            />
                            {translate(locale, "loadUnpackedSuffix")}
                          </div>
                        </div>
                      </li>
                      <li style={styles.stepItem}>
                        <span style={styles.stepIndex}>4</span>
                        <div style={styles.stepBody}>
                          <Text strong>
                            {translate(locale, "pastePathStepTitle")}
                          </Text>
                          <div style={styles.stepLine}>
                            {translate(locale, "pastePathGuide")}
                          </div>
                        </div>
                      </li>
                    </ol>
                  </div>

                  <aside
                    aria-label={translate(locale, "shortcutTipsTitle")}
                    style={styles.installTipsBox}
                  >
                    <div style={styles.installBoxHead}>
                      <Text strong>
                        {translate(locale, "shortcutTipsTitle")}
                      </Text>
                      <span style={styles.installBoxNote}>
                        {translate(locale, "shortcutTipsScope")}
                      </span>
                    </div>
                    <div style={styles.shortcutBox}>
                      <div style={styles.shortcutHead}>
                        <Text strong>{translate(locale, "currentSystem")}</Text>
                        <div style={styles.osTabs} role="tablist">
                          {(
                            [
                              ["mac", "macOS"],
                              ["windows", "Windows"],
                              ["linux", "Linux"],
                            ] as const
                          ).map(([platform, label]) => (
                            <button
                              key={platform}
                              onClick={() => setShortcutPlatform(platform)}
                              style={{
                                ...styles.osTab,
                                ...(shortcutPlatform === platform
                                  ? styles.osTabActive
                                  : null),
                              }}
                              type="button"
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <ol style={styles.shortcutSteps}>
                        <li style={styles.shortcutStep}>
                          <span style={styles.tipDot}>1</span>
                          <div style={styles.shortcutStepCopy}>
                            <span>
                              {translate(locale, "shortcutCopyPathPrefix")}
                            </span>
                            <StepControl
                              icon="copy"
                              label={translate(locale, "qwenpawExtensionPath")}
                              loading={setupLoading}
                              onClick={() => void handleCopyPath()}
                              tone="blue"
                              iconOnly
                            />
                            <span>
                              {translate(locale, "shortcutCopyPathSuffix")}
                            </span>
                          </div>
                        </li>
                        {shortcutTipsSteps[shortcutPlatform].map(
                          (key, index) => (
                            <li key={key} style={styles.shortcutStep}>
                              <span style={styles.tipDot}>{index + 2}</span>
                              <span>{translate(locale, key)}</span>
                            </li>
                          ),
                        )}
                      </ol>
                    </div>
                  </aside>
                </div>
              </div>
            </>
          )}

          <AdvancedInfo
            locale={locale}
            onCopy={(value) => void copyValue(value)}
            status={status}
          />
        </div>
        {loading && !status ? <Spin /> : null}
      </div>
    </div>
  );
}

window.QwenPaw.registerRoutes?.("chrome", [
  {
    path: "/plugin/chrome",
    component: ChromeSetupPage,
    label: translate(resolveChromeLocale(), "routeLabel"),
    icon: <ChromeSidebarIcon />,
    priority: 40,
  },
]);
