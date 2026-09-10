import { MobileAlert } from "@/components/MobileAlert";
import { FileLock2, Globe2, ScanSearch, ShieldCheck, TerminalSquare } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Switch } from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors } from "../../theme/tokens";
import { ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";
import { DynamicConfigSheet } from "./DynamicConfigSheet";

interface SecurityState {
  sandbox?: Record<string, unknown>;
  toolGuard?: Record<string, unknown>;
  fileGuard?: Record<string, unknown>;
  scanner?: Record<string, unknown>;
  allowHosts?: Record<string, unknown>;
  unsupported: Set<string>;
}

export function SecuritySettings({ connection }: { connection: Connection }) {
  const [state, setState] = useState<SecurityState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [editingHosts, setEditingHosts] = useState(false);

  const load = useCallback(async () => {
    const client = new QwenPawClient(connection);
    const entries = await Promise.allSettled([
      client.inspectModule("/config/security/sandbox"),
      client.inspectModule("/config/security/tool-guard"),
      client.inspectModule("/config/security/file-guard"),
      client.inspectModule("/config/security/skill-scanner"),
      client.inspectModule("/config/security/allow-no-auth-hosts"),
    ]);
    const keys = ["sandbox", "toolGuard", "fileGuard", "scanner", "allowHosts"] as const;
    const next: SecurityState = { unsupported: new Set() };
    entries.forEach((result, index) => {
      const key = keys[index];
      if (result.status === "fulfilled" && isRecord(result.value)) {
        next[key] = result.value;
      } else {
        next.unsupported.add(key);
      }
    });
    if (next.unsupported.size === keys.length) {
      const first = entries.find((result) => result.status === "rejected");
      setError(first?.status === "rejected"
        ? errorMessage(first.reason)
        : "当前 QwenPaw 不支持安全设置 API");
      return;
    }
    setError(null);
    setState(next);
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const update = useCallback(async (
    key: Exclude<keyof SecurityState, "unsupported">,
    path: string,
    next: Record<string, unknown>,
  ) => {
    if (saving) return;
    setSaving(key);
    try {
      const result = await new QwenPawClient(connection)
        .mutateModule<Record<string, unknown>>(path, "PUT", next);
      setState((current) => current ? { ...current, [key]: result } : current);
    } catch (reason) {
      MobileAlert.alert("安全设置保存失败", errorMessage(reason));
    } finally {
      setSaving(null);
    }
  }, [connection, saving]);

  const chooseScannerMode = useCallback(() => {
    if (!state?.scanner || saving) return;
    const save = (mode: string) => void update(
      "scanner",
      "/config/security/skill-scanner",
      { ...state.scanner, mode },
    );
    MobileAlert.alert("Skill Scanner 模式", "选择安装或更新 Skill 时的处理方式。", [
      { text: "阻止风险 Skill", onPress: () => save("block") },
      { text: "仅警告", onPress: () => save("warn") },
      { text: "关闭扫描", style: "destructive", onPress: () => save("off") },
      { text: "取消", style: "cancel" },
    ]);
  }, [saving, state, update]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!state) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="执行隔离">
        <SecurityToggle
          disabled={saving !== null || state.unsupported.has("sandbox")}
          icon={TerminalSquare}
          label="Sandbox"
          onChange={(enabled) => void update(
            "sandbox",
            "/config/security/sandbox",
            { enabled },
          )}
          subtitle={state.unsupported.has("sandbox")
            ? "当前 QwenPaw 不支持"
            : stringValue(state.sandbox?.reason) || "隔离命令和文件操作"}
          value={state.sandbox?.enabled === true}
        />
        <SecurityToggle
          disabled={saving !== null || state.unsupported.has("toolGuard")}
          icon={ShieldCheck}
          label="Tool Guard"
          onChange={(enabled) => state.toolGuard && void update(
            "toolGuard",
            "/config/security/tool-guard",
            { ...state.toolGuard, enabled },
          )}
          subtitle={state.unsupported.has("toolGuard")
            ? "当前 QwenPaw 不支持"
            : "检测并拦截高风险工具调用"}
          value={state.toolGuard?.enabled === true}
        />
        <SecurityToggle
          disabled={saving !== null || state.unsupported.has("fileGuard")}
          icon={FileLock2}
          label="File Guard"
          onChange={(enabled) => state.fileGuard && void update(
            "fileGuard",
            "/config/security/file-guard",
            { ...state.fileGuard, enabled },
          )}
          subtitle={state.unsupported.has("fileGuard")
            ? "当前 QwenPaw 不支持"
            : "保护工作区外的敏感路径"}
          value={state.fileGuard?.enabled === true}
        />
      </IosGroup>
      <IosGroup title="供应链安全">
        <IosRow
          icon={ScanSearch}
          label="Skill Scanner"
          onPress={state.unsupported.has("scanner") ? undefined : chooseScannerMode}
          subtitle={state.unsupported.has("scanner")
            ? "当前 QwenPaw 不支持"
            : "安装前扫描 Skill 内容"}
          trailing={scannerLabel(state.scanner?.mode)}
        />
      </IosGroup>
      <IosGroup title="网络访问">
        <IosRow
          icon={Globe2}
          iconTone="ink"
          label="免认证 Host"
          onPress={state.unsupported.has("allowHosts") ? undefined : () => setEditingHosts(true)}
          subtitle="仅为明确可信的内部服务绕过认证"
          trailing={Array.isArray(state.allowHosts?.hosts)
            ? `${state.allowHosts.hosts.length} 项`
            : "不支持"}
        />
      </IosGroup>
      <ModuleFooter>安全设置会立即作用于当前 QwenPaw；关闭前请确认运行环境可信。</ModuleFooter>
      {editingHosts ? (
        <DynamicConfigSheet
          fields={[{
            name: "hosts",
            label: "可信 Host",
            type: "textarea",
            help: "每行一个 Host 或域名，不要填写路径。",
          }]}
          onClose={() => setEditingHosts(false)}
          onSave={async (values) => {
            const hosts = String(values.hosts || "").split("\n")
              .map((host) => host.trim()).filter(Boolean);
            await new QwenPawClient(connection).mutateModule(
              "/config/security/allow-no-auth-hosts",
              "PUT",
              { hosts },
            );
            await load();
          }}
          title="免认证 Host"
          values={{
            hosts: Array.isArray(state.allowHosts?.hosts)
              ? state.allowHosts.hosts.join("\n")
              : "",
          }}
        />
      ) : null}
    </>
  );
}

function SecurityToggle({
  disabled,
  icon,
  label,
  onChange,
  subtitle,
  value,
}: {
  disabled: boolean;
  icon: typeof ShieldCheck;
  label: string;
  onChange: (value: boolean) => void;
  subtitle: string;
  value: boolean;
}) {
  return (
    <IosRow
      accessory={(
        <Switch
          disabled={disabled}
          ios_backgroundColor={colors.hairline}
          onValueChange={onChange}
          trackColor={{ false: colors.hairline, true: colors.accent }}
          value={value}
        />
      )}
      icon={icon}
      label={label}
      subtitle={subtitle}
    />
  );
}

function scannerLabel(value: unknown): string {
  if (value === "block") return "阻止";
  if (value === "warn") return "警告";
  if (value === "off") return "关闭";
  return "未设置";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "读取失败";
}
