import {
  Copy,
  Ellipsis,
  Pin,
  PinOff,
  Plus,
  Power,
  PowerOff,
  Search,
  Trash2,
  Undo2,
} from "lucide-react-native";
import { memo, useCallback, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import type { AgentSummary } from "../../api/types";
import { IosHeader } from "../../components/IosHeader";
import { MobileToast } from "../../components/MobileToast";
import { AgentAvatar } from "../../features/agents/AgentAvatar";
import { AgentProfileSheet } from "../../features/agents/AgentProfileSheet";
import {
  AnchoredActionMenu,
  type AnchoredMenuAction,
  type AnchorRect,
} from "../../features/chat/AnchoredActionMenu";
import { workspaceName } from "../../features/workspaces/WorkspaceSwitcher";
import { QwenPawClient } from "../../api/client";
import { DynamicConfigSheet } from "../../features/workbench/DynamicConfigSheet";
import { mobileText } from "../../i18n/locale";
import {
  agentAppearanceKey,
  resolveAgentAppearance,
} from "../../storage/agentAppearance";
import { useAppStore } from "../../store/app";
import { qwenPawBrandAssets } from "../../theme/brandAssets";
import { colors, radius, spacing } from "../../theme/tokens";

export default function AgentsScreen() {
  const agents = useAppStore((state) => state.agents);
  const activeAgentId = useAppStore((state) => state.connection?.agentId);
  const selectAgent = useAppStore((state) => state.selectAgent);
  const connection = useAppStore((state) => state.connection);
  const appearances = useAppStore((state) => state.agentAppearances);
  const setAgentAppearance = useAppStore((state) => state.setAgentAppearance);
  const reconnect = useAppStore((state) => state.connect);
  const [query, setQuery] = useState("");
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [manager, setManager] = useState<
    { mode: "create" } | { mode: "copy"; agent: AgentSummary } | null
  >(null);
  const [agentMenu, setAgentMenu] = useState<{
    agent: AgentSummary;
    anchor: AnchorRect;
    confirmDelete?: boolean;
  } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const visibleAgents = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return agents;
    return agents.filter((agent) => (
      `${resolveAgentAppearance(appearances, connection, agent).name} ` +
      agent.description
    ).toLocaleLowerCase().includes(normalized));
  }, [agents, appearances, connection, query]);
  const activeAgent = useMemo(
    () => agents.find((agent) => agent.id === activeAgentId) ?? agents[0] ?? null,
    [activeAgentId, agents],
  );
  const activeAppearance = activeAgent
    ? resolveAgentAppearance(appearances, connection, activeAgent)
    : null;

  const switchAgent = useCallback(async (agentId: string) => {
    if (agentId === activeAgentId || switchingId) return;
    setSwitchingId(agentId);
    try {
      await selectAgent(agentId);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "暂时无法切换智能体");
    } finally {
      setSwitchingId(null);
    }
  }, [activeAgentId, selectAgent, switchingId]);

  const reload = useCallback(async () => {
    if (connection) await reconnect(connection);
  }, [connection, reconnect]);

  const mutateAgent = useCallback(async (
    agent: AgentSummary,
    action: "delete" | "pin" | "toggle",
  ) => {
    if (!connection) return;
    const client = new QwenPawClient(connection);
    try {
      if (action === "delete") {
        await client.mutateModule(
          `/agents/${encodeURIComponent(agent.id)}`,
          "DELETE",
        );
      } else {
        await client.mutateModule(
          `/agents/${encodeURIComponent(agent.id)}/${action}`,
          "PATCH",
          action === "pin"
            ? { pinned: agent.pinned !== true }
            : { enabled: agent.enabled === false },
        );
      }
      await reload();
    } catch (reason) {
      setToast(errorMessage(reason));
    }
  }, [connection, reload]);

  const agentMenuActions: AnchoredMenuAction[] = !agentMenu
    ? []
    : agentMenu.confirmDelete
      ? [
          { icon: Undo2, label: "取消", onPress: () => undefined },
          {
            icon: Trash2,
            label: "确认删除",
            onPress: () => void mutateAgent(agentMenu.agent, "delete"),
            tone: "danger",
          },
        ]
      : [
          {
            icon: Copy,
            label: "复制",
            onPress: () => setManager({ mode: "copy", agent: agentMenu.agent }),
          },
          {
            icon: agentMenu.agent.pinned ? PinOff : Pin,
            label: agentMenu.agent.pinned ? "取消置顶" : "置顶",
            onPress: () => void mutateAgent(agentMenu.agent, "pin"),
          },
          {
            icon: agentMenu.agent.enabled === false ? Power : PowerOff,
            label: agentMenu.agent.enabled === false ? "启用" : "停用",
            onPress: () => void mutateAgent(agentMenu.agent, "toggle"),
          },
          ...(agentMenu.agent.id === "default" ||
          agentMenu.agent.id === activeAgentId ? [] : [{
            icon: Trash2,
            label: "删除",
            onPress: () => setAgentMenu({ ...agentMenu, confirmDelete: true }),
            tone: "danger" as const,
          }]),
        ];

  return (
    <SafeAreaView edges={["top"]} style={styles.root}>
      <View style={styles.shell}>
        <IosHeader
          actionIcon={Plus}
          actionLabel={mobileText("创建 Agent", "Create Agent")}
          emphasizedAction
          onAction={() => setManager({ mode: "create" })}
          title={mobileText("智能体", "Agents")}
        />
        {activeAgent && activeAppearance ? (
          <Pressable
            accessibilityLabel={`编辑当前智能体 ${activeAppearance.name}`}
            accessibilityRole="button"
            onPress={() => setEditingAgent(activeAgent)}
            style={({ pressed }) => [
              styles.currentCard,
              pressed && styles.pressed,
            ]}
          >
            <AgentAvatar
              avatarUri={activeAppearance.avatarUri}
              branded={activeAgent.id === "default"}
              size={64}
            />
            <View style={styles.currentBody}>
              <Text maxFontSizeMultiplier={1.3} style={styles.currentEyebrow}>
                {mobileText("当前使用", "Active Agent")}
              </Text>
              <Text
                maxFontSizeMultiplier={1.35}
                numberOfLines={1}
                style={styles.currentName}
              >
                {activeAppearance.name}
              </Text>
              <Text
                maxFontSizeMultiplier={1.25}
                numberOfLines={1}
                style={styles.currentMeta}
              >
                {connection
                  ? workspaceName(connection)
                  : mobileText("尚未连接", "Not connected")}
                {mobileText(
                  " · 新会话与工作台跟随此智能体",
                  " · New chats and Workbench use this Agent",
                )}
              </Text>
            </View>
            <View style={styles.connectedBadge}>
              <Text maxFontSizeMultiplier={1.2} style={styles.connectedLabel}>
                {connection
                  ? mobileText("已连接", "Connected")
                  : mobileText("未连接", "Offline")}
              </Text>
            </View>
          </Pressable>
        ) : null}
        <View style={styles.search}>
          <Search color={colors.faint} size={18} />
          <TextInput
            clearButtonMode="while-editing"
            maxFontSizeMultiplier={1.35}
            onChangeText={setQuery}
            placeholder={mobileText("搜索智能体", "Search Agents")}
            placeholderTextColor={colors.faint}
            style={styles.searchInput}
            value={query}
          />
        </View>
        <View style={styles.sectionHeading}>
          <Text maxFontSizeMultiplier={1.35} style={styles.sectionTitle}>
            {mobileText("全部智能体", "All Agents")}
          </Text>
          <Text maxFontSizeMultiplier={1.25} style={styles.sectionCount}>
            {visibleAgents.length}
          </Text>
        </View>
        <FlatList
          contentContainerStyle={visibleAgents.length ? styles.list : styles.emptyList}
          data={visibleAgents}
          keyboardShouldPersistTaps="handled"
          keyExtractor={(item) => item.id}
          ListEmptyComponent={(
            <View style={styles.empty}>
              <Image
                accessible={false}
                resizeMode="contain"
                source={qwenPawBrandAssets.paw}
                style={styles.emptyImage}
              />
              <Text maxFontSizeMultiplier={1.4} style={styles.emptyTitle}>
                {mobileText("没有找到相关智能体", "No matching Agents")}
              </Text>
              <Text maxFontSizeMultiplier={1.35} style={styles.emptyCopy}>
                {mobileText(
                  "换个关键词，或创建一只新的 QwenPaw。",
                  "Try another keyword or create a new QwenPaw.",
                )}
              </Text>
            </View>
          )}
          renderItem={({ item, index }) => (
            <AgentRow
              active={item.id === activeAgentId}
              agent={item}
              appearance={resolveAgentAppearance(appearances, connection, item)}
              first={index === 0}
              last={index === visibleAgents.length - 1}
              loading={item.id === switchingId}
              onEdit={() => setEditingAgent(item)}
              onManage={(anchor) => setAgentMenu({ agent: item, anchor })}
              onPress={switchAgent}
            />
          )}
        />
        {editingAgent ? (
          <AgentProfileSheet
            agent={editingAgent}
            appearance={connection
              ? appearances[agentAppearanceKey(connection.baseUrl, editingAgent.id)]
              : undefined}
            key={editingAgent.id}
            onClose={() => setEditingAgent(null)}
            onSave={(appearance) => setAgentAppearance(editingAgent.id, appearance)}
          />
        ) : null}
        {manager && connection ? (
          <DynamicConfigSheet
            fields={manager.mode === "create" ? [
              { name: "name", label: "名称", type: "text", required: true },
              { name: "id", label: "Agent ID", type: "text", placeholder: "可选，留空自动生成" },
              { name: "description", label: "说明", type: "textarea" },
              { name: "workspace_dir", label: "Workspace 路径", type: "text", placeholder: "可选" },
            ] : [
              { name: "name", label: "新 Agent 名称", type: "text", required: true },
              { name: "copy_md_files", label: "复制提示与记忆文件", type: "switch" },
              { name: "copy_skills", label: "复制 Skills", type: "switch" },
              { name: "copy_jobs", label: "复制 Cron Jobs", type: "switch" },
            ]}
            onClose={() => setManager(null)}
            onSave={async (values) => {
              const client = new QwenPawClient(connection);
              if (manager.mode === "create") {
                await client.mutateModule("/agents", "POST", {
                  name: String(values.name || "").trim(),
                  ...(String(values.id || "").trim()
                    ? { id: String(values.id).trim() }
                    : {}),
                  ...(String(values.description || "").trim()
                    ? { description: String(values.description).trim() }
                    : {}),
                  ...(String(values.workspace_dir || "").trim()
                    ? { workspace_dir: String(values.workspace_dir).trim() }
                    : {}),
                  language: "zh-CN",
                  backend: "qwenpaw",
                });
              } else {
                await client.mutateModule(
                  `/agents/${encodeURIComponent(manager.agent.id)}/copy`,
                  "POST",
                  {
                    name: String(values.name || "").trim(),
                    copy_agent_json: true,
                    copy_md_files: values.copy_md_files === true,
                    copy_skills: values.copy_skills === true,
                    copy_jobs: values.copy_jobs === true,
                  },
                );
              }
              await reload();
            }}
            title={manager.mode === "create" ? "创建 Agent" : `复制 ${manager.agent.name}`}
            values={manager.mode === "create" ? {} : {
              name: `${manager.agent.name || manager.agent.id} Copy`,
              copy_md_files: true,
              copy_skills: false,
              copy_jobs: false,
            }}
          />
        ) : null}
        <AnchoredActionMenu
          actions={agentMenuActions}
          anchor={agentMenu?.anchor ?? null}
          onClose={() => setAgentMenu(null)}
          title={agentMenu?.confirmDelete
            ? "将删除工作空间且无法撤销"
            : agentMenu?.agent.name || agentMenu?.agent.id}
        />
        <MobileToast
          message={toast}
          onHide={() => setToast(null)}
        />
      </View>
    </SafeAreaView>
  );
}

const AgentRow = memo(function AgentRow({
  active,
  agent,
  first,
  last,
  loading,
  appearance,
  onEdit,
  onManage,
  onPress,
}: {
  active: boolean;
  agent: AgentSummary;
  first: boolean;
  last: boolean;
  loading: boolean;
  appearance: { name: string; avatarUri?: string };
  onEdit: () => void;
  onManage: (anchor: AnchorRect) => void;
  onPress: (agentId: string) => void;
}) {
  const rowRef = useRef<View>(null);
  const moreRef = useRef<View>(null);
  const showActions = (target: View | null) => {
    target?.measureInWindow((x, y, width, height) => {
      onManage({ x, y, width, height });
    });
  };
  return (
    <Pressable
      accessibilityRole="button"
      delayLongPress={320}
      onLongPress={() => showActions(rowRef.current)}
      onPress={() => onPress(agent.id)}
      ref={rowRef}
      style={({ pressed }) => [
        styles.row,
        first && styles.rowFirst,
        last && styles.rowLast,
        pressed && styles.pressed,
      ]}
    >
      <Pressable
        accessibilityLabel={`编辑 ${appearance.name} 头像和昵称`}
        onPress={(event) => {
          event.stopPropagation();
          onEdit();
        }}
        style={styles.avatarButton}
      >
        <AgentAvatar
          avatarUri={appearance.avatarUri}
          branded={agent.id === "default"}
          size={46}
        />
      </Pressable>
      <View style={styles.rowBody}>
        <Text maxFontSizeMultiplier={1.35} numberOfLines={1} style={styles.name}>
          {appearance.name}
        </Text>
        <Text maxFontSizeMultiplier={1.25} numberOfLines={1} style={styles.description}>
          {agent.description || "QwenPaw Agent"}
        </Text>
      </View>
      {loading ? (
        <ActivityIndicator color={colors.accent} size="small" />
      ) : active ? (
        <View style={styles.activeBadge}>
          <Text maxFontSizeMultiplier={1.2} style={styles.activeLabel}>
            {mobileText("当前", "Active")}
          </Text>
        </View>
      ) : null}
      <Pressable
        accessibilityLabel={`管理 ${appearance.name}`}
        accessibilityRole="button"
        onPress={(event) => {
          event.stopPropagation();
          showActions(moreRef.current);
        }}
        ref={moreRef}
        style={styles.more}
      >
        <Ellipsis color={colors.faint} size={19} />
      </Pressable>
    </Pressable>
  );
});

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Agent 操作失败";
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  shell: { flex: 1, width: "100%", maxWidth: 760, alignSelf: "center" },
  currentCard: {
    minHeight: 108,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  currentBody: { flex: 1, minWidth: 0 },
  currentEyebrow: { color: colors.accentDark, fontSize: 11, fontWeight: "700" },
  currentName: { marginTop: 4, color: colors.ink, fontSize: 18, fontWeight: "700" },
  currentMeta: { marginTop: 5, color: colors.muted, fontSize: 11 },
  connectedBadge: { minHeight: 25, justifyContent: "center", paddingHorizontal: 8, borderRadius: radius.pill, backgroundColor: colors.accentSoft },
  connectedLabel: { color: colors.accentDark, fontSize: 10, fontWeight: "700" },
  search: {
    height: 44,
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
    backgroundColor: colors.searchBackground,
  },
  searchInput: { flex: 1, color: colors.ink, fontSize: 16, paddingVertical: 0 },
  sectionHeading: { flexDirection: "row", alignItems: "center", gap: 7, minHeight: 34, marginHorizontal: spacing.md },
  sectionTitle: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  sectionCount: { color: colors.faint, fontSize: 11 },
  list: { paddingBottom: spacing.xl },
  emptyList: { flexGrow: 1, justifyContent: "center", paddingBottom: 90 },
  row: {
    minHeight: 76,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginHorizontal: spacing.md,
    paddingLeft: 12,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
  },
  rowFirst: { borderTopWidth: 1, borderTopLeftRadius: radius.md, borderTopRightRadius: radius.md },
  rowLast: { borderBottomWidth: 1, borderBottomLeftRadius: radius.md, borderBottomRightRadius: radius.md },
  pressed: { backgroundColor: colors.pressed },
  avatarButton: { width: 48, height: 48, alignItems: "center", justifyContent: "center" },
  rowBody: { flex: 1, minWidth: 0, gap: 4 },
  name: { color: colors.ink, fontSize: 16, fontWeight: "600" },
  description: { color: colors.muted, fontSize: 12 },
  activeBadge: { minHeight: 25, justifyContent: "center", paddingHorizontal: 8, borderRadius: radius.pill, backgroundColor: colors.accentSoft },
  activeLabel: { color: colors.accentDark, fontSize: 10, fontWeight: "700" },
  more: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  empty: { alignItems: "center", paddingHorizontal: spacing.xl },
  emptyImage: { width: 58, height: 56, marginBottom: spacing.sm },
  emptyTitle: { color: colors.ink, fontSize: 17, fontWeight: "600" },
  emptyCopy: { marginTop: spacing.xs, color: colors.muted, fontSize: 13, textAlign: "center" },
});
