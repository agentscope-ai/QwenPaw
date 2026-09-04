import { router, useLocalSearchParams } from "expo-router";
import { ChevronLeft } from "lucide-react-native";
import { useMemo } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import type { Connection } from "../../api/types";
import { AcpSettings } from "../../features/workbench/AcpSettings";
import { AgentSettings } from "../../features/workbench/AgentSettings";
import { AutomationSettings } from "../../features/workbench/AutomationSettings";
import { CheckpointSettings } from "../../features/workbench/CheckpointSettings";
import { ChannelSettings } from "../../features/workbench/ChannelSettings";
import { DebugSettings } from "../../features/workbench/DebugSettings";
import { EnvironmentSettings } from "../../features/workbench/EnvironmentSettings";
import { ExtensionsSettings } from "../../features/workbench/ExtensionsSettings";
import { FilesSettings } from "../../features/workbench/FilesSettings";
import { McpSettings } from "../../features/workbench/McpSettings";
import { ModelsSettings } from "../../features/workbench/ModelsSettings";
import { OffloadSettings } from "../../features/workbench/OffloadSettings";
import { OperationsSettings } from "../../features/workbench/OperationsSettings";
import { ProjectGitSettings } from "../../features/workbench/ProjectGitSettings";
import { SecuritySettings } from "../../features/workbench/SecuritySettings";
import { SkillSettings } from "../../features/workbench/SkillSettings";
import { SkillPoolSettings } from "../../features/workbench/SkillPoolSettings";
import { SnapshotSettings } from "../../features/workbench/SnapshotSettings";
import { ToggleCollectionSettings } from "../../features/workbench/ToggleCollectionSettings";
import { VoiceSettings } from "../../features/workbench/VoiceSettings";
import { findWorkbenchModule } from "../../features/workbench/modules";
import type { WorkbenchModule } from "../../features/workbench/modules";
import { useAppStore } from "../../store/app";
import { colors, spacing } from "../../theme/tokens";

export default function ModuleScreen() {
  const { key } = useLocalSearchParams<{ key: string }>();
  const connection = useAppStore((state) => state.connection);
  const module = useMemo(() => findWorkbenchModule(key), [key]);

  if (!module || !connection) {
    return (
      <SafeAreaView style={styles.root}>
        <Text style={styles.missing}>无法打开这个设置。</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={["top"]} style={styles.root}>
      <View style={styles.header}>
        <Pressable
          accessibilityLabel="返回工作台"
          hitSlop={8}
          onPress={() => router.back()}
          style={styles.headerAction}
        >
          <ChevronLeft color={colors.ink} size={25} />
        </Pressable>
        <View style={styles.headerText}>
          <Text numberOfLines={1} style={styles.headerTitle}>{module.title}</Text>
          <Text numberOfLines={1} style={styles.headerSubtitle}>
            {connection.agentId} · {connection.source === "platform"
              ? "Platform 云端"
              : "本地 / 私人"}
          </Text>
        </View>
        <View style={styles.headerAction} />
      </View>
      <ScrollView contentContainerStyle={styles.content}>
        <ModuleContent
          connection={connection}
          module={module}
        />
      </ScrollView>
    </SafeAreaView>
  );
}

function ModuleContent({
  connection,
  module,
}: {
  connection: Connection;
  module: WorkbenchModule;
}) {
  if (module.key === "agent-config") return <AgentSettings connection={connection} />;
  if (module.key === "models") return <ModelsSettings connection={connection} />;
  if (module.key === "skills") return <SkillSettings connection={connection} />;
  if (module.key === "skill-pool") {
    return <SkillPoolSettings connection={connection} />;
  }
  if (module.key === "tools") {
    return <ToggleCollectionSettings connection={connection} kind={module.key} />;
  }
  if (module.key === "mcp-acp") return <McpSettings connection={connection} />;
  if (module.key === "acp") return <AcpSettings connection={connection} />;
  if (module.key === "security") return <SecuritySettings connection={connection} />;
  if (module.key === "automation") return <AutomationSettings connection={connection} />;
  if (module.key === "channels") return <ChannelSettings connection={connection} />;
  if (module.key === "environments") {
    return <EnvironmentSettings connection={connection} />;
  }
  if (module.key === "files") return <FilesSettings connection={connection} />;
  if (module.key === "projects-git") {
    return <ProjectGitSettings connection={connection} />;
  }
  if (module.key === "checkpoints") {
    return <CheckpointSettings connection={connection} />;
  }
  if (module.key === "extensions") {
    return <ExtensionsSettings connection={connection} />;
  }
  if (module.key === "operations") {
    return <OperationsSettings connection={connection} />;
  }
  if (module.key === "offload") return <OffloadSettings connection={connection} />;
  if (module.key === "voice") return <VoiceSettings connection={connection} />;
  if (module.key === "debug") return <DebugSettings connection={connection} />;
  return <SnapshotSettings connection={connection} module={module} />;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  header: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
    backgroundColor: colors.tabBar,
  },
  headerAction: {
    width: 48,
    height: 48,
    alignItems: "center",
    justifyContent: "center",
  },
  headerText: { flex: 1, alignItems: "center", gap: 2 },
  headerTitle: { color: colors.ink, fontSize: 17, fontWeight: "600" },
  headerSubtitle: { color: colors.muted, fontSize: 11 },
  content: {
    width: "100%",
    maxWidth: 760,
    alignSelf: "center",
    gap: spacing.lg,
    padding: spacing.md,
    paddingBottom: spacing.xxl,
  },
  missing: { color: colors.ink, fontSize: 16, padding: spacing.lg },
});
