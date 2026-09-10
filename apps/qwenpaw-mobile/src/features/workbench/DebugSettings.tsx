import { FileText, RefreshCw, TerminalSquare, X } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors, radius, spacing } from "../../theme/tokens";
import { ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface DebugLogs {
  path: string;
  exists: boolean;
  lines: number;
  updated_at: number | null;
  size: number;
  content: string;
}

export function DebugSettings({ connection }: { connection: Connection }) {
  const [logs, setLogs] = useState<DebugLogs | null>(null);
  const [showing, setShowing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const value = await new QwenPawClient(connection)
        .inspectModule("/console/debug/backend-logs?lines=200");
      setError(null);
      setLogs(value as DebugLogs);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取失败");
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!logs) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="Backend">
        <IosRow
          icon={TerminalSquare}
          label="最近日志"
          onPress={() => setShowing(true)}
          subtitle={`${logs.lines} 行 · ${formatBytes(logs.size)}`}
          trailing={logs.exists ? "查看" : "未生成"}
        />
        <IosRow
          icon={RefreshCw}
          label="刷新日志"
          onPress={() => void load()}
          subtitle="重新读取当前 QwenPaw"
        />
        <IosRow
          icon={FileText}
          iconTone="ink"
          label="日志位置"
          subtitle={logs.path || "当前 QwenPaw 未返回路径"}
        />
      </IosGroup>
      <ModuleFooter>日志只在当前设备显示，不上传到 QwenPaw Mobile。</ModuleFooter>
      {showing ? (
        <Modal animationType="slide" presentationStyle="pageSheet">
          <SafeAreaView style={styles.root}>
            <View style={styles.header}>
              <Text style={styles.title}>Backend Logs</Text>
              <Pressable onPress={() => setShowing(false)} style={styles.close}>
                <X color={colors.ink} size={22} />
              </Pressable>
            </View>
            <ScrollView contentContainerStyle={styles.logContent}>
              <Text selectable style={styles.log}>{logs.content || "暂无日志内容"}</Text>
            </ScrollView>
          </SafeAreaView>
        </Modal>
      ) : null}
    </>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  header: {
    height: 58,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
  },
  title: { color: colors.ink, fontSize: 20, fontWeight: "700" },
  close: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.searchBackground,
  },
  logContent: { padding: spacing.md, paddingBottom: spacing.xxl },
  log: {
    padding: spacing.md,
    borderRadius: radius.md,
    color: "#EDE7E1",
    backgroundColor: colors.black,
    fontFamily: "Menlo",
    fontSize: 11,
    lineHeight: 17,
  },
});
