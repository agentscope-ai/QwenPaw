import {
  CircleAlert,
  CloudOff,
  RefreshCw,
  Server,
  Trash2,
  X,
} from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  getPlatformRelayQuota,
  listPlatformRelayNodes,
  revokePlatformRelayNode,
  type PlatformRelayNode,
  type PlatformRelayQuota,
} from "../../api/platformRelay";
import { colors, radius, spacing } from "../../theme/tokens";

export function RelayNodesSheet({
  currentNodeId,
  onClose,
  onRevoked,
  visible,
}: {
  currentNodeId?: string | null;
  onClose: () => void;
  onRevoked: (nodeId: string) => void;
  visible: boolean;
}) {
  const [nodes, setNodes] = useState<PlatformRelayNode[]>([]);
  const [quota, setQuota] = useState<PlatformRelayQuota | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [confirmingNode, setConfirmingNode] =
    useState<PlatformRelayNode | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextQuota, nextNodes] = await Promise.all([
        getPlatformRelayQuota(),
        listPlatformRelayNodes(),
      ]);
      setQuota(nextQuota);
      setNodes(nextNodes);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!visible) return;
    const timer = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(timer);
  }, [refresh, visible]);

  const close = () => {
    setConfirmingNode(null);
    onClose();
  };

  const revoke = async (node: PlatformRelayNode) => {
    setRemovingId(node.id);
    try {
      await revokePlatformRelayNode(node.id);
      setNodes((current) => current.filter((item) => item.id !== node.id));
      setQuota((current) => current
        ? { ...current, used: Math.max(0, current.used - 1), can_bind: true }
        : current);
      onRevoked(node.id);
      setConfirmingNode(null);
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : "解除绑定失败，请稍后重试。",
      );
    } finally {
      setRemovingId(null);
    }
  };

  const allowance = quota?.limit == null
    ? `${quota?.used ?? nodes.length} 个`
    : `${quota.used} / ${quota.limit}`;

  return (
    <Modal
      animationType="slide"
      onRequestClose={close}
      presentationStyle="formSheet"
      visible={visible}
    >
      <SafeAreaView edges={["bottom"]} style={styles.root}>
        <View style={styles.header}>
          <View style={styles.heading}>
            <Text maxFontSizeMultiplier={1.4} style={styles.title}>
              自部署连接
            </Text>
            <Text maxFontSizeMultiplier={1.3} style={styles.subtitle}>
              已用额度 {allowance}，云端 QwenPaw 不计入这里
            </Text>
          </View>
          <Pressable
            accessibilityLabel="关闭自部署连接管理"
            accessibilityRole="button"
            hitSlop={8}
            onPress={close}
            style={({ pressed }) => [styles.roundButton, pressed && styles.pressed]}
          >
            <X color={colors.ink} size={20} />
          </Pressable>
        </View>

        {loading && nodes.length === 0 ? (
          <View style={styles.state}>
            <ActivityIndicator color={colors.accent} />
            <Text style={styles.stateText}>正在读取连接…</Text>
          </View>
        ) : error && nodes.length === 0 ? (
          <View style={styles.state}>
            <CloudOff color={colors.danger} size={26} />
            <Text style={styles.stateTitle}>暂时无法读取连接</Text>
            <Text style={styles.stateText}>{error}</Text>
            <Pressable
              accessibilityRole="button"
              onPress={() => void refresh()}
              style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
            >
              <RefreshCw color={colors.white} size={18} />
              <Text style={styles.retryText}>重新加载</Text>
            </Pressable>
          </View>
        ) : nodes.length === 0 ? (
          <View style={styles.state}>
            <Server color={colors.muted} size={26} />
            <Text style={styles.stateTitle}>暂无自部署连接</Text>
            <Text style={styles.stateText}>在 QwenPaw 中登录同一个 Platform 账号即可绑定。</Text>
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.content}>
            <View style={styles.group}>
              {nodes.map((node, index) => {
                const current = node.id === currentNodeId;
                const online = node.status === "online";
                return (
                  <View
                    key={node.id}
                    style={[styles.row, index > 0 && styles.divider]}
                  >
                    <View style={styles.nodeIcon}>
                      <Server color={colors.accentDark} size={19} />
                    </View>
                    <View style={styles.nodeBody}>
                      <View style={styles.nodeTitleLine}>
                        <Text numberOfLines={1} style={styles.nodeName}>
                          {node.name}
                        </Text>
                        {current ? <Text style={styles.current}>当前</Text> : null}
                      </View>
                      <Text numberOfLines={1} style={styles.nodeMeta}>
                        {online ? "在线" : "离线"}{formatLastSeen(node.last_seen_at)}
                      </Text>
                    </View>
                    <Pressable
                      accessibilityLabel={`解除绑定${node.name}`}
                      accessibilityRole="button"
                      disabled={removingId !== null}
                      onPress={() => setConfirmingNode(node)}
                      style={({ pressed }) => [
                        styles.remove,
                        pressed && styles.pressed,
                      ]}
                    >
                      {removingId === node.id ? (
                        <ActivityIndicator color={colors.danger} size="small" />
                      ) : (
                        <Trash2 color={colors.danger} size={18} />
                      )}
                    </Pressable>
                  </View>
                );
              })}
            </View>
            {error ? <Text style={styles.inlineError}>{error}</Text> : null}
          </ScrollView>
        )}
        {confirmingNode ? (
          <View style={styles.confirmationLayer}>
            <Pressable
              accessibilityLabel="取消解除绑定"
              accessibilityRole="button"
              onPress={() => setConfirmingNode(null)}
              style={StyleSheet.absoluteFill}
            />
            <View style={styles.confirmationCard}>
              <View style={styles.confirmationIcon}>
                <CircleAlert color={colors.danger} size={22} />
              </View>
              <Text style={styles.confirmationTitle}>
                解除绑定“{confirmingNode.name}”？
              </Text>
              <Text style={styles.confirmationText}>
                将停止 Platform 中转访问，本地会话和配置不会被删除。
              </Text>
              <View style={styles.confirmationActions}>
                <Pressable
                  accessibilityRole="button"
                  disabled={removingId !== null}
                  onPress={() => setConfirmingNode(null)}
                  style={({ pressed }) => [
                    styles.confirmationButton,
                    pressed && styles.pressed,
                  ]}
                >
                  <Text style={styles.cancelText}>取消</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  disabled={removingId !== null}
                  onPress={() => void revoke(confirmingNode)}
                  style={({ pressed }) => [
                    styles.confirmationButton,
                    styles.destructiveButton,
                    pressed && styles.pressed,
                  ]}
                >
                  {removingId ? (
                    <ActivityIndicator color={colors.white} size="small" />
                  ) : (
                    <Text style={styles.destructiveText}>解除绑定</Text>
                  )}
                </Pressable>
              </View>
            </View>
          </View>
        ) : null}
      </SafeAreaView>
    </Modal>
  );
}

function formatLastSeen(value: string | null): string {
  if (!value) return " · 尚未连接";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return ` · ${date.toLocaleDateString()}`;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  header: {
    minHeight: 82,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
  },
  heading: { flex: 1, gap: 3 },
  title: { color: colors.ink, fontSize: 25, fontWeight: "700" },
  subtitle: { color: colors.muted, fontSize: 13 },
  roundButton: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
    backgroundColor: colors.surfaceSoft,
  },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  group: {
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  row: {
    minHeight: 72,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: spacing.md,
  },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
  nodeIcon: {
    width: 36,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 11,
    backgroundColor: colors.accentSoft,
  },
  nodeBody: { flex: 1, minWidth: 0, gap: 3 },
  nodeTitleLine: { flexDirection: "row", alignItems: "center", gap: 7 },
  nodeName: { flexShrink: 1, color: colors.ink, fontSize: 16, fontWeight: "600" },
  nodeMeta: { color: colors.muted, fontSize: 12 },
  current: { color: colors.accentDark, fontSize: 11, fontWeight: "600" },
  remove: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
  },
  state: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    padding: spacing.xl,
  },
  stateTitle: { color: colors.ink, fontSize: 18, fontWeight: "600" },
  stateText: { color: colors.muted, fontSize: 14, textAlign: "center" },
  retry: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
  },
  retryText: { color: colors.white, fontSize: 15, fontWeight: "600" },
  inlineError: { marginTop: spacing.md, color: colors.danger, fontSize: 13 },
  confirmationLayer: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    justifyContent: "flex-end",
    padding: spacing.md,
    backgroundColor: colors.scrim,
  },
  confirmationCard: {
    gap: spacing.sm,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surfaceStrong,
  },
  confirmationIcon: {
    width: 42,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 13,
    backgroundColor: colors.accentSoft,
  },
  confirmationTitle: { color: colors.ink, fontSize: 20, fontWeight: "700" },
  confirmationText: { color: colors.muted, fontSize: 14, lineHeight: 21 },
  confirmationActions: { flexDirection: "row", gap: spacing.sm, marginTop: 6 },
  confirmationButton: {
    minHeight: 50,
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSoft,
  },
  destructiveButton: { backgroundColor: colors.danger },
  cancelText: { color: colors.ink, fontSize: 15, fontWeight: "600" },
  destructiveText: { color: colors.white, fontSize: 15, fontWeight: "600" },
  pressed: { opacity: 0.62 },
});
