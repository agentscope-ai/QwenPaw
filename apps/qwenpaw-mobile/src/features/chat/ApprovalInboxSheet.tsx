import { router } from "expo-router";
import { CheckCircle2, Inbox, X } from "lucide-react-native";
import { FlatList, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import type { ChatSpec, PendingApproval } from "../../api/types";
import { colors, spacing } from "../../theme/tokens";
import { ApprovalCard } from "./ApprovalCard";

export function ApprovalInboxSheet({
  approvals,
  chats,
  onApprove,
  onClose,
  onDeny,
  visible,
}: {
  approvals: PendingApproval[];
  chats: ChatSpec[];
  onApprove: (
    approval: PendingApproval,
    scope: "exact" | "similar",
  ) => Promise<void>;
  onClose: () => void;
  onDeny: (approval: PendingApproval) => Promise<void>;
  visible: boolean;
}) {
  return (
    <Modal
      animationType="slide"
      onRequestClose={onClose}
      presentationStyle="pageSheet"
      visible={visible}
    >
      <SafeAreaView edges={["top", "bottom"]} style={styles.root}>
        <View style={styles.header}>
          <View style={styles.headerIcon}>
            <Inbox color={colors.accentDark} size={18} />
          </View>
          <View style={styles.headerText}>
            <Text style={styles.title}>审批 Inbox</Text>
            <Text style={styles.subtitle}>
              {approvals.length ? `${approvals.length} 项正在等待你` : "当前没有待审批操作"}
            </Text>
          </View>
          <Pressable accessibilityLabel="关闭审批 Inbox" onPress={onClose} style={styles.close}>
            <X color={colors.ink} size={19} />
          </Pressable>
        </View>

        <FlatList
          contentContainerStyle={approvals.length ? styles.list : styles.emptyList}
          data={approvals}
          keyExtractor={(item) => item.request_id}
          renderItem={({ item }) => {
            const chat = findApprovalChat(chats, item);
            return (
              <View style={styles.item}>
                {chat ? (
                  <Pressable
                    onPress={() => {
                      onClose();
                      router.push({ pathname: "/chat/[id]", params: { id: chat.id } });
                    }}
                    style={styles.chatLink}
                  >
                    <Text numberOfLines={1} style={styles.chatName}>
                      {chat.name || "新会话"}
                    </Text>
                    <Text style={styles.chatAction}>打开会话</Text>
                  </Pressable>
                ) : null}
                <ApprovalCard
                  approval={item}
                  contextLabel={approvalContext(item)}
                  onApprove={(scope) => onApprove(item, scope)}
                  onDeny={() => onDeny(item)}
                />
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={styles.empty}>
              <View style={styles.emptyIcon}>
                <CheckCircle2 color={colors.accentDark} size={28} />
              </View>
              <Text style={styles.emptyTitle}>审批已清空</Text>
              <Text style={styles.emptyCopy}>需要确认的工具操作会立即出现在这里。</Text>
            </View>
          }
        />
      </SafeAreaView>
    </Modal>
  );
}

function findApprovalChat(
  chats: ChatSpec[],
  approval: PendingApproval,
): ChatSpec | undefined {
  return chats.find((chat) =>
    chat.session_id === approval.root_session_id ||
    chat.session_id === approval.session_id ||
    chat.id === approval.root_session_id);
}

function approvalContext(approval: PendingApproval): string {
  if (approval.session_id !== approval.root_session_id) {
    return `子 Agent · ${approval.agent_id || "未知 Agent"}`;
  }
  return approval.agent_id ? `Agent · ${approval.agent_id}` : "当前 QwenPaw";
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  header: {
    minHeight: 66,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
  },
  headerIcon: {
    width: 36,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: colors.accentSoft,
  },
  headerText: { flex: 1 },
  title: { color: colors.ink, fontSize: 17, fontWeight: "700" },
  subtitle: { marginTop: 2, color: colors.muted, fontSize: 11 },
  close: {
    width: 38,
    height: 38,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 19,
    backgroundColor: colors.searchBackground,
  },
  list: { gap: spacing.md, padding: spacing.md, paddingBottom: spacing.xxl },
  item: { gap: spacing.xs },
  chatLink: { flexDirection: "row", alignItems: "center", paddingHorizontal: 2 },
  chatName: { flex: 1, color: colors.ink, fontSize: 12, fontWeight: "700" },
  chatAction: { color: colors.accentDark, fontSize: 11, fontWeight: "600" },
  emptyList: { flexGrow: 1, justifyContent: "center" },
  empty: { alignItems: "center", gap: spacing.sm, padding: spacing.xl },
  emptyIcon: {
    width: 58,
    height: 58,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 20,
    backgroundColor: colors.accentSoft,
  },
  emptyTitle: { color: colors.ink, fontSize: 18, fontWeight: "700" },
  emptyCopy: { color: colors.muted, fontSize: 13, textAlign: "center" },
});
