import type * as ReactNS from "react";

import { resolveLocale, t, type ComputerUseLocale } from "./locale";
import manifest from "../../plugin.json";

const host = window.QwenPaw.host;
const React: typeof ReactNS = host.React;
const {
  Badge,
  Button,
  Empty,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tabs,
  Tooltip,
  Typography,
  message,
} = host.antd;
const {
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} = host.antdIcons;
const { Text, Title } = Typography;

type RuntimeStatus = { runtime_available: boolean; enabled: boolean };

type PersistentAccess = {
  canonical_app_id: string;
  display_name: string;
};

type Approval = {
  requestId: string;
  sessionId: string;
  toolParams: Record<string, unknown>;
};

type ApprovalDecision = "deny" | "session" | "always";

type ApprovalCardProps = {
  approval: Approval;
  onResolved: () => void;
};

function storedLocale() {
  try {
    return resolveLocale(localStorage.getItem("language"));
  } catch {
    return resolveLocale(undefined);
  }
}

async function requestJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = host.fetch
    ? await host.fetch(path, init)
    : await fetch(host.getApiUrl(path), {
        ...init,
        headers: {
          ...(init?.headers || {}),
          ...(host.getApiToken()
            ? { Authorization: `Bearer ${host.getApiToken()}` }
            : {}),
        },
      });
  const content = await response.text();
  let payload: unknown = null;
  try {
    payload = content ? JSON.parse(content) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail?: unknown }).detail
        : undefined;
    throw new Error(
      typeof detail === "string" ? detail : `HTTP ${response.status}`,
    );
  }
  return payload;
}

function applicationName(
  approval: Approval,
  selectedLocale: ComputerUseLocale,
) {
  const displayName = approval.toolParams.display_name;
  if (typeof displayName === "string" && displayName.trim()) {
    return displayName;
  }
  const appId = approval.toolParams.canonical_app_id;
  return typeof appId === "string" && appId.trim()
    ? appId
    : t(selectedLocale, "unknownApplication");
}

// Surface the executable's on-disk location so the user can tell exactly
// which application is asking for access. Identifiers arrive as
// ``process:<path>``; strip only the scheme and keep the drive-qualified
// path intact (the drive letter's own colon must be preserved).
function applicationPath(approval: Approval) {
  const appId = approval.toolParams.canonical_app_id;
  if (typeof appId !== "string" || !appId.trim()) {
    return "";
  }
  const separator = appId.indexOf(":");
  if (separator !== -1 && appId.slice(0, separator) === "process") {
    return appId.slice(separator + 1);
  }
  return appId;
}

function ComputerUseApprovalCard({ approval, onResolved }: ApprovalCardProps) {
  const selectedLocale = resolveLocale(host.useLocale?.());
  const [pending, setPending] = React.useState<ApprovalDecision | null>(null);
  const risk =
    typeof approval.toolParams.risk === "string"
      ? approval.toolParams.risk
      : "";
  const warning =
    typeof approval.toolParams.warning === "string"
      ? approval.toolParams.warning
      : "";
  const appName = applicationName(approval, selectedLocale);
  const appPath = applicationPath(approval);

  const decide = async (decision: ApprovalDecision) => {
    setPending(decision);
    try {
      await requestJson("/computer-use/session/pending/decision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: approval.sessionId,
          request_id: approval.requestId,
          decision,
        }),
      });
      message.success(t(selectedLocale, `decision.${decision}`));
      onResolved();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t(selectedLocale, "failed"),
      );
    } finally {
      setPending(null);
    }
  };

  return React.createElement(
    host.antd.Card,
    { size: "small", bordered: true, style: { borderRadius: 8 } },
    React.createElement(
      "div",
      { style: { display: "grid", gap: 14 } },
      React.createElement(
        "div",
        { style: { display: "grid", gap: 4 } },
        React.createElement(
          Space,
          { size: 8 },
          React.createElement(SafetyCertificateOutlined),
          React.createElement(
            Text,
            { strong: true },
            t(selectedLocale, "approvalTitle"),
          ),
        ),
        React.createElement(Text, { strong: true }, appName),
        appPath && appPath !== appName
          ? React.createElement(
              "div",
              {
                style: {
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  minWidth: 0,
                  maxWidth: "100%",
                  padding: "2px 8px",
                  borderRadius: 6,
                  background: "rgba(140, 140, 140, 0.1)",
                },
              },
              React.createElement(FolderOpenOutlined, {
                style: { color: "#8c8c8c", flexShrink: 0, fontSize: 12 },
              }),
              React.createElement(
                Text,
                {
                  type: "secondary",
                  copyable: { text: appPath },
                  ellipsis: { tooltip: appPath },
                  style: {
                    fontSize: 12,
                    minWidth: 0,
                    fontFamily:
                      "'SFMono-Regular', Consolas, 'Liberation Mono', " +
                      "Menlo, monospace",
                  },
                },
                appPath,
              ),
            )
          : null,
        risk
          ? React.createElement(
              Text,
              { type: "secondary" },
              `${t(selectedLocale, "risk")}: ${risk}`,
            )
          : null,
        warning
          ? React.createElement(Text, { type: "warning" }, warning)
          : null,
      ),
      React.createElement(
        Space,
        { size: 8, wrap: true },
        React.createElement(
          Button,
          {
            danger: true,
            icon: React.createElement(CloseOutlined),
            loading: pending === "deny",
            disabled: pending !== null,
            onClick: () => void decide("deny"),
          },
          t(selectedLocale, "deny"),
        ),
        React.createElement(
          Button,
          {
            icon: React.createElement(CheckOutlined),
            loading: pending === "session",
            disabled: pending !== null,
            onClick: () => void decide("session"),
          },
          t(selectedLocale, "allowSession"),
        ),
        React.createElement(
          Button,
          {
            type: "primary",
            icon: React.createElement(CheckOutlined),
            loading: pending === "always",
            disabled: pending !== null,
            onClick: () => void decide("always"),
          },
          t(selectedLocale, "allowAlways"),
        ),
      ),
    ),
  );
}

function ComputerUsePage() {
  const selectedLocale = resolveLocale(host.useLocale?.());
  const currentSession = host.useCurrentSession?.();
  const sessionId = currentSession?.id ?? host.getCurrentSessionId?.() ?? null;
  const [runtime, setRuntime] = React.useState<RuntimeStatus | null>(null);
  const [access, setAccess] = React.useState<PersistentAccess[]>([]);
  const [enabled, setEnabled] = React.useState(true);
  const [toggling, setToggling] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [action, setAction] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const [runtimePayload, accessPayload] = await Promise.all([
        requestJson("/computer-use/status"),
        requestJson("/computer-use/access"),
      ]);
      setRuntime(runtimePayload as RuntimeStatus);
      setAccess((accessPayload as { access: PersistentAccess[] }).access || []);
      setEnabled((runtimePayload as RuntimeStatus).enabled !== false);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t(selectedLocale, "failed"),
      );
    } finally {
      setLoading(false);
    }
  }, [selectedLocale]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const revoke = async (item: PersistentAccess) => {
    setAction(`revoke:${item.canonical_app_id}`);
    try {
      await requestJson("/computer-use/access", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canonical_app_id: item.canonical_app_id }),
      });
      await refresh();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t(selectedLocale, "failed"),
      );
    } finally {
      setAction(null);
    }
  };

  const toggleFeature = async (next: boolean) => {
    setToggling(true);
    try {
      await requestJson("/computer-use/feature", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next, session_id: sessionId }),
      });
      setEnabled(next);
      message.success(t(selectedLocale, next ? "enabledMsg" : "disabledMsg"));
      await refresh();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t(selectedLocale, "failed"),
      );
    } finally {
      setToggling(false);
    }
  };

  const columns = [
    {
      title: t(selectedLocale, "application"),
      dataIndex: "display_name",
      key: "display_name",
      render: (value: string) =>
        React.createElement(Text, { strong: true }, value),
    },
    {
      title: t(selectedLocale, "applicationId"),
      dataIndex: "canonical_app_id",
      key: "canonical_app_id",
      render: (value: string) =>
        React.createElement(Text, { code: true }, value),
    },
    {
      key: "actions",
      width: 56,
      render: (_: unknown, item: PersistentAccess) =>
        React.createElement(
          Popconfirm,
          {
            title: t(selectedLocale, "revokeConfirm"),
            onConfirm: () => void revoke(item),
          },
          React.createElement(
            Tooltip,
            { title: t(selectedLocale, "revoke") },
            React.createElement(Button, {
              type: "text",
              danger: true,
              shape: "circle",
              icon: React.createElement(DeleteOutlined),
              loading: action === `revoke:${item.canonical_app_id}`,
              "aria-label": t(selectedLocale, "revoke"),
            }),
          ),
        ),
    },
  ];
  const runtimeReady = runtime?.runtime_available === true;

  return React.createElement(
    "main",
    {
      style: {
        maxWidth: 1080,
        margin: "24px auto",
        padding: "0 24px 40px",
        display: "grid",
        gap: 28,
      },
    },
    React.createElement(
      "header",
      {
        style: {
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          paddingBottom: 16,
          borderBottom: "1px solid rgba(0, 0, 0, 0.08)",
        },
      },
      React.createElement(
        "div",
        { style: { display: "grid", gap: 6 } },
        React.createElement(
          Space,
          { align: "baseline", size: 8 },
          React.createElement(
            Title,
            { level: 3, style: { margin: 0 } },
            t(selectedLocale, "title"),
          ),
          React.createElement(
            Text,
            { type: "secondary", style: { fontSize: 12 } },
            `${t(selectedLocale, "version")} ${manifest.version}`,
          ),
        ),
        React.createElement(Badge, {
          status: runtimeReady ? "success" : "error",
          text: t(selectedLocale, runtimeReady ? "ready" : "unavailable"),
        }),
      ),
      React.createElement(
        Space,
        { size: 8 },
        React.createElement(
          Tooltip,
          { title: t(selectedLocale, "refresh") },
          React.createElement(Button, {
            type: "text",
            shape: "circle",
            icon: React.createElement(ReloadOutlined),
            loading,
            onClick: () => void refresh(),
            "aria-label": t(selectedLocale, "refresh"),
          }),
        ),
        React.createElement(
          Space,
          { size: 8, align: "center" },
          React.createElement(
            Text,
            { type: "secondary", style: { fontSize: 13 } },
            t(selectedLocale, "feature"),
          ),
          React.createElement(Switch, {
            checked: enabled,
            loading: toggling,
            disabled: !runtimeReady,
            onChange: (next: boolean) => void toggleFeature(next),
            "aria-label": t(selectedLocale, "feature"),
          }),
        ),
      ),
    ),
    React.createElement(Tabs, {
      defaultActiveKey: "access",
      items: [
        {
          key: "access",
          label: t(selectedLocale, "accessManagement"),
          children: React.createElement(Table, {
            rowKey: "canonical_app_id",
            columns,
            dataSource: access,
            pagination: false,
            size: "middle",
            locale: {
              emptyText: React.createElement(Empty, {
                image: Empty.PRESENTED_IMAGE_SIMPLE,
                description: t(selectedLocale, "empty"),
              }),
            },
          }),
        },
      ],
    }),
  );
}

window.QwenPaw.chat?.approval.render(
  "computer-use",
  "computer_use_app_access",
  ComputerUseApprovalCard,
);

window.QwenPaw.registerRoutes?.("computer-use", [
  {
    path: "/plugin/computer-use",
    component: ComputerUsePage,
    label: t(storedLocale(), "routeLabel"),
    icon: "🖥️",
    priority: 43,
  },
]);
