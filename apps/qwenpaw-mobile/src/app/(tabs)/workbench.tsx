import { router } from "expo-router";
import {
  Bot,
  CalendarClock,
  ChartNoAxesCombined,
  ChevronRight,
  FolderOpen,
  Inbox,
  MessageSquarePlus,
  Search,
  ShieldCheck,
  UserRound,
  Waypoints,
  type LucideIcon,
} from "lucide-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { IosHeader } from "../../components/IosHeader";
import { IosGroup, IosRow } from "../../components/IosList";
import { MobileToast } from "../../components/MobileToast";
import {
  workbenchCategories,
  type WorkbenchModule,
  type WorkbenchSection,
} from "../../features/workbench/modules";
import {
  WorkspaceSwitcher,
  workspaceName,
} from "../../features/workspaces/WorkspaceSwitcher";
import { mobileText } from "../../i18n/locale";
import { resolveAgentAppearance } from "../../storage/agentAppearance";
import { useAppStore } from "../../store/app";
import { qwenPawBrandAssets } from "../../theme/brandAssets";
import { colors, radius, spacing } from "../../theme/tokens";

const accountSearchText = [
  "账户",
  "设备",
  "配对",
  "连接",
  "Platform",
  "外观",
  "主题",
  "关于",
].join(" ").toLocaleLowerCase();

const categoryPresentation: Record<string, {
  description: string;
  icon: LucideIcon;
  title: string;
}> = {
  "Agent 与工作空间": {
    description: mobileText("Agent、会话、文件与项目", "Agents, chats, files, and projects"),
    icon: Bot,
    title: mobileText("Agent 与工作空间", "Agents & Workspace"),
  },
  "连接与自动化": {
    description: mobileText("模型、渠道、工具与计划任务", "Models, channels, tools, and schedules"),
    icon: Waypoints,
    title: mobileText("连接与自动化", "Connections & Automation"),
  },
  "运行与安全": {
    description: mobileText("技能、权限、运行与扩展", "Skills, permissions, runtime, and extensions"),
    icon: ShieldCheck,
    title: mobileText("运行与安全", "Runtime & Security"),
  },
  "数据与诊断": {
    description: mobileText("版本、日志、用量与恢复", "Versions, logs, usage, and recovery"),
    icon: ChartNoAxesCombined,
    title: mobileText("数据与诊断", "Data & Diagnostics"),
  },
};

export default function WorkbenchScreen() {
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<WorkbenchSection | null>(
    null,
  );
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const connection = useAppStore((state) => state.connection);
  const status = useAppStore((state) => state.status);
  const agents = useAppStore((state) => state.agents);
  const appearances = useAppStore((state) => state.agentAppearances);
  const createChat = useAppStore((state) => state.createChat);
  const agent = agents.find((item) => item.id === connection?.agentId);
  const appearance = resolveAgentAppearance(appearances, connection, agent);
  const searchResults = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return [];
    return workbenchCategories.flatMap((section) => section.modules.filter(
      (module) => [
        module.title,
        module.subtitle,
        ...module.scope,
        ...(module.keywords ?? []),
      ].join(" ").toLocaleLowerCase().includes(normalized),
    ));
  }, [query]);
  const accountMatches = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return Boolean(normalized && accountSearchText.includes(normalized));
  }, [query]);

  const openModule = (key: string) => {
    if (key === "sessions") {
      router.push("/chats");
      return;
    }
    router.push({ pathname: "/module/[key]", params: { key } });
  };

  const create = async () => {
    setCreating(true);
    try {
      const chat = await createChat();
      router.push({ pathname: "/chat/[id]", params: { id: chat.id } });
    } catch (error) {
      setToast(error instanceof Error ? error.message : "暂时无法新建会话");
    } finally {
      setCreating(false);
    }
  };

  const back = () => {
    if (activeCategory) {
      setActiveCategory(null);
      return;
    }
    router.back();
  };

  return (
    <SafeAreaView edges={["top"]} style={styles.root}>
      <IosHeader
        title={activeCategory
          ? categoryPresentation[activeCategory.title]?.title ?? activeCategory.title
          : mobileText("工作台", "Workbench")}
        onBack={activeCategory ? back : undefined}
      />
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
      >
        {activeCategory ? (
          <CategoryDetail category={activeCategory} onOpen={openModule} />
        ) : (
          <>
            <Pressable
              accessibilityLabel="切换当前 QwenPaw"
              accessibilityRole="button"
              onPress={() => setSwitcherOpen(true)}
              style={({ pressed }) => [
                styles.contextCard,
                pressed && styles.pressed,
              ]}
            >
              <View style={styles.brandMark}>
                <Image
                  accessible={false}
                  resizeMode="contain"
                  source={qwenPawBrandAssets.wave}
                  style={styles.brandImage}
                />
              </View>
              <View style={styles.contextBody}>
                <Text maxFontSizeMultiplier={1.3} style={styles.contextEyebrow}>
                  {mobileText("当前 QwenPaw", "Current QwenPaw")}
                </Text>
                <Text maxFontSizeMultiplier={1.35} numberOfLines={1} style={styles.contextTitle}>
                  {connection
                    ? workspaceName(connection)
                    : mobileText("尚未连接", "Not connected")}
                </Text>
                <Text maxFontSizeMultiplier={1.25} numberOfLines={1} style={styles.contextSubtitle}>
                  {status === "ready"
                    ? mobileText("运行正常", "Ready")
                    : mobileText("正在连接", "Connecting")}
                  {connection
                    ? mobileText(
                        ` · 当前 Agent：${appearance.name}`,
                        ` · Active Agent: ${appearance.name}`,
                      )
                    : ""}
                </Text>
              </View>
              <ChevronRight color={colors.faint} size={19} />
            </Pressable>

            <View style={styles.search}>
              <Search color={colors.muted} size={18} />
              <TextInput
                clearButtonMode="while-editing"
                maxFontSizeMultiplier={1.35}
                onChangeText={setQuery}
                placeholder={mobileText(
                  "搜索全部功能与设置",
                  "Search features and settings",
                )}
                placeholderTextColor={colors.faint}
                returnKeyType="search"
                style={styles.searchInput}
                value={query}
              />
            </View>

            {query.trim() ? (
              <SearchResults
                modules={searchResults}
                onOpen={openModule}
                showAccount={accountMatches}
              />
            ) : (
              <>
                <View style={styles.sectionHeading}>
                  <Text maxFontSizeMultiplier={1.35} style={styles.sectionTitle}>
                    {mobileText("快捷操作", "Quick Actions")}
                  </Text>
                </View>
                <View style={styles.quickGrid}>
                  <QuickAction
                    icon={MessageSquarePlus}
                    label={mobileText("新建会话", "New Chat")}
                    loading={creating}
                    onPress={() => void create()}
                  />
                  <QuickAction
                    icon={Inbox}
                    label={mobileText("审批", "Approvals")}
                    onPress={() => router.push("/chats")}
                  />
                  <QuickAction
                    icon={CalendarClock}
                    label={mobileText("定时任务", "Schedules")}
                    onPress={() => openModule("automation")}
                  />
                  <QuickAction
                    icon={FolderOpen}
                    label={mobileText("文件", "Files")}
                    onPress={() => openModule("files")}
                  />
                </View>

                <View style={styles.sectionHeading}>
                  <Text maxFontSizeMultiplier={1.35} style={styles.sectionTitle}>
                    {mobileText("全部功能", "All Features")}
                  </Text>
                  <Text maxFontSizeMultiplier={1.3} style={styles.sectionMeta}>
                    {mobileText("按任务分类", "Grouped by task")}
                  </Text>
                </View>
                <View style={styles.categoryGroup}>
                  {workbenchCategories.map((category, index) => (
                    <CategoryRow
                      category={category}
                      divider={index > 0}
                      key={category.title}
                      onPress={() => setActiveCategory(category)}
                    />
                  ))}
                  <AccountCategoryRow
                    onPress={() => router.push("/me")}
                  />
                </View>
              </>
            )}
          </>
        )}
      </ScrollView>
      <WorkspaceSwitcher
        onClose={() => setSwitcherOpen(false)}
        visible={switcherOpen}
      />
      <MobileToast message={toast} onHide={() => setToast(null)} />
    </SafeAreaView>
  );
}

function AccountCategoryRow({ onPress }: { onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [
        styles.categoryRow,
        styles.categoryDivider,
        pressed && styles.rowPressed,
      ]}
    >
      <View style={styles.categoryIcon}>
        <UserRound color={colors.accentDark} size={19} strokeWidth={1.9} />
      </View>
      <View style={styles.categoryBody}>
        <Text maxFontSizeMultiplier={1.35} style={styles.categoryTitle}>
          {mobileText("账户与设备", "Account & Devices")}
        </Text>
        <Text maxFontSizeMultiplier={1.25} numberOfLines={1} style={styles.categorySubtitle}>
          {mobileText(
            "配对、Platform、外观与关于",
            "Pairing, Platform, appearance, and about",
          )}
        </Text>
      </View>
      <ChevronRight color={colors.faint} size={18} />
    </Pressable>
  );
}

function QuickAction({
  icon: Icon,
  label,
  loading = false,
  onPress,
}: {
  icon: LucideIcon;
  label: string;
  loading?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      disabled={loading}
      onPress={onPress}
      style={({ pressed }) => [styles.quickAction, pressed && styles.pressed]}
    >
      <View style={styles.quickIcon}>
        {loading ? (
          <ActivityIndicator color={colors.accentDark} size="small" />
        ) : (
          <Icon color={colors.accentDark} size={20} strokeWidth={1.9} />
        )}
      </View>
      <Text maxFontSizeMultiplier={1.25} numberOfLines={1} style={styles.quickLabel}>
        {label}
      </Text>
    </Pressable>
  );
}

function CategoryRow({
  category,
  divider,
  onPress,
}: {
  category: WorkbenchSection;
  divider: boolean;
  onPress: () => void;
}) {
  const presentation = categoryPresentation[category.title]!;
  const Icon = presentation.icon;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [
        styles.categoryRow,
        divider && styles.categoryDivider,
        pressed && styles.rowPressed,
      ]}
    >
      <View style={styles.categoryIcon}>
        <Icon color={colors.accentDark} size={19} strokeWidth={1.9} />
      </View>
      <View style={styles.categoryBody}>
        <Text maxFontSizeMultiplier={1.35} style={styles.categoryTitle}>
          {presentation.title}
        </Text>
        <Text maxFontSizeMultiplier={1.25} numberOfLines={1} style={styles.categorySubtitle}>
          {presentation.description}
        </Text>
      </View>
      <Text maxFontSizeMultiplier={1.25} style={styles.categoryCount}>
        {mobileText(
          `${category.modules.length} 项`,
          `${category.modules.length} items`,
        )}
      </Text>
      <ChevronRight color={colors.faint} size={18} />
    </Pressable>
  );
}

function CategoryDetail({
  category,
  onOpen,
}: {
  category: WorkbenchSection;
  onOpen: (key: string) => void;
}) {
  const presentation = categoryPresentation[category.title]!;
  return (
    <>
      <Text maxFontSizeMultiplier={1.5} style={styles.detailCopy}>
        {presentation.description}
      </Text>
      <IosGroup>
        {category.modules.map((module) => (
          <IosRow
            icon={module.icon}
            key={module.key}
            label={module.title}
            onPress={() => onOpen(module.key)}
            subtitle={module.subtitle}
          />
        ))}
      </IosGroup>
    </>
  );
}

function SearchResults({
  modules,
  onOpen,
  showAccount,
}: {
  modules: WorkbenchModule[];
  onOpen: (key: string) => void;
  showAccount: boolean;
}) {
  if (!modules.length && !showAccount) {
    return (
      <View style={styles.empty}>
        <Image
          accessible={false}
          resizeMode="contain"
          source={qwenPawBrandAssets.paw}
          style={styles.emptyPaw}
        />
        <Text maxFontSizeMultiplier={1.4} style={styles.emptyTitle}>
          没有找到相关功能
        </Text>
        <Text maxFontSizeMultiplier={1.4} style={styles.emptyCopy}>
          换一个关键词试试。
        </Text>
      </View>
    );
  }
  return (
    <>
      <Text maxFontSizeMultiplier={1.35} style={styles.resultCount}>
        找到 {modules.length + (showAccount ? 1 : 0)} 项功能
      </Text>
      <IosGroup>
        {modules.map((module) => (
          <IosRow
            icon={module.icon}
            key={module.key}
            label={module.title}
            onPress={() => onOpen(module.key)}
            subtitle={module.subtitle}
            trailing="移动端"
          />
        ))}
        {showAccount ? (
          <IosRow
            icon={UserRound}
            label="账户与设备"
            onPress={() => router.push("/me")}
            subtitle="配对、Platform、外观与关于"
            trailing="移动端"
          />
        ) : null}
      </IosGroup>
    </>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  content: {
    width: "100%",
    maxWidth: 720,
    alignSelf: "center",
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xxl,
  },
  contextCard: {
    minHeight: 86,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.accentSoft,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  brandMark: {
    width: 52,
    height: 52,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 17,
    backgroundColor: colors.accentSoft,
  },
  brandImage: { width: 50, height: 50 },
  contextBody: { flex: 1, minWidth: 0 },
  contextEyebrow: {
    color: colors.accentDark,
    fontSize: 12,
    fontWeight: "700",
    marginBottom: 2,
  },
  contextTitle: { color: colors.ink, fontSize: 16, fontWeight: "600" },
  contextSubtitle: { color: colors.muted, fontSize: 12, marginTop: 4 },
  search: {
    height: 46,
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    marginTop: 14,
    paddingHorizontal: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: 15,
    backgroundColor: colors.surface,
  },
  searchInput: { flex: 1, color: colors.ink, fontSize: 16, paddingVertical: 0 },
  sectionHeading: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    paddingHorizontal: 4,
    paddingBottom: 9,
  },
  sectionTitle: { color: colors.ink, fontSize: 15, fontWeight: "700" },
  sectionMeta: { color: colors.muted, fontSize: 13 },
  quickGrid: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: spacing.xs,
  },
  quickAction: {
    flex: 1,
    minHeight: 78,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderRadius: radius.md,
  },
  quickIcon: {
    width: 42,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: 14,
    backgroundColor: colors.surface,
  },
  quickLabel: { color: colors.ink, fontSize: 12, fontWeight: "600" },
  categoryGroup: {
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  categoryRow: {
    minHeight: 68,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: 14,
  },
  categoryDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  categoryIcon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 11,
    backgroundColor: colors.accentSoft,
  },
  categoryBody: { flex: 1, minWidth: 0 },
  categoryTitle: { color: colors.ink, fontSize: 16, fontWeight: "600" },
  categorySubtitle: { color: colors.muted, fontSize: 12, marginTop: 3 },
  categoryCount: { color: colors.muted, fontSize: 12 },
  detailCopy: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: spacing.md,
    paddingHorizontal: 4,
  },
  resultCount: {
    color: colors.muted,
    fontSize: 13,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
    paddingHorizontal: 4,
  },
  empty: { alignItems: "center", gap: 6, paddingVertical: spacing.xxl },
  emptyPaw: { width: 52, height: 50, marginBottom: spacing.xs },
  emptyTitle: { color: colors.ink, fontSize: 16, fontWeight: "600" },
  emptyCopy: { color: colors.muted, fontSize: 13 },
  pressed: { opacity: 0.64 },
  rowPressed: { backgroundColor: colors.pressed },
});
