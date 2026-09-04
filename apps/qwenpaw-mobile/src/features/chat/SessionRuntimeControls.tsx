import {
  Bot,
  Check,
  ChevronDown,
  CircleDot,
  LockKeyhole,
  Rocket,
  RotateCw,
  Search,
  Shield,
  Sparkles,
  Target,
  type LucideIcon,
} from "lucide-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  SectionList,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import type {
  ActiveModelInfo,
  ApprovalLevel,
  LoopModeInfo,
  LoopSessionState,
  ModelSlotOverride,
} from "../../api/types";
import { MobileBottomSheet } from "../../components/MobileBottomSheet";
import { colors, radius, spacing } from "../../theme/tokens";
import type { SelectableProvider } from "./sessionControlsModel";

export type SessionControlKind = "model" | "loop" | "approval";

interface ControlsValue {
  activeModel: ActiveModelInfo | null;
  effectiveApproval: ApprovalLevel;
  effectiveModel: ModelSlotOverride | null;
  loading: boolean;
  loopModes: LoopModeInfo[];
  loopStatus: { state: LoopSessionState; mode: LoopModeInfo | null };
  modelError: string | null;
  providers: SelectableProvider[];
  reload: () => Promise<void>;
  runningApproval: ApprovalLevel;
  savingModel: boolean;
  selectedLoopMode: LoopModeInfo;
  sessionApproval: ApprovalLevel | null;
  sessionModelOverride: ModelSlotOverride | null;
  setSelectedLoopId: (id: string) => void;
  updateApproval: (value: ApprovalLevel | null) => Promise<void>;
  updateModel: (value: ModelSlotOverride | null) => Promise<void>;
}

export function SessionControlBar({
  controls,
  onOpen,
}: {
  controls: ControlsValue;
  onOpen: (kind: SessionControlKind) => void;
}) {
  const loopRunning = controls.loopStatus.state !== "idle";
  const modelLabel = controls.effectiveModel?.model || "未配置";
  const loopLabel = loopRunning
    ? loopStateLabel(controls.loopStatus.state)
    : loopName(controls.selectedLoopMode);
  return (
    <View style={styles.runtimeBar}>
      <RuntimeButton
        accent={Boolean(controls.sessionModelOverride)}
        icon={Bot}
        label={modelLabel}
        loading={controls.loading}
        onPress={() => onOpen("model")}
        title="模型"
      />
      <View style={styles.runtimeDivider} />
      <RuntimeButton
        active={loopRunning}
        icon={loopRunning ? CircleDot : Target}
        label={loopLabel}
        onPress={() => onOpen("loop")}
        title="Loop"
      />
      <View style={styles.runtimeDivider} />
      <RuntimeButton
        accent={controls.sessionApproval !== null}
        icon={Shield}
        label={approvalLabel(controls.effectiveApproval)}
        onPress={() => onOpen("approval")}
        title="审批"
      />
    </View>
  );
}

export function SessionControlSheet({
  controls,
  kind,
  onClose,
  visible,
}: {
  controls: ControlsValue;
  kind: SessionControlKind;
  onClose: () => void;
  visible: boolean;
}) {
  const [query, setQuery] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const sections = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return controls.providers.map((provider) => ({
      title: provider.name,
      providerId: provider.id,
      data: provider.models.filter((model) =>
        !normalized || model.name.toLocaleLowerCase().includes(normalized) ||
        model.id.toLocaleLowerCase().includes(normalized)),
    })).filter((section) => section.data.length);
  }, [controls.providers, query]);
  const presentation = sheetPresentation(kind);

  const close = () => {
    setQuery("");
    setActionError(null);
    onClose();
  };

  const commit = async (action: () => Promise<void>) => {
    setActionError(null);
    try {
      await action();
      close();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "设置保存失败");
    }
  };

  return (
    <MobileBottomSheet
      expanded
      onClose={close}
      subtitle={presentation.subtitle}
      title={presentation.title}
      visible={visible}
    >
      <View style={styles.sheet}>
        {kind === "model" ? (
          <View style={styles.flex}>
            <View style={styles.insetGroupSingle}>
              <OptionRow
                detail={agentModelDescription(controls.activeModel)}
                icon={Bot}
                label="跟随 Agent"
                onPress={() => void commit(() => controls.updateModel(null))}
                selected={controls.sessionModelOverride === null}
              />
            </View>
            <View style={styles.search}>
              <Search color={colors.faint} size={16} />
              <TextInput
                clearButtonMode="while-editing"
                onChangeText={setQuery}
                placeholder="搜索已配置模型"
                placeholderTextColor={colors.faint}
                style={styles.searchInput}
                value={query}
              />
            </View>
            <SectionList
              contentContainerStyle={styles.modelList}
              sections={sections}
              keyExtractor={(item, index) => `${item.id}:${index}`}
              renderSectionHeader={({ section }) => (
                <Text style={styles.sectionTitle}>{section.title}</Text>
              )}
              renderItem={({ item, section }) => {
                const selected =
                  controls.sessionModelOverride?.provider_id === section.providerId &&
                  controls.sessionModelOverride.model === item.id;
                return (
                  <OptionRow
                    detail={[
                      item.supports_multimodal ? "多模态" : "",
                      item.is_free ? "免费" : "",
                    ].filter(Boolean).join(" · ")}
                    disabled={controls.savingModel}
                    icon={item.is_recommended ? Sparkles : Bot}
                    label={item.name || item.id}
                    onPress={() => void commit(() => controls.updateModel({
                      provider_id: section.providerId,
                      model: item.id,
                    }))}
                    selected={selected}
                  />
                );
              }}
              ListEmptyComponent={
                controls.modelError ? (
                  <EmptyState
                    action="重新加载"
                    onAction={() => void controls.reload()}
                    text="无法读取当前 QwenPaw 的模型列表。"
                  />
                ) : (
                  <EmptyState text="当前 QwenPaw 没有可用模型，请先配置 Provider。" />
                )
              }
              stickySectionHeadersEnabled={false}
            />
          </View>
        ) : null}

        {kind === "loop" ? (
          <ScrollView contentContainerStyle={styles.sheetScroll}>
            {controls.loopStatus.state !== "idle" && controls.loopStatus.mode ? (
              <View style={styles.runningState}>
                <ActivityIndicator color="#3478F6" size="small" />
                <View style={styles.runningCopy}>
                  <Text style={styles.runningTitle}>
                    {loopName(controls.loopStatus.mode)} 正在运行
                  </Text>
                  <Text style={styles.runningDetail}>
                    {loopStateLabel(controls.loopStatus.state)}；本轮完成后才能切换。
                  </Text>
                </View>
              </View>
            ) : (
              <View style={styles.insetGroup}>
                {controls.loopModes.map((mode) => (
                  <OptionRow
                    detail={loopDescription(mode)}
                    icon={loopIcon(mode)}
                    key={mode.id}
                    label={loopName(mode)}
                    onPress={() => {
                      controls.setSelectedLoopId(mode.id);
                      close();
                    }}
                    selected={controls.selectedLoopMode.id === mode.id}
                  />
                ))}
              </View>
            )}
          </ScrollView>
        ) : null}

        {kind === "approval" ? (
          <ScrollView contentContainerStyle={styles.sheetScroll}>
            <Text style={styles.sectionCaption}>
              只覆盖当前会话。需要确认的工具操作会同时进入审批 Inbox。
            </Text>
            <View style={styles.insetGroup}>
              <OptionRow
                detail={`Agent 默认：${approvalLabel(controls.runningApproval)}`}
                icon={Shield}
                label="跟随 Agent"
                onPress={() => void commit(() => controls.updateApproval(null))}
                selected={controls.sessionApproval === null}
              />
              {APPROVAL_OPTIONS.map((option) => (
                <OptionRow
                  detail={option.description}
                  icon={option.icon}
                  key={option.value}
                  label={option.label}
                  onPress={() => void commit(() => controls.updateApproval(option.value))}
                  selected={controls.sessionApproval === option.value}
                />
              ))}
            </View>
          </ScrollView>
        ) : null}

        {actionError ? <Text style={styles.actionError}>{actionError}</Text> : null}
      </View>
    </MobileBottomSheet>
  );
}

function RuntimeButton({
  accent = false,
  active = false,
  icon: Icon,
  label,
  loading = false,
  onPress,
  title,
}: {
  accent?: boolean;
  active?: boolean;
  icon: LucideIcon;
  label: string;
  loading?: boolean;
  onPress: () => void;
  title: string;
}) {
  const color = active ? "#3478F6" : accent ? colors.accentDark : colors.muted;
  return (
    <Pressable
      accessibilityLabel={`${title}：${label}`}
      onPress={onPress}
      style={({ pressed }) => [styles.runtimeButton, pressed && styles.pressed]}
    >
      {loading
        ? <ActivityIndicator color={color} size="small" />
        : <Icon color={color} size={14} strokeWidth={2} />}
      <Text numberOfLines={1} style={[styles.runtimeLabel, { color }]}>{label}</Text>
      <ChevronDown color={colors.faint} size={11} />
    </Pressable>
  );
}

function OptionRow({
  detail,
  disabled = false,
  icon: Icon,
  label,
  onPress,
  selected,
}: {
  detail?: string;
  disabled?: boolean;
  icon: LucideIcon;
  label: string;
  onPress: () => void;
  selected: boolean;
}) {
  return (
    <Pressable
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.option,
        disabled && styles.optionDisabled,
        pressed && styles.optionPressed,
      ]}
    >
      <View style={[styles.optionIcon, selected && styles.optionIconSelected]}>
        <Icon color={selected ? colors.accentDark : colors.muted} size={18} />
      </View>
      <View style={styles.optionText}>
        <Text numberOfLines={1} style={styles.optionLabel}>{label}</Text>
        {detail ? <Text style={styles.optionDetail}>{detail}</Text> : null}
      </View>
      {selected ? <Check color={colors.accent} size={19} strokeWidth={2.7} /> : null}
    </Pressable>
  );
}

function EmptyState({
  action,
  onAction,
  text,
}: {
  action?: string;
  onAction?: () => void;
  text: string;
}) {
  return (
    <View style={styles.emptyState}>
      <Text style={styles.empty}>{text}</Text>
      {action && onAction ? (
        <Pressable onPress={onAction} style={styles.retryButton}>
          <RotateCw color={colors.accentDark} size={15} />
          <Text style={styles.retryLabel}>{action}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const APPROVAL_OPTIONS: {
  value: ApprovalLevel;
  label: string;
  description: string;
  icon: LucideIcon;
}[] = [
  { value: "STRICT", label: "严格", description: "每次工具调用都需要确认。", icon: LockKeyhole },
  { value: "SMART", label: "智能", description: "低风险自动放行，中高风险需要确认。", icon: Sparkles },
  { value: "AUTO", label: "自动", description: "仅确认工具明确标记的敏感操作。", icon: Shield },
  { value: "OFF", label: "关闭", description: "所有工具自动执行，不再请求审批。", icon: CircleDot },
];

function sheetPresentation(kind: SessionControlKind) {
  if (kind === "model") {
    return { title: "本会话模型", subtitle: "只影响当前会话，不修改 Agent" };
  }
  if (kind === "loop") {
    return { title: "运行方式", subtitle: "选择下一轮如何推进任务" };
  }
  return { title: "审批等级", subtitle: "控制当前会话的工具授权" };
}

function agentModelDescription(active: ActiveModelInfo | null): string {
  const model = active?.active_llm?.model;
  return model ? `当前 Agent 默认：${model}` : "使用 Agent 的默认模型";
}

function approvalLabel(level: ApprovalLevel): string {
  return APPROVAL_OPTIONS.find((item) => item.value === level)?.label ?? level;
}

function loopName(mode: LoopModeInfo | null): string {
  if (!mode || mode.id === "default") return "单轮";
  if (mode.id === "goal") return "Goal";
  if (mode.id === "mission") return "Mission";
  return mode.name_i18n?.zh || mode.name_i18n?.["zh-CN"] || mode.name;
}

function loopDescription(mode: LoopModeInfo): string {
  if (mode.id === "default") return "生成一轮完整回复后停止。";
  if (mode.id === "goal") return "围绕目标持续推进，直到判断完成。";
  if (mode.id === "mission") return "自动拆解复杂任务并交由子 Agent 验证。";
  return mode.description_i18n?.zh || mode.description_i18n?.["zh-CN"] || mode.description;
}

function loopStateLabel(state: LoopSessionState): string {
  if (state === "starting") return "正在启动";
  if (state === "running") return "执行中";
  if (state === "awaiting_user") return "等待回复";
  return "单轮";
}

function loopIcon(mode: LoopModeInfo): LucideIcon {
  if (mode.id === "goal") return Target;
  if (mode.id === "mission") return Rocket;
  if (mode.source === "custom") return Sparkles;
  return CircleDot;
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  runtimeBar: { height: 36, flexDirection: "row", alignItems: "center", marginBottom: 6, paddingHorizontal: 4 },
  runtimeButton: { flex: 1, minWidth: 0, height: 34, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, paddingHorizontal: 6 },
  runtimeDivider: { width: StyleSheet.hairlineWidth, height: 16, backgroundColor: colors.line },
  runtimeLabel: { flexShrink: 1, fontSize: 11, fontWeight: "600" },
  sheet: { flex: 1, backgroundColor: colors.groupedBackground },
  search: { minHeight: 40, flexDirection: "row", alignItems: "center", gap: spacing.xs, marginHorizontal: spacing.md, marginTop: spacing.md, paddingHorizontal: spacing.sm, borderRadius: 12, backgroundColor: colors.searchBackground },
  searchInput: { flex: 1, color: colors.ink, fontSize: 14, paddingVertical: 8 },
  insetGroupSingle: { marginHorizontal: spacing.md, marginTop: spacing.md, overflow: "hidden", borderRadius: radius.md, backgroundColor: colors.surface },
  insetGroup: { overflow: "hidden", borderRadius: radius.md, backgroundColor: colors.surface },
  modelList: { paddingHorizontal: spacing.md, paddingBottom: spacing.xxl },
  sheetScroll: { padding: spacing.md, paddingBottom: spacing.xxl },
  sectionTitle: { paddingTop: spacing.lg, paddingBottom: 7, paddingHorizontal: 4, color: colors.muted, fontSize: 11, fontWeight: "700", letterSpacing: 0.4, textTransform: "uppercase", backgroundColor: colors.groupedBackground },
  sectionCaption: { marginHorizontal: 4, marginBottom: spacing.sm, color: colors.muted, fontSize: 12, lineHeight: 18 },
  option: { minHeight: 64, flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line, backgroundColor: colors.surface },
  optionPressed: { backgroundColor: colors.searchBackground },
  optionDisabled: { opacity: 0.5 },
  optionIcon: { width: 36, height: 36, alignItems: "center", justifyContent: "center", borderRadius: 11, backgroundColor: colors.groupedBackground },
  optionIconSelected: { backgroundColor: colors.accentSoft },
  optionText: { flex: 1, minWidth: 0, gap: 3 },
  optionLabel: { color: colors.ink, fontSize: 15, fontWeight: "600" },
  optionDetail: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  runningState: { minHeight: 84, flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderRadius: radius.md, backgroundColor: "#EEF5FF" },
  runningCopy: { flex: 1, gap: 4 },
  runningTitle: { color: colors.ink, fontSize: 15, fontWeight: "700" },
  runningDetail: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  actionError: { paddingHorizontal: spacing.md, paddingBottom: spacing.sm, color: colors.danger, fontSize: 12 },
  emptyState: { alignItems: "center", padding: spacing.xl, gap: spacing.sm },
  empty: { color: colors.muted, fontSize: 13, lineHeight: 20, textAlign: "center" },
  retryButton: { minHeight: 36, flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.md, borderRadius: 18, backgroundColor: colors.accentSoft },
  retryLabel: { color: colors.accentDark, fontSize: 13, fontWeight: "600" },
  pressed: { opacity: 0.55 },
});
