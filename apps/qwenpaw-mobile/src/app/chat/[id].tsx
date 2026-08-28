import * as DocumentPicker from "expo-document-picker";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import {
  Archive,
  ChevronLeft,
  Ellipsis,
  FileUp,
  Pin,
  PinOff,
  Send,
  Settings2,
  Square,
  Trash2,
  Undo2,
  X,
} from "lucide-react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { QwenPawClient } from "../../api/client";
import { toDisplayTurns } from "../../api/messages";
import type { ContentItem, DisplayTurn } from "../../api/types";
import { MobileToast } from "../../components/MobileToast";
import { AgentAvatar } from "../../features/agents/AgentAvatar";
import {
  AnchoredActionMenu,
  type AnchoredMenuAction,
  type AnchorRect,
} from "../../features/chat/AnchoredActionMenu";
import { ApprovalCard } from "../../features/chat/ApprovalCard";
import { MessageTurnView } from "../../features/chat/MessageTurn";
import {
  SessionControlBar,
  SessionControlSheet,
  type SessionControlKind,
} from "../../features/chat/SessionRuntimeControls";
import { useSessionControls } from "../../features/chat/useSessionControls";
import { resolveAgentAppearance } from "../../storage/agentAppearance";
import { useAppStore } from "../../store/app";
import { selectChatMessages } from "../../store/selectors";
import { colors, radius, spacing } from "../../theme/tokens";

interface PendingAttachment {
  id: string;
  name: string;
  content: ContentItem;
}

export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const status = useAppStore((state) => state.status);
  const connection = useAppStore((state) => state.connection);
  const agents = useAppStore((state) => state.agents);
  const appearances = useAppStore((state) => state.agentAppearances);
  const chats = useAppStore((state) => state.chats);
  const messages = useAppStore((state) => selectChatMessages(state.messages, id));
  const activeAbort = useAppStore((state) => state.activeAbort);
  const activeStreamChatId = useAppStore((state) => state.activeStreamChatId);
  const pinnedChatId = useAppStore((state) => state.pinnedChatId);
  const pendingApprovals = useAppStore((state) => state.pendingApprovals);
  const loadChat = useAppStore((state) => state.loadChat);
  const reconnectChat = useAppStore((state) => state.reconnectChat);
  const detachStream = useAppStore((state) => state.detachStream);
  const send = useAppStore((state) => state.send);
  const stop = useAppStore((state) => state.stop);
  const deleteChat = useAppStore((state) => state.deleteChat);
  const archiveChat = useAppStore((state) => state.archiveChat);
  const setPinnedChat = useAppStore((state) => state.setPinnedChat);
  const refreshApprovals = useAppStore((state) => state.refreshApprovals);
  const approveRequest = useAppStore((state) => state.approveRequest);
  const denyRequest = useAppStore((state) => state.denyRequest);
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [controlsOpen, setControlsOpen] = useState(false);
  const [controlsKind, setControlsKind] = useState<SessionControlKind>("model");
  const [actionMenu, setActionMenu] = useState<{
    anchor: AnchorRect;
    confirmDelete?: boolean;
  } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const listRef = useRef<FlatList<DisplayTurn>>(null);
  const actionRef = useRef<View>(null);
  const chat = useMemo(() => chats.find((item) => item.id === id), [chats, id]);
  const turns = useMemo(() => toDisplayTurns(messages), [messages]);
  const pinned = chat?.id === pinnedChatId;
  const activeAgent = agents.find((agent) => agent.id === connection?.agentId);
  const appearance = resolveAgentAppearance(appearances, connection, activeAgent);
  const controls = useSessionControls(connection, chat);
  const isStreaming = activeStreamChatId === chat?.id && Boolean(activeAbort);
  const chatApprovals = useMemo(() => pendingApprovals.filter((approval) =>
    approval.root_session_id === chat?.session_id ||
    approval.root_session_id === chat?.id), [chat, pendingApprovals]);

  const openControls = useCallback((kind: SessionControlKind) => {
    setControlsKind(kind);
    setControlsOpen(true);
  }, []);

  useFocusEffect(useCallback(() => {
    if (status !== "ready" || !id) return undefined;
    let cancelled = false;
    void loadChat(id)
      .then((remoteStatus) => {
        if (!cancelled && remoteStatus === "running") {
          return reconnectChat(id);
        }
        return undefined;
      })
      .catch((error) => {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : "加载会话失败");
        }
      });
    return () => {
      cancelled = true;
      detachStream(id);
    };
  }, [detachStream, id, loadChat, reconnectChat, status]));

  useFocusEffect(useCallback(() => {
    let busy = false;
    const poll = async () => {
      if (busy) return;
      busy = true;
      await refreshApprovals().catch(() => undefined);
      busy = false;
    };
    void poll();
    const timer = setInterval(() => void poll(), 2500);
    return () => clearInterval(timer);
  }, [refreshApprovals]));

  useEffect(() => {
    if (turns.length) {
      requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
    }
  }, [turns]);

  const pickAttachment = async () => {
    if (!connection) return;
    const result = await DocumentPicker.getDocumentAsync({ multiple: true });
    if (result.canceled) return;
    setUploading(true);
    try {
      const uploadedItems: PendingAttachment[] = [];
      for (const asset of result.assets) {
        const uploaded = await new QwenPawClient(connection).upload(asset);
        let content: ContentItem;
        if (asset.mimeType?.startsWith("image/")) {
          content = { type: "image", image_url: uploaded.url };
        } else if (asset.mimeType?.startsWith("video/")) {
          content = { type: "video", video_url: uploaded.url };
        } else if (asset.mimeType?.startsWith("audio/")) {
          content = { type: "audio", data: uploaded.url };
        } else {
          content = {
            type: "file",
            file_url: uploaded.url,
            file_name: uploaded.file_name,
          };
        }
        uploadedItems.push({
          id: `${uploaded.url}:${uploaded.file_name}`,
          name: uploaded.file_name,
          content,
        });
      }
      setAttachments((current) => [...current, ...uploadedItems]);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "附件上传失败，请稍后重试");
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    const value = text.trim();
    if (!chat || (!value && !attachments.length) || isStreaming) return;
    setText("");
    const content = attachments.map((item) => item.content);
    setAttachments([]);
    const loopMode = controls.beginSubmission();
    await send(chat, value, content, {
      approvalLevel: controls.effectiveApproval,
      loopMode,
      modelSlotOverride: controls.sessionModelOverride,
    });
  };

  const removeChat = async () => {
    if (!chat) return;
    try {
      await deleteChat(chat.id);
      router.back();
    } catch (error) {
      setToast(error instanceof Error ? error.message : "删除失败，请稍后重试");
    }
  };

  const archive = () => {
    if (!chat) return;
    void archiveChat(chat.id).then(() => router.back()).catch((error) => {
      setToast(error instanceof Error ? error.message : "归档失败，请稍后重试");
    });
  };

  const togglePin = () => {
    if (!chat) return;
    void setPinnedChat(pinned ? null : chat.id);
  };

  const openActions = () => {
    actionRef.current?.measureInWindow((x, y, width, height) => {
      setActionMenu({ anchor: { x, y, width, height } });
    });
  };

  const actionMenuActions: AnchoredMenuAction[] = !actionMenu
    ? []
    : actionMenu.confirmDelete
      ? [
          { icon: Undo2, label: "取消", onPress: () => undefined },
          {
            icon: Trash2,
            label: "确认删除",
            onPress: () => void removeChat(),
            tone: "danger",
          },
        ]
      : [
          {
            icon: Settings2,
            label: "会话控制",
            onPress: () => openControls("model"),
          },
          {
            icon: pinned ? PinOff : Pin,
            label: pinned ? "取消置顶" : "置顶",
            onPress: togglePin,
          },
          { icon: Archive, label: "归档", onPress: archive },
          {
            icon: Trash2,
            label: "删除",
            onPress: () => setActionMenu({ ...actionMenu, confirmDelete: true }),
            tone: "danger",
          },
        ];

  if (!chat || !connection) {
    return (
      <View style={styles.loading}>
        {loadError ? (
          <>
            <Text style={styles.loadError}>{loadError}</Text>
            <Pressable onPress={() => router.back()} style={styles.loadErrorButton}>
              <Text style={styles.loadErrorButtonText}>返回会话</Text>
            </Pressable>
          </>
        ) : <ActivityIndicator color={colors.accent} />}
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "left", "right"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.flex}>
        <View style={styles.shell}>
          <View style={styles.header}>
            <Pressable accessibilityLabel="返回" onPress={() => router.back()} style={styles.backButton}>
              <ChevronLeft size={26} color={colors.ink} strokeWidth={2.2} />
            </Pressable>
            <View style={styles.headerText}>
              <View style={styles.titleRow}>
                <AgentAvatar avatarUri={appearance.avatarUri} size={27} />
                <Text numberOfLines={1} style={styles.title}>{chat.name || "新会话"}</Text>
                {pinned ? <Pin color={colors.accent} fill={colors.accent} size={11} /> : null}
              </View>
              <Text style={styles.status}>{isStreaming ? `${appearance.name} 正在回复` : appearance.name}</Text>
            </View>
            <Pressable
              accessibilityLabel="会话操作"
              onPress={openActions}
              ref={actionRef}
              style={styles.headerAction}
            >
              <Ellipsis size={22} color={colors.ink} />
            </Pressable>
          </View>

          <FlatList
            contentContainerStyle={turns.length ? styles.messages : styles.emptyMessages}
            data={turns}
            keyExtractor={(item) => item.id}
            keyboardDismissMode="interactive"
            ref={listRef}
            renderItem={({ item }) => <MessageTurnView connection={connection} turn={item} />}
            ListEmptyComponent={
              <View style={styles.empty}>
                <AgentAvatar avatarUri={appearance.avatarUri} size={58} />
                <Text style={styles.emptyTitle}>今天想做什么？</Text>
                <Text style={styles.emptyCopy}>提问、发送图片或文件，或继续之前的工作。</Text>
              </View>
            }
          />

          <View style={styles.composerArea}>
            {chatApprovals.length ? (
              <View style={styles.approvalWrap}>
                {chatApprovals.length > 1 ? (
                  <Text style={styles.approvalCount}>
                    当前会话有 {chatApprovals.length} 项待审批
                  </Text>
                ) : null}
                <ApprovalCard
                  approval={chatApprovals[0]!}
                  compact
                  contextLabel={chatApprovals[0]?.session_id !== chatApprovals[0]?.root_session_id
                    ? `子 Agent · ${chatApprovals[0]?.agent_id}`
                    : undefined}
                  onApprove={(scope) => approveRequest(chatApprovals[0]!, scope)}
                  onDeny={() => denyRequest(chatApprovals[0]!)}
                />
              </View>
            ) : null}
            <SessionControlBar controls={controls} onOpen={openControls} />
            {attachments.length ? (
              <View style={styles.attachments}>
                {attachments.map((attachment) => (
                  <View key={attachment.id} style={styles.attachmentChip}>
                    <Text numberOfLines={1} style={styles.attachmentName}>{attachment.name}</Text>
                    <Pressable onPress={() => setAttachments((items) => items.filter((item) => item.id !== attachment.id))}>
                      <X size={15} color={colors.muted} />
                    </Pressable>
                  </View>
                ))}
              </View>
            ) : null}
            <View style={styles.composer}>
              <Pressable accessibilityLabel="添加附件" onPress={() => void pickAttachment()} style={styles.attachButton}>
                {uploading ? <ActivityIndicator size="small" color={colors.muted} /> : <FileUp size={20} color={colors.muted} />}
              </Pressable>
              <TextInput
                multiline
                onChangeText={setText}
                placeholder={`给 ${appearance.name} 发消息`}
                placeholderTextColor={colors.faint}
                style={styles.input}
                value={text}
              />
              {isStreaming ? (
                <Pressable accessibilityLabel="停止" onPress={() => void stop(chat.id)} style={styles.sendButton}>
                  <Square size={17} color={colors.white} fill={colors.white} />
                </Pressable>
              ) : (
                <Pressable
                  accessibilityLabel="发送"
                  disabled={!text.trim() && !attachments.length}
                  onPress={() => void submit()}
                  style={({ pressed }) => [styles.sendButton, pressed && styles.pressed, !text.trim() && !attachments.length && styles.disabled]}
                >
                  <Send size={18} color={colors.white} />
                </Pressable>
              )}
            </View>
          </View>
          <SessionControlSheet
            controls={controls}
            kind={controlsKind}
            onClose={() => setControlsOpen(false)}
            visible={controlsOpen}
          />
          <AnchoredActionMenu
            actions={actionMenuActions}
            anchor={actionMenu?.anchor ?? null}
            onClose={() => setActionMenu(null)}
            title={actionMenu?.confirmDelete
              ? "此操作无法撤销"
              : chat.name || "会话操作"}
          />
          <MobileToast message={toast} onHide={() => setToast(null)} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.canvas },
  flex: { flex: 1 },
  shell: { flex: 1, width: "100%", maxWidth: 840, alignSelf: "center" },
  loading: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.canvas },
  loadError: { color: colors.muted, fontSize: 14, textAlign: "center", paddingHorizontal: spacing.lg },
  loadErrorButton: { minHeight: 44, justifyContent: "center", marginTop: spacing.sm },
  loadErrorButtonText: { color: colors.accent, fontSize: 15, fontWeight: "600" },
  header: { minHeight: 58, flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.xs, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line },
  backButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  headerAction: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  headerText: { flex: 1, minWidth: 0, alignItems: "center" },
  titleRow: { maxWidth: "100%", flexDirection: "row", alignItems: "center", gap: 6 },
  title: { flexShrink: 1, color: colors.ink, fontSize: 16, fontWeight: "600", textAlign: "center" },
  status: { color: colors.muted, fontSize: 11, lineHeight: 15, marginTop: 1, textAlign: "center" },
  messages: { padding: spacing.md, gap: spacing.lg },
  emptyMessages: { flexGrow: 1, justifyContent: "center", padding: spacing.xl },
  empty: { alignItems: "center", gap: spacing.sm },
  emptyTitle: { marginTop: spacing.sm, color: colors.ink, fontSize: 26, fontWeight: "600", letterSpacing: -0.8, textAlign: "center" },
  emptyCopy: { color: colors.muted, fontSize: 14, textAlign: "center" },
  composerArea: { paddingHorizontal: spacing.md, paddingTop: spacing.sm, paddingBottom: Platform.OS === "ios" ? spacing.sm : spacing.md, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line, backgroundColor: colors.canvas },
  approvalWrap: { gap: spacing.xs, paddingBottom: spacing.sm },
  approvalCount: { color: colors.muted, fontSize: 10, fontWeight: "700", paddingHorizontal: 2 },
  composer: { minHeight: 58, maxHeight: 150, flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surfaceStrong, padding: 7 },
  input: { flex: 1, minHeight: 42, maxHeight: 130, color: colors.ink, fontSize: 16, lineHeight: 24, paddingHorizontal: 4, paddingTop: 9, paddingBottom: 9 },
  attachButton: { width: 42, height: 42, alignItems: "center", justifyContent: "center" },
  sendButton: { width: 42, height: 42, borderRadius: 14, backgroundColor: colors.accent, alignItems: "center", justifyContent: "center" },
  pressed: { opacity: 0.75 },
  disabled: { opacity: 0.3 },
  attachments: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, paddingBottom: spacing.sm },
  attachmentChip: { maxWidth: 220, height: 34, flexDirection: "row", alignItems: "center", gap: spacing.xs, borderRadius: radius.pill, backgroundColor: colors.accentSoft, paddingHorizontal: spacing.sm },
  attachmentName: { flexShrink: 1, color: colors.accentDark, fontSize: 12, fontWeight: "600" },
});
