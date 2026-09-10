import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import {
  Archive,
  ArchiveRestore,
  Check,
  ChevronLeft,
  Ellipsis,
  FolderInput,
  FolderPlus,
  Inbox,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Trash2,
  Undo2,
} from "lucide-react-native";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  SectionList,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Animated, {
  cancelAnimation,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";

import type { ChatGroup, ChatSpec, Connection } from "../../api/types";
import { MobileBottomSheet } from "../../components/MobileBottomSheet";
import { MobileToast } from "../../components/MobileToast";
import { AgentAvatar } from "../../features/agents/AgentAvatar";
import {
  AnchoredActionMenu,
  type AnchorRect,
  type AnchoredMenuAction,
} from "../../features/chat/AnchoredActionMenu";
import { ApprovalInboxSheet } from "../../features/chat/ApprovalInboxSheet";
import {
  buildChatSections,
  type ChatSection,
} from "../../features/chats/grouping";
import { WorkspaceBadge } from "../../features/workspaces/WorkspaceSwitcher";
import { mobileText } from "../../i18n/locale";
import { resolveAgentAppearance } from "../../storage/agentAppearance";
import {
  type ChatActivity,
  type ChatActivityMap,
  resolveChatActivity,
} from "../../storage/chatActivity";
import { useAppStore } from "../../store/app";
import { qwenPawBrandAssets } from "../../theme/brandAssets";
import { colors, radius, spacing } from "../../theme/tokens";

export default function ChatsScreen() {
  const params = useLocalSearchParams<{ approval?: string }>();
  const chats = useAppStore((state) => state.chats);
  const archivedChats = useAppStore((state) => state.archivedChats);
  const groups = useAppStore((state) => state.chatGroups);
  const supportsChatGroups = useAppStore((state) => state.supportsChatGroups);
  const chatActivity = useAppStore((state) => state.chatActivity);
  const agents = useAppStore((state) => state.agents);
  const connection = useAppStore((state) => state.connection);
  const appearances = useAppStore((state) => state.agentAppearances);
  const pinnedChatId = useAppStore((state) => state.pinnedChatId);
  const pendingApprovals = useAppStore((state) => state.pendingApprovals);
  const refreshChats = useAppStore((state) => state.refreshChats);
  const refreshArchivedChats = useAppStore(
    (state) => state.refreshArchivedChats,
  );
  const createChat = useAppStore((state) => state.createChat);
  const createChatGroup = useAppStore((state) => state.createChatGroup);
  const renameChatGroup = useAppStore((state) => state.renameChatGroup);
  const deleteChatGroup = useAppStore((state) => state.deleteChatGroup);
  const moveChatToGroup = useAppStore((state) => state.moveChatToGroup);
  const archiveChat = useAppStore((state) => state.archiveChat);
  const unarchiveChat = useAppStore((state) => state.unarchiveChat);
  const deleteChat = useAppStore((state) => state.deleteChat);
  const setPinnedChat = useAppStore((state) => state.setPinnedChat);
  const refreshApprovals = useAppStore((state) => state.refreshApprovals);
  const approveRequest = useAppStore((state) => state.approveRequest);
  const denyRequest = useAppStore((state) => state.denyRequest);
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [groupEditorOpen, setGroupEditorOpen] = useState(false);
  const [groupName, setGroupName] = useState("");
  const [savingGroup, setSavingGroup] = useState(false);
  const [editingGroup, setEditingGroup] = useState<ChatGroup | null>(null);
  const [groupError, setGroupError] = useState<string | null>(null);
  const [approvalInboxOpen, setApprovalInboxOpen] = useState(false);
  const [chatMenu, setChatMenu] = useState<{
    anchor: AnchorRect;
    chat: ChatSpec;
    confirmDelete?: boolean;
  } | null>(null);
  const [groupMenu, setGroupMenu] = useState<{
    anchor: AnchorRect;
    confirmDelete?: boolean;
    group: ChatGroup;
  } | null>(null);
  const [groupPickerChat, setGroupPickerChat] = useState<ChatSpec | null>(null);
  const [toast, setToast] = useState<{
    message: string;
    tone: "error" | "success";
  } | null>(null);

  const activeAgent = agents.find((agent) => agent.id === connection?.agentId);
  const agentAppearance = resolveAgentAppearance(
    appearances,
    connection,
    activeAgent,
  );
  const sourceChats = showArchived ? archivedChats : chats;
  const filteredChats = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return sourceChats;
    return sourceChats.filter((chat) =>
      (chat.name || "新会话").toLocaleLowerCase().includes(normalized),
    );
  }, [query, sourceChats]);
  const sections = useMemo<ChatSection[]>(
    () =>
      showArchived
        ? [{ key: "archived", title: "已归档", data: filteredChats }]
        : buildChatSections(
            filteredChats,
            groups,
            pinnedChatId,
            connection,
            chatActivity,
          ),
    [
      chatActivity,
      connection,
      filteredChats,
      groups,
      pinnedChatId,
      showArchived,
    ],
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const action = showArchived ? refreshArchivedChats : refreshChats;
    await action().catch(() => undefined);
    setRefreshing(false);
  }, [refreshArchivedChats, refreshChats, showArchived]);

  useFocusEffect(
    useCallback(() => {
      let busy = false;
      const poll = async () => {
        if (busy) return;
        busy = true;
        await Promise.all([
          refreshChats().catch(() => undefined),
          refreshApprovals().catch(() => undefined),
        ]);
        busy = false;
      };
      void poll();
      const timer = setInterval(() => void poll(), 4000);
      return () => clearInterval(timer);
    }, [refreshApprovals, refreshChats]),
  );

  const create = async () => {
    setCreating(true);
    try {
      const chat = await createChat();
      router.push({ pathname: "/chat/[id]", params: { id: chat.id } });
    } finally {
      setCreating(false);
    }
  };

  const saveGroup = async () => {
    const name = groupName.trim();
    if (!name) return;
    const duplicate = groups.some(
      (group) =>
        group.id !== editingGroup?.id &&
        group.name.trim().toLocaleLowerCase() === name.toLocaleLowerCase(),
    );
    if (duplicate) {
      setGroupError("分组名称已存在，请换一个容易区分的名称。");
      return;
    }
    setGroupError(null);
    setSavingGroup(true);
    try {
      if (editingGroup) await renameChatGroup(editingGroup.id, name);
      else await createChatGroup(name);
      setGroupName("");
      setEditingGroup(null);
      setGroupEditorOpen(false);
    } catch (error) {
      setGroupError(errorMessage(error));
    } finally {
      setSavingGroup(false);
    }
  };

  const openGroupEditor = (group: ChatGroup | null) => {
    setEditingGroup(group);
    setGroupName(group?.name ?? "");
    setGroupError(null);
    setGroupEditorOpen(true);
  };

  const closeGroupEditor = () => {
    setGroupEditorOpen(false);
    setEditingGroup(null);
    setGroupError(null);
  };

  const notify = (message: string, tone: "error" | "success" = "error") => {
    setToast({ message, tone });
  };

  const deleteSelectedChat = async (chat: ChatSpec) => {
    try {
      await deleteChat(chat.id);
      notify("会话已删除", "success");
    } catch (error) {
      notify(`删除失败：${errorMessage(error)}`);
    }
  };

  const deleteSelectedGroup = async (group: ChatGroup) => {
    try {
      await deleteChatGroup(group.id);
      notify("分组已删除，会话已移到未分组", "success");
    } catch (error) {
      notify(`删除失败：${errorMessage(error)}`);
    }
  };

  const moveSelectedChat = async (groupId: string | null) => {
    const chat = groupPickerChat;
    if (!chat) return;
    setGroupPickerChat(null);
    try {
      await moveChatToGroup(chat.id, groupId);
      notify("会话已移动", "success");
    } catch (error) {
      notify(`移动失败：${errorMessage(error)}`);
    }
  };

  const chatMenuActions: AnchoredMenuAction[] = !chatMenu
    ? []
    : chatMenu.confirmDelete
    ? [
        {
          icon: Undo2,
          label: "取消",
          onPress: () => undefined,
        },
        {
          icon: Trash2,
          label: "确认删除",
          onPress: () => void deleteSelectedChat(chatMenu.chat),
          tone: "danger",
        },
      ]
    : showArchived
    ? [
        {
          icon: ArchiveRestore,
          label: "恢复",
          onPress: () =>
            void unarchiveChat(chatMenu.chat.id)
              .then(() => notify("会话已恢复", "success"))
              .catch((error) => notify(`恢复失败：${errorMessage(error)}`)),
        },
        {
          icon: Trash2,
          label: "永久删除",
          onPress: () => setChatMenu({ ...chatMenu, confirmDelete: true }),
          tone: "danger",
        },
      ]
    : [
        {
          icon: chatMenu.chat.id === pinnedChatId ? PinOff : Pin,
          label: chatMenu.chat.id === pinnedChatId ? "取消置顶" : "置顶",
          onPress: () =>
            void setPinnedChat(
              chatMenu.chat.id === pinnedChatId ? null : chatMenu.chat.id,
            ),
        },
        ...(supportsChatGroups
          ? [
              {
                icon: FolderInput,
                label: "移动",
                onPress: () => setGroupPickerChat(chatMenu.chat),
              },
            ]
          : []),
        {
          icon: Archive,
          label: "归档",
          onPress: () =>
            void archiveChat(chatMenu.chat.id)
              .then(() => notify("会话已归档", "success"))
              .catch((error) => notify(`归档失败：${errorMessage(error)}`)),
        },
        {
          icon: Trash2,
          label: "删除",
          onPress: () => setChatMenu({ ...chatMenu, confirmDelete: true }),
          tone: "danger",
        },
      ];

  const groupMenuActions: AnchoredMenuAction[] = !groupMenu
    ? []
    : groupMenu.confirmDelete
    ? [
        { icon: Undo2, label: "取消", onPress: () => undefined },
        {
          icon: Trash2,
          label: "确认删除",
          onPress: () => void deleteSelectedGroup(groupMenu.group),
          tone: "danger",
        },
      ]
    : [
        {
          icon: Pencil,
          label: "重命名",
          onPress: () => openGroupEditor(groupMenu.group),
        },
        {
          icon: Trash2,
          label: "删除分组",
          onPress: () => setGroupMenu({ ...groupMenu, confirmDelete: true }),
          tone: "danger",
        },
      ];

  return (
    <SafeAreaView edges={["top"]} style={styles.root}>
      <View style={styles.shell}>
        <View style={styles.header}>
          {showArchived ? (
            <Pressable
              accessibilityLabel="返回会话"
              onPress={() => setShowArchived(false)}
              style={styles.headerButton}
            >
              <ChevronLeft color={colors.ink} size={25} />
            </Pressable>
          ) : (
            <Text maxFontSizeMultiplier={1.4} style={styles.title}>
              {mobileText("会话", "Chats")}
            </Text>
          )}
          {showArchived ? (
            <Text maxFontSizeMultiplier={1.4} style={styles.archiveTitle}>
              {mobileText("已归档", "Archived")}
            </Text>
          ) : null}
          <View style={styles.headerActions}>
            {!showArchived ? (
              <>
                <Pressable
                  accessibilityLabel={`已归档 ${archivedChats.length} 个会话`}
                  onPress={() => setShowArchived(true)}
                  style={styles.headerButton}
                >
                  <Archive color={colors.ink} size={21} />
                  {archivedChats.length ? (
                    <View style={styles.badge}>
                      <Text
                        maxFontSizeMultiplier={1.1}
                        style={styles.badgeText}
                      >
                        {Math.min(99, archivedChats.length)}
                      </Text>
                    </View>
                  ) : null}
                </Pressable>
                {supportsChatGroups ? (
                  <Pressable
                    accessibilityLabel="新建分组"
                    onPress={() => openGroupEditor(null)}
                    style={styles.headerButton}
                  >
                    <FolderPlus color={colors.ink} size={21} />
                  </Pressable>
                ) : null}
                <Pressable
                  accessibilityLabel="新建会话"
                  onPress={() => void create()}
                  style={[styles.headerButton, styles.primaryHeaderButton]}
                >
                  {creating ? (
                    <ActivityIndicator color={colors.white} size="small" />
                  ) : (
                    <Plus color={colors.white} size={21} strokeWidth={2.2} />
                  )}
                </Pressable>
              </>
            ) : (
              <View style={styles.headerButton} />
            )}
          </View>
        </View>

        {!showArchived ? <WorkspaceBadge /> : null}

        <View style={styles.search}>
          <Search color={colors.faint} size={17} />
          <TextInput
            clearButtonMode="while-editing"
            onChangeText={setQuery}
            placeholder={showArchived
              ? mobileText("搜索已归档会话", "Search archived chats")
              : mobileText("搜索会话", "Search chats")}
            placeholderTextColor={colors.faint}
            returnKeyType="search"
            maxFontSizeMultiplier={1.35}
            style={styles.searchInput}
            value={query}
          />
        </View>

        {!showArchived ? (
          <Pressable
            accessibilityLabel="打开待审批 Inbox"
            accessibilityRole="button"
            onPress={() => setApprovalInboxOpen(true)}
            style={({ pressed }) => [
              styles.inboxCard,
              pendingApprovals.length > 0 && styles.inboxCardActive,
              pressed && styles.rowPressed,
            ]}
          >
            <View style={styles.inboxIcon}>
              <Inbox color={colors.accentDark} size={19} />
            </View>
            <View style={styles.inboxText}>
              <Text maxFontSizeMultiplier={1.35} style={styles.inboxTitle}>
                {mobileText("审批 Inbox", "Approval Inbox")}
              </Text>
              <Text
                maxFontSizeMultiplier={1.25}
                numberOfLines={1}
                style={styles.inboxSubtitle}
              >
                {pendingApprovals.length
                  ? mobileText(
                      `${pendingApprovals.length} 项工具操作等待确认`,
                      `${pendingApprovals.length} tool actions need approval`,
                    )
                  : mobileText(
                      "所有需要确认的操作都会集中在这里",
                      "Review every action that needs your approval",
                    )}
              </Text>
            </View>
            <View
              style={[
                styles.inboxCount,
                !pendingApprovals.length && styles.inboxCountEmpty,
              ]}
            >
              <Text
                maxFontSizeMultiplier={1.1}
                style={[
                  styles.inboxCountText,
                  !pendingApprovals.length && styles.inboxCountTextEmpty,
                ]}
              >
                {pendingApprovals.length}
              </Text>
            </View>
          </Pressable>
        ) : null}

        <SectionList
          contentContainerStyle={
            sections.length ? styles.list : styles.emptyList
          }
          sections={sections}
          keyExtractor={(item) => item.id}
          keyboardShouldPersistTaps="handled"
          ListEmptyComponent={
            sections.length ? null : (
              <EmptyChats
                archived={showArchived}
                filtered={Boolean(query.trim())}
              />
            )
          }
          refreshControl={
            <RefreshControl
              onRefresh={() => void refresh()}
              refreshing={refreshing}
              tintColor={colors.accent}
            />
          }
          renderSectionHeader={({ section }) => (
            <View style={styles.sectionHeader}>
              {section.pinned ? (
                <Pin color={colors.accent} fill={colors.accent} size={12} />
              ) : null}
              <Text maxFontSizeMultiplier={1.3} style={styles.sectionTitle}>
                {displaySectionTitle(section.title)}
              </Text>
              <Text maxFontSizeMultiplier={1.2} style={styles.sectionCount}>
                {section.data.length}
              </Text>
              {!section.data.length ? (
                <Text maxFontSizeMultiplier={1.15} style={styles.emptyGroup}>
                  {mobileText("空分组", "Empty")}
                </Text>
              ) : null}
              <View style={styles.sectionSpacer} />
              {section.group?.kind === "custom" ? (
                <GroupActionButton
                  group={section.group}
                  onActions={(anchor) =>
                    setGroupMenu({
                      anchor,
                      group: section.group!,
                    })
                  }
                />
              ) : null}
            </View>
          )}
          renderItem={({ item, section, index }) => (
            <ChatRow
              appearance={agentAppearance}
              activity={chatActivity}
              chat={item}
              connection={connection}
              first={index === 0}
              last={index === section.data.length - 1}
              onActions={(anchor) => setChatMenu({ anchor, chat: item })}
              pinned={item.id === pinnedChatId}
            />
          )}
          stickySectionHeadersEnabled={false}
        />

        <AnchoredActionMenu
          actions={chatMenuActions}
          anchor={chatMenu?.anchor ?? null}
          onClose={() => setChatMenu(null)}
          title={
            chatMenu?.confirmDelete
              ? "此操作无法撤销"
              : chatMenu?.chat.name || "会话操作"
          }
        />
        <AnchoredActionMenu
          actions={groupMenuActions}
          anchor={groupMenu?.anchor ?? null}
          onClose={() => setGroupMenu(null)}
          title={
            groupMenu?.confirmDelete
              ? "会话将移到未分组"
              : groupMenu?.group.name
          }
        />
        <MobileBottomSheet
          onClose={closeGroupEditor}
          subtitle="用清晰的名称整理同一主题的会话"
          title={editingGroup ? "重命名分组" : "新建会话分组"}
          visible={groupEditorOpen}
        >
          <TextInput
            autoFocus
            maxFontSizeMultiplier={1.35}
            maxLength={40}
            onChangeText={(value) => {
              setGroupName(value);
              setGroupError(null);
            }}
            onSubmitEditing={() => void saveGroup()}
            placeholder="例如：产品研发"
            placeholderTextColor={colors.faint}
            returnKeyType="done"
            style={[styles.groupInput, groupError && styles.groupInputError]}
            value={groupName}
          />
          {groupError ? (
            <Text accessibilityLiveRegion="polite" style={styles.groupError}>
              {groupError}
            </Text>
          ) : null}
          <Pressable
            accessibilityRole="button"
            disabled={!groupName.trim() || savingGroup}
            onPress={() => void saveGroup()}
            style={({ pressed }) => [
              styles.groupSave,
              (!groupName.trim() || savingGroup) && styles.disabled,
              pressed && styles.rowPressed,
            ]}
          >
            {savingGroup ? (
              <ActivityIndicator color={colors.white} size="small" />
            ) : null}
            <Text style={styles.groupSaveText}>
              {savingGroup ? "保存中…" : editingGroup ? "保存" : "创建"}
            </Text>
          </Pressable>
        </MobileBottomSheet>
        <MobileBottomSheet
          onClose={() => setGroupPickerChat(null)}
          subtitle={groupPickerChat?.name || "新会话"}
          title="移动到分组"
          visible={Boolean(groupPickerChat)}
        >
          <ScrollView
            contentContainerStyle={styles.groupPicker}
            showsVerticalScrollIndicator={false}
            style={styles.groupPickerScroll}
          >
            <GroupPickerRow
              active={!groupPickerChat?.group_id}
              label="未分组"
              onPress={() => void moveSelectedChat(null)}
            />
            {groups.map((group) => (
              <GroupPickerRow
                active={groupPickerChat?.group_id === group.id}
                key={group.id}
                label={group.name}
                onPress={() => void moveSelectedChat(group.id)}
              />
            ))}
          </ScrollView>
        </MobileBottomSheet>
        <ApprovalInboxSheet
          approvals={pendingApprovals}
          chats={[...chats, ...archivedChats]}
          onApprove={approveRequest}
          onClose={() => {
            setApprovalInboxOpen(false);
            if (params.approval === "1") router.setParams({ approval: "" });
          }}
          onDeny={denyRequest}
          visible={approvalInboxOpen || params.approval === "1"}
        />
        <MobileToast
          message={toast?.message ?? null}
          onHide={() => setToast(null)}
          tone={toast?.tone}
        />
      </View>
    </SafeAreaView>
  );
}

const ChatRow = memo(function ChatRow({
  appearance,
  activity,
  chat,
  connection,
  first,
  last,
  onActions,
  pinned,
}: {
  appearance: { name: string; avatarUri?: string };
  activity: ChatActivityMap;
  chat: ChatSpec;
  connection: Connection | null;
  first: boolean;
  last: boolean;
  onActions: (anchor: AnchorRect) => void;
  pinned: boolean;
}) {
  const chatActivity = resolveChatActivity(connection, chat, activity);
  const rowRef = useRef<View>(null);
  const moreRef = useRef<View>(null);
  const showActions = (target: View | null) => {
    target?.measureInWindow((x, y, width, height) => {
      onActions({ x, y, width, height });
    });
  };
  return (
    <Pressable
      delayLongPress={320}
      onLongPress={() => showActions(rowRef.current)}
      onPress={() =>
        router.push({ pathname: "/chat/[id]", params: { id: chat.id } })
      }
      ref={rowRef}
      style={({ pressed }) => [
        styles.row,
        first && styles.rowFirst,
        last && styles.rowLast,
        pressed && styles.rowPressed,
      ]}
    >
      <View style={styles.avatarWrap}>
        <AgentAvatar
          active={pinned}
          avatarUri={appearance.avatarUri}
          size={48}
        />
        <ActivityDot activity={chatActivity} />
      </View>
      <View style={[styles.rowBody, !last && styles.rowDivider]}>
        <View style={styles.rowTop}>
          <View style={styles.rowTitleWrap}>
            <Text
              maxFontSizeMultiplier={1.35}
              numberOfLines={1}
              style={styles.rowTitle}
            >
              {chat.name || mobileText("新会话", "New Chat")}
            </Text>
            {pinned ? (
              <Pin color={colors.accent} fill={colors.accent} size={12} />
            ) : null}
          </View>
          <Text maxFontSizeMultiplier={1.25} style={styles.time}>
            {formatTime(chat.updated_at)}
          </Text>
          <Pressable
            accessibilityLabel="会话操作"
            hitSlop={7}
            onPress={(event) => {
              event.stopPropagation();
              showActions(moreRef.current);
            }}
            ref={moreRef}
            style={styles.more}
          >
            <Ellipsis color={colors.faint} size={19} />
          </Pressable>
        </View>
        <Text
          maxFontSizeMultiplier={1.3}
          numberOfLines={1}
          style={styles.preview}
        >
          {activityLabel(chatActivity, appearance.name)}
        </Text>
      </View>
    </Pressable>
  );
});

function GroupActionButton({
  group,
  onActions,
}: {
  group: ChatGroup;
  onActions: (anchor: AnchorRect) => void;
}) {
  const buttonRef = useRef<View>(null);
  return (
    <Pressable
      accessibilityLabel={`${group.name}分组操作`}
      hitSlop={8}
      onPress={() =>
        buttonRef.current?.measureInWindow((x, y, width, height) => {
          onActions({ x, y, width, height });
        })
      }
      ref={buttonRef}
      style={({ pressed }) => [
        styles.sectionAction,
        pressed && styles.rowPressed,
      ]}
    >
      <Ellipsis color={colors.faint} size={17} />
    </Pressable>
  );
}

function GroupPickerRow({
  active,
  label,
  onPress,
}: {
  active: boolean;
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [
        styles.groupPickerRow,
        active && styles.groupPickerRowActive,
        pressed && styles.rowPressed,
      ]}
    >
      <FolderInput
        color={active ? colors.accentDark : colors.muted}
        size={20}
      />
      <Text
        maxFontSizeMultiplier={1.35}
        numberOfLines={1}
        style={styles.groupPickerLabel}
      >
        {label}
      </Text>
      {active ? (
        <Check color={colors.accentDark} size={20} strokeWidth={2.2} />
      ) : null}
    </Pressable>
  );
}

function ActivityDot({ activity }: { activity: ChatActivity }) {
  const reducedMotion = useReducedMotion();
  const pulse = useSharedValue(1);
  useEffect(() => {
    if (activity === "running" && !reducedMotion) {
      pulse.value = withRepeat(withTiming(1.8, { duration: 900 }), -1, true);
      return () => cancelAnimation(pulse);
    }
    cancelAnimation(pulse);
    pulse.value = 1;
    return undefined;
  }, [activity, pulse, reducedMotion]);
  const pulseStyle = useAnimatedStyle(() => ({
    opacity: Math.max(0, 1.25 - pulse.value * 0.55),
    transform: [{ scale: pulse.value }],
  }));
  const color =
    activity === "running"
      ? "#2F80ED"
      : activity === "unread"
      ? "#34C759"
      : "#A9A5A1";
  return (
    <View style={styles.activitySlot}>
      {activity === "running" ? (
        <Animated.View
          style={[styles.activityPulse, { backgroundColor: color }, pulseStyle]}
        />
      ) : null}
      <View
        style={[
          styles.activityDot,
          { backgroundColor: activity === "idle" ? colors.surface : color },
          activity === "idle" && styles.activityIdle,
        ]}
      />
    </View>
  );
}

function activityLabel(activity: ChatActivity, agentName: string): string {
  if (activity === "running") {
    return mobileText(`${agentName} 正在回复…`, `${agentName} is replying…`);
  }
  if (activity === "unread") return mobileText("新回复 · 未读", "New reply · Unread");
  if (activity === "read") return mobileText("已读", "Read");
  return mobileText("尚未开始", "Not started");
}

function displaySectionTitle(title: string): string {
  if (title === "置顶") return mobileText(title, "Pinned");
  if (title === "未分组") return mobileText(title, "Ungrouped");
  if (title === "定时任务") return mobileText(title, "Scheduled tasks");
  if (title === "子智能体") return mobileText(title, "Sub-agents");
  if (title === "已归档") return mobileText(title, "Archived");
  return title;
}

function EmptyChats({
  archived,
  filtered,
}: {
  archived: boolean;
  filtered: boolean;
}) {
  const title = filtered
    ? "没有匹配的会话"
    : archived
    ? "还没有归档会话"
    : "开始第一次对话";
  const copy = filtered
    ? "换个关键词再试试。"
    : archived
    ? "长按会话即可将它归档。"
    : "点击右上角加号创建会话。";
  const showMascot = !archived && !filtered;
  return (
    <View style={styles.empty}>
      {showMascot ? (
        <Image
          accessible={false}
          resizeMode="contain"
          source={qwenPawBrandAssets.wave}
          style={styles.emptyMascot}
        />
      ) : (
        <View style={styles.emptyIcon}>
          {archived ? (
            <Archive color={colors.accentDark} size={27} />
          ) : (
            <Search color={colors.accentDark} size={27} strokeWidth={1.8} />
          )}
        </View>
      )}
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyCopy}>{copy}</Text>
    </View>
  );
}

function formatTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return new Intl.DateTimeFormat(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "numeric",
    day: "numeric",
  }).format(date);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请稍后重试。";
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  shell: { flex: 1, width: "100%", maxWidth: 760, alignSelf: "center" },
  header: {
    minHeight: 66,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
  },
  title: {
    flex: 1,
    minWidth: 0,
    paddingHorizontal: spacing.xs,
    color: colors.ink,
    fontSize: 31,
    fontWeight: "700",
    letterSpacing: -1.1,
  },
  archiveTitle: {
    flex: 1,
    color: colors.ink,
    textAlign: "center",
    fontSize: 17,
    fontWeight: "700",
  },
  headerActions: { flexDirection: "row", alignItems: "center" },
  headerButton: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
  },
  primaryHeaderButton: { backgroundColor: colors.accent },
  badge: {
    position: "absolute",
    right: 0,
    top: 1,
    minWidth: 16,
    height: 16,
    paddingHorizontal: 3,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: colors.accent,
  },
  badgeText: { color: colors.white, fontSize: 9, fontWeight: "700" },
  search: {
    height: 44,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
    backgroundColor: colors.searchBackground,
  },
  searchInput: { flex: 1, color: colors.ink, fontSize: 16, paddingVertical: 0 },
  inboxCard: {
    minHeight: 62,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.sm,
  },
  inboxCardActive: {
    borderColor: colors.accent,
    backgroundColor: colors.accentSoft,
  },
  inboxIcon: {
    width: 38,
    height: 38,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: colors.accentSoft,
  },
  inboxText: { flex: 1, minWidth: 0 },
  inboxTitle: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  inboxSubtitle: { marginTop: 3, color: colors.muted, fontSize: 11 },
  inboxCount: {
    minWidth: 25,
    height: 25,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 13,
    backgroundColor: colors.accent,
    paddingHorizontal: 6,
  },
  inboxCountEmpty: { backgroundColor: colors.searchBackground },
  inboxCountText: { color: colors.white, fontSize: 11, fontWeight: "800" },
  inboxCountTextEmpty: { color: colors.muted },
  list: { paddingBottom: spacing.xl },
  emptyList: { flexGrow: 1, justifyContent: "center", paddingBottom: 90 },
  sectionHeader: {
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: spacing.md,
    paddingTop: 8,
    backgroundColor: colors.groupedBackground,
  },
  sectionTitle: { color: colors.ink, fontSize: 13, fontWeight: "700" },
  sectionCount: { color: colors.faint, fontSize: 11 },
  emptyGroup: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 5,
    color: colors.faint,
    backgroundColor: colors.searchBackground,
    fontSize: 9,
    fontWeight: "600",
  },
  sectionSpacer: { flex: 1 },
  sectionAction: {
    width: 44,
    height: 44,
    marginRight: -10,
    alignItems: "center",
    justifyContent: "center",
  },
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
  rowFirst: {
    borderTopWidth: 1,
    borderTopLeftRadius: radius.md,
    borderTopRightRadius: radius.md,
  },
  rowLast: {
    marginBottom: spacing.xs,
    borderBottomWidth: 1,
    borderBottomLeftRadius: radius.md,
    borderBottomRightRadius: radius.md,
  },
  rowPressed: { backgroundColor: colors.pressed },
  avatarWrap: { position: "relative" },
  activitySlot: {
    position: "absolute",
    right: -2,
    bottom: -2,
    width: 15,
    height: 15,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: colors.surface,
  },
  activityPulse: { position: "absolute", width: 8, height: 8, borderRadius: 4 },
  activityDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: colors.surface,
  },
  activityIdle: { borderColor: "#A9A5A1" },
  rowBody: {
    flex: 1,
    minWidth: 0,
    alignSelf: "stretch",
    justifyContent: "center",
    gap: 5,
    paddingRight: 7,
  },
  rowDivider: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
  },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 6 },
  rowTitleWrap: {
    flex: 1,
    minWidth: 0,
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
  },
  rowTitle: {
    flexShrink: 1,
    color: colors.ink,
    fontSize: 16,
    fontWeight: "600",
  },
  time: { color: colors.faint, fontSize: 11 },
  more: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  preview: { color: colors.muted, fontSize: 13 },
  empty: { alignItems: "center", paddingHorizontal: spacing.xl },
  emptyIcon: {
    width: 58,
    height: 58,
    borderRadius: 18,
    backgroundColor: colors.accentSoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.md,
  },
  emptyMascot: { width: 104, height: 104, marginBottom: spacing.sm },
  emptyTitle: { color: colors.ink, fontSize: 18, fontWeight: "600" },
  emptyCopy: { color: colors.muted, fontSize: 14, marginTop: spacing.xs },
  groupInput: {
    height: 50,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    color: colors.ink,
    backgroundColor: colors.surface,
    fontSize: 16,
  },
  groupInputError: { borderColor: colors.danger },
  groupError: {
    marginTop: spacing.xs,
    color: colors.danger,
    fontSize: 13,
    lineHeight: 18,
  },
  groupSave: {
    height: 48,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    marginTop: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.accent,
  },
  groupSaveText: { color: colors.white, fontSize: 15, fontWeight: "700" },
  groupPickerScroll: { maxHeight: 360 },
  groupPicker: { gap: spacing.xs, paddingBottom: spacing.xs },
  groupPickerRow: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  groupPickerRowActive: {
    borderColor: colors.accent,
    backgroundColor: colors.accentSoft,
  },
  groupPickerLabel: {
    flex: 1,
    minWidth: 0,
    color: colors.ink,
    fontSize: 15,
    fontWeight: "600",
  },
  disabled: { opacity: 0.35 },
});
