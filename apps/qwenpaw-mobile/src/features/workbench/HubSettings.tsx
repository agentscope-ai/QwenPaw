import {
  Activity,
  Cpu,
  HardDrive,
  MemoryStick,
  Network,
  RefreshCw,
  Server,
  ShieldCheck,
  UserRound,
  UsersRound,
} from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { QwenPawClient } from "../../api/client";
import type {
  Connection,
  HubHealth,
  HubIdentity,
  HubOverview,
  HubRuntime,
} from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { MobileAlert } from "../../components/MobileAlert";
import { colors, radius, spacing } from "../../theme/tokens";
import {
  hubRoleLabel,
  hubRuntimeStateLabel,
  hubRuntimeStateTone,
} from "./hubModel";
import { ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface HubSnapshot {
  health: HubHealth;
  identity: HubIdentity;
  overview: HubOverview | null;
  runtimes: HubRuntime[];
}

export function HubSettings({ connection }: { connection: Connection }) {
  const [snapshot, setSnapshot] = useState<HubSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [health, identity, page] = await Promise.all([
        client.getHubHealth(),
        client.getHubIdentity(),
        client.listHubRuntimes(),
      ]);
      const overview = identity.role === "admin"
        ? await client.getHubOverview()
        : null;
      setSnapshot({ health, identity, overview, runtimes: page.items });
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const run = async (
    key: string,
    action: () => Promise<unknown>,
    success: string,
  ) => {
    if (busy) return;
    setBusy(key);
    try {
      await action();
      await load();
      MobileAlert.alert(success);
    } catch (reason) {
      MobileAlert.alert("操作失败", errorMessage(reason));
    } finally {
      setBusy(null);
    }
  };

  const restartOwnRuntime = () => {
    MobileAlert.alert(
      "重新启动我的 QwenPaw？",
      "正在进行的任务会中断，Runtime 就绪后 App 会继续使用当前 Hub 账号。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "重新启动",
          onPress: () => void run(
            "restart-own",
            () => new QwenPawClient(connection).restartOwnHubRuntime(),
            "QwenPaw 已重新启动",
          ),
        },
      ],
    );
  };

  const confirmRuntimeAction = (
    runtime: HubRuntime,
    action: "start" | "stop" | "rebuild" | "disable" | "delete",
  ) => {
    const labels = {
      start: "启动",
      stop: "停止",
      rebuild: "重建",
      disable: "停用",
      delete: "删除",
    } as const;
    const destructive = action !== "start";
    MobileAlert.alert(
      `${labels[action]} ${runtime.runtime_id}？`,
      action === "delete"
        ? "Runtime 记录和运行实例会被删除，此操作无法撤销。"
        : "该操作可能中断此用户正在进行的任务。",
      [
        { text: "取消", style: "cancel" },
        {
          text: labels[action],
          style: destructive ? "destructive" : "default",
          onPress: () => void run(
            `${runtime.runtime_id}:${action}`,
            () => action === "delete"
              ? new QwenPawClient(connection).deleteHubRuntime(
                  runtime.runtime_id,
                )
              : new QwenPawClient(connection).manageHubRuntime(
                  runtime.runtime_id,
                  action,
                ),
            `${labels[action]}操作已完成`,
          ),
        },
      ],
    );
  };

  const openRuntimeActions = (runtime: HubRuntime) => {
    const stopped = runtime.state === "stopped" || runtime.state === "failed";
    MobileAlert.alert(runtime.runtime_id, "选择 Runtime 操作。", [
      ...(stopped ? [{
        text: "启动",
        onPress: () => confirmRuntimeAction(runtime, "start"),
      }] : [{
        text: "停止",
        onPress: () => confirmRuntimeAction(runtime, "stop"),
      }]),
      {
        text: "使用当前镜像重建",
        onPress: () => confirmRuntimeAction(runtime, "rebuild"),
      },
      {
        text: "停用",
        style: "destructive",
        onPress: () => confirmRuntimeAction(runtime, "disable"),
      },
      {
        text: "删除",
        style: "destructive",
        onPress: () => confirmRuntimeAction(runtime, "delete"),
      },
      { text: "取消", style: "cancel" },
    ]);
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!snapshot) return <ModuleLoading label="正在读取 Hub 状态…" />;

  const { health, identity, overview, runtimes } = snapshot;
  const personalRuntime = runtimes.find(
    (runtime) => runtime.owner_username === identity.username,
  ) ?? runtimes[0];

  return (
    <>
      <IosGroup title="当前 Hub">
        <IosRow
          icon={UserRound}
          label={identity.username}
          subtitle="当前登录身份"
          trailing={hubRoleLabel(identity.role)}
        />
        <IosRow
          accessory={<RuntimeBadge state={health.runtime_state} />}
          icon={Activity}
          label="我的 QwenPaw"
          subtitle={health.runtime_last_error || "Hub 管理的个人 Runtime"}
        />
        <IosRow
          icon={Network}
          label="运行方式"
          subtitle={personalRuntime?.security_level || "由 Hub 统一隔离"}
          trailing={personalRuntime?.provisioner || health.default_provisioner}
        />
        <IosRow
          icon={RefreshCw}
          label={busy === "restart-own" ? "正在重新启动" : "重新启动我的 QwenPaw"}
          onPress={busy ? undefined : restartOwnRuntime}
          subtitle="任务异常或 Runtime 未响应时使用"
        />
      </IosGroup>

      {identity.role === "admin" && overview ? (
        <>
          <View style={styles.metrics}>
            <Metric icon={UsersRound} label="用户" value={overview.total_users} />
            <Metric icon={Server} label="Runtime" value={overview.total_runtimes} />
            <Metric
              icon={ShieldCheck}
              label="运行中"
              value={overview.runtime_counts.running ?? 0}
            />
          </View>
          <IosGroup title="宿主机">
            <IosRow icon={Cpu} label="CPU" trailing={percent(overview.host.cpu_percent)} />
            <IosRow icon={MemoryStick} label="内存" trailing={percent(overview.host.memory_percent)} />
            <IosRow icon={HardDrive} label="磁盘" trailing={percent(overview.host.disk_percent)} />
          </IosGroup>
          <IosGroup title={`Runtime · ${runtimes.length}`}>
            {runtimes.map((runtime) => (
              <IosRow
                accessory={<RuntimeBadge state={runtime.state} />}
                icon={Server}
                key={runtime.runtime_id}
                label={runtime.owner_username || runtime.runtime_id}
                onPress={busy ? undefined : () => openRuntimeActions(runtime)}
                subtitle={`${runtime.runtime_id} · ${runtime.provisioner}`}
              />
            ))}
          </IosGroup>
        </>
      ) : null}

      <ModuleFooter>
        Hub 登录令牌同时用于控制面和个人 QwenPaw；会话、Agent 与模型继续使用同一套 Mobile 功能。
      </ModuleFooter>
    </>
  );
}

function RuntimeBadge({ state }: { state: HubRuntime["state"] | null }) {
  const tone = hubRuntimeStateTone(state);
  return (
    <View style={styles.badge}>
      <View style={[styles.dot, styles[`${tone}Dot`]]} />
      <Text style={styles.badgeText}>{hubRuntimeStateLabel(state)}</Text>
    </View>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Server;
  label: string;
  value: number;
}) {
  return (
    <View style={styles.metric}>
      <Icon color={colors.accentDark} size={18} strokeWidth={1.9} />
      <Text style={styles.metricValue}>{value}</Text>
      <Text style={styles.metricLabel}>{label}</Text>
    </View>
  );
}

function percent(value: number): string {
  return `${Math.round(value)}%`;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Hub 暂时不可用";
}

const styles = StyleSheet.create({
  metrics: { flexDirection: "row", gap: spacing.sm },
  metric: {
    flex: 1,
    minHeight: 108,
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  metricValue: { color: colors.ink, fontSize: 22, fontWeight: "700" },
  metricLabel: { color: colors.muted, fontSize: 12 },
  badge: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  dot: { width: 8, height: 8, borderRadius: 4 },
  positiveDot: { backgroundColor: colors.positive },
  accentDot: { backgroundColor: colors.accent },
  mutedDot: { backgroundColor: colors.faint },
  dangerDot: { backgroundColor: colors.danger },
  badgeText: { color: colors.muted, fontSize: 13 },
});
