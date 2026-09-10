import { router } from "expo-router";
import {
  Check,
  ChevronDown,
  Cloud,
  Plus,
  Server,
  Trash2,
  X,
} from "lucide-react-native";
import { useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import ReanimatedSwipeable, {
  type SwipeableMethods,
} from "react-native-gesture-handler/ReanimatedSwipeable";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaView } from "react-native-safe-area-context";

import type { Connection } from "../../api/types";
import { MobileToast } from "../../components/MobileToast";
import { mobileText } from "../../i18n/locale";
import { resolveAgentAppearance } from "../../storage/agentAppearance";
import { connectionKey } from "../../storage/connection";
import { useAppStore } from "../../store/app";
import { qwenPawBrandAssets } from "../../theme/brandAssets";
import { colors, radius, spacing } from "../../theme/tokens";

export function WorkspaceBadge() {
  const connection = useAppStore((state) => state.connection);
  const agents = useAppStore((state) => state.agents);
  const appearances = useAppStore((state) => state.agentAppearances);
  const status = useAppStore((state) => state.status);
  const [visible, setVisible] = useState(false);
  if (!connection) return null;
  const agent = agents.find((item) => item.id === connection.agentId);
  const agentName = agent
    ? resolveAgentAppearance(appearances, connection, agent).name
    : connection.agentId || "Default Agent";
  return (
    <>
      <Pressable
        accessibilityLabel="切换 QwenPaw"
        onPress={() => setVisible(true)}
        style={({ pressed }) => [styles.badge, pressed && styles.pressed]}
      >
        <Image
          accessible={false}
          resizeMode="contain"
          source={qwenPawBrandAssets.wave}
          style={styles.badgeImage}
        />
        <View style={styles.badgeBody}>
          <Text maxFontSizeMultiplier={1.3} style={styles.badgeTitle}>
            {workspaceName(connection)}
          </Text>
          <Text
            maxFontSizeMultiplier={1.25}
            numberOfLines={1}
            style={styles.badgeSource}
          >
            {agentName} · {status === "ready"
              ? mobileText("运行正常", "Ready")
              : mobileText("正在连接", "Connecting")}
          </Text>
        </View>
        <ChevronDown color={colors.faint} size={17} strokeWidth={2.2} />
      </Pressable>
      <WorkspaceSwitcher
        onClose={() => setVisible(false)}
        visible={visible}
      />
    </>
  );
}

export function WorkspaceSwitcher({
  onClose,
  visible,
}: {
  onClose: () => void;
  visible: boolean;
}) {
  const connection = useAppStore((state) => state.connection);
  const connections = useAppStore((state) => state.connections);
  const status = useAppStore((state) => state.status);
  const switchConnection = useAppStore((state) => state.switchConnection);
  const removeConnection = useAppStore((state) => state.removeConnection);
  const [switchingKey, setSwitchingKey] = useState<string | null>(null);
  const [removingKey, setRemovingKey] = useState<string | null>(null);
  const [toast, setToast] = useState<{
    message: string;
    tone: "error" | "success";
  } | null>(null);
  const openSwipeable = useRef<SwipeableMethods | null>(null);
  const rowRefs = useRef(new Map<string, SwipeableMethods>());
  const activeKey = connection ? connectionKey(connection) : null;

  const close = () => {
    openSwipeable.current?.close();
    openSwipeable.current = null;
    onClose();
  };

  const select = async (target: Connection) => {
    const key = connectionKey(target);
    if (key === activeKey) {
      close();
      return;
    }
    try {
      setSwitchingKey(key);
      await switchConnection(key);
      close();
    } catch (error) {
      setToast({
        message: error instanceof Error
          ? error.message
          : "切换失败，当前 QwenPaw 仍保持连接。",
        tone: "error",
      });
    } finally {
      setSwitchingKey(null);
    }
  };

  const add = () => {
    close();
    router.push({ pathname: "/", params: { add: "1" } });
  };

  const remove = async (target: Connection) => {
    const key = connectionKey(target);
    const active = key === activeKey;
    try {
      setRemovingKey(key);
      await removeConnection(key);
      if (!active) {
        setToast({
          message: `${workspaceName(target)}已取消配对`,
          tone: "success",
        });
        return;
      }
      close();
      const state = useAppStore.getState();
      router.replace(
        state.connection && state.status === "ready" ? "/chats" : "/",
      );
    } catch (error) {
      setToast({
        message: error instanceof Error ? error.message : "取消配对失败，请重试",
        tone: "error",
      });
    } finally {
      setRemovingKey(null);
    }
  };

  return (
    <Modal
      animationType="slide"
      onRequestClose={close}
      transparent
      visible={visible}
    >
      <GestureHandlerRootView style={styles.modalRoot}>
        <View style={styles.mask}>
          <Pressable onPress={close} style={StyleSheet.absoluteFill} />
          <SafeAreaView edges={["bottom"]} style={styles.sheet}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View>
              <Text style={styles.sheetTitle}>
                {mobileText("切换 QwenPaw", "Switch QwenPaw")}
              </Text>
              <Text style={styles.sheetCopy}>
                {mobileText(
                  "切换不会退出另一个连接",
                  "Switching keeps your other connections signed in",
                )}
              </Text>
            </View>
            <Pressable
              accessibilityLabel="关闭"
              onPress={close}
              style={styles.close}
            >
              <X color={colors.ink} size={20} />
            </Pressable>
          </View>
          <View style={styles.workspaceList}>
            {connections.map((item) => {
              const key = connectionKey(item);
              const active = key === activeKey;
              const Icon = item.source === "platform" ? Cloud : Server;
              return (
                <ReanimatedSwipeable
                  containerStyle={styles.swipeable}
                  enabled={status !== "connecting" && removingKey === null}
                  key={key}
                  onSwipeableWillOpen={() => {
                    const next = rowRefs.current.get(key) ?? null;
                    if (openSwipeable.current !== next) {
                      openSwipeable.current?.close();
                      openSwipeable.current = next;
                    }
                  }}
                  overshootRight={false}
                  ref={(value) => {
                    if (value) rowRefs.current.set(key, value);
                    else rowRefs.current.delete(key);
                  }}
                  renderRightActions={(_progress, _translation, methods) => (
                    <Pressable
                      accessibilityLabel={`取消配对${workspaceName(item)}`}
                      accessibilityRole="button"
                      disabled={removingKey !== null}
                      onPress={() => {
                        methods.close();
                        void remove(item);
                      }}
                      style={({ pressed }) => [
                        styles.removeAction,
                        pressed && styles.removeActionPressed,
                      ]}
                    >
                      {removingKey === key ? (
                        <ActivityIndicator color={colors.white} size="small" />
                      ) : (
                        <Trash2 color={colors.white} size={20} />
                      )}
                      <Text style={styles.removeActionText}>
                        {mobileText("取消配对", "Unpair")}
                      </Text>
                    </Pressable>
                  )}
                >
                  <Pressable
                    accessibilityActions={[
                      {
                        label: `取消配对${workspaceName(item)}`,
                        name: "remove",
                      },
                    ]}
                    accessibilityHint="左滑可取消配对"
                    accessibilityRole="button"
                    disabled={status === "connecting" || removingKey !== null}
                    onAccessibilityAction={(event) => {
                      if (event.nativeEvent.actionName === "remove") {
                        void remove(item);
                      }
                    }}
                    onPress={() => void select(item)}
                    style={({ pressed }) => [
                      styles.workspace,
                      active && styles.workspaceActive,
                      pressed && styles.pressed,
                    ]}
                  >
                    <View style={[styles.workspaceIcon, active && styles.workspaceIconActive]}>
                      <Icon color={active ? colors.white : colors.accent} size={20} />
                    </View>
                    <View style={styles.workspaceBody}>
                      <Text style={styles.workspaceName}>{workspaceName(item)}</Text>
                      <Text numberOfLines={1} style={styles.workspaceUrl}>{item.baseUrl}</Text>
                    </View>
                    {status === "connecting" && switchingKey === key ? (
                      <ActivityIndicator color={colors.accent} size="small" />
                    ) : active ? (
                      <View style={styles.check}><Check color={colors.white} size={15} strokeWidth={2.6} /></View>
                    ) : null}
                  </Pressable>
                </ReanimatedSwipeable>
              );
            })}
          </View>
          <Pressable onPress={add} style={({ pressed }) => [styles.add, pressed && styles.pressed]}>
            <View style={styles.addIcon}><Plus color={colors.accent} size={20} /></View>
            <View style={styles.workspaceBody}>
              <Text style={styles.addTitle}>
                {mobileText("再配对一只 QwenPaw", "Pair another QwenPaw")}
              </Text>
              <Text style={styles.workspaceUrl}>
                {mobileText(
                  "私人部署或 Platform 云端 QwenPaw",
                  "Private deployment or Platform Cloud",
                )}
              </Text>
            </View>
          </Pressable>
          <MobileToast
            message={toast?.message ?? null}
            onHide={() => setToast(null)}
            tone={toast?.tone}
          />
          </SafeAreaView>
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}

export function workspaceName(connection: Connection): string {
  return connection.source === "platform"
    ? mobileText("Platform 云端", "Platform Cloud")
    : mobileText("本地 / 私人", "Local / Private");
}

const styles = StyleSheet.create({
  badge: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  badgeImage: { width: 34, height: 34 },
  badgeBody: { flex: 1, minWidth: 0 },
  badgeTitle: { color: colors.ink, fontSize: 13, fontWeight: "700" },
  badgeSource: { marginTop: 2, color: colors.muted, fontSize: 10 },
  modalRoot: { flex: 1 },
  mask: { flex: 1, justifyContent: "flex-end", backgroundColor: colors.scrim },
  sheet: { paddingHorizontal: spacing.md, paddingBottom: spacing.md, borderTopLeftRadius: 26, borderTopRightRadius: 26, backgroundColor: colors.groupedBackground },
  sheetHandle: { width: 36, height: 5, alignSelf: "center", marginTop: 8, marginBottom: 10, borderRadius: 3, backgroundColor: colors.line },
  sheetHeader: { minHeight: 58, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sheetTitle: { color: colors.ink, fontSize: 20, fontWeight: "700" },
  sheetCopy: { color: colors.muted, fontSize: 11, marginTop: 3 },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22, backgroundColor: colors.searchBackground },
  workspaceList: { overflow: "hidden", marginTop: spacing.sm, borderRadius: radius.md, backgroundColor: colors.surface },
  swipeable: { backgroundColor: colors.surface },
  workspace: { minHeight: 72, flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: spacing.md, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.hairline, backgroundColor: colors.surface },
  workspaceActive: { backgroundColor: colors.accentSoft },
  workspaceIcon: { width: 42, height: 42, alignItems: "center", justifyContent: "center", borderRadius: 13, backgroundColor: colors.accentSoft },
  workspaceIconActive: { backgroundColor: colors.accent },
  workspaceBody: { flex: 1, minWidth: 0, gap: 3 },
  workspaceName: { color: colors.ink, fontSize: 15, fontWeight: "600" },
  workspaceUrl: { color: colors.muted, fontSize: 11 },
  check: { width: 26, height: 26, alignItems: "center", justifyContent: "center", borderRadius: 13, backgroundColor: colors.accent },
  removeAction: { width: 96, alignItems: "center", justifyContent: "center", gap: 4, backgroundColor: colors.danger },
  removeActionPressed: { opacity: 0.78 },
  removeActionText: { color: colors.white, fontSize: 12, fontWeight: "700" },
  add: { minHeight: 68, flexDirection: "row", alignItems: "center", gap: 12, marginTop: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.md, backgroundColor: colors.surface },
  addIcon: { width: 42, height: 42, alignItems: "center", justifyContent: "center", borderRadius: 13, borderWidth: 1, borderColor: colors.accentSoft, backgroundColor: colors.surfaceStrong },
  addTitle: { color: colors.accentDark, fontSize: 14, fontWeight: "700" },
  pressed: { opacity: 0.68 },
});
