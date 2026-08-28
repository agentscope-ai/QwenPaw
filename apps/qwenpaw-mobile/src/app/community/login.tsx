import { router, useLocalSearchParams } from "expo-router";
import { ChevronLeft, LogIn, ShieldCheck } from "lucide-react-native";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  loginAgentScopePlatform,
  loginAgentScopePlatformWithGitHub,
} from "../../api/platform";
import { PlatformAuthForm } from "../../features/platform/PlatformAuthForm";
import { colors, radius, spacing } from "../../theme/tokens";

export default function CommunityLoginScreen() {
  const { returnTo, view } = useLocalSearchParams<{
    returnTo?: string;
    view?: string;
  }>();

  const submit = async (account: string, password: string) => {
    await loginAgentScopePlatform(account, password);
    if (returnTo === "compose") router.replace("/community/compose");
    else router.back();
  };

  const submitGitHub = async () => {
    await loginAgentScopePlatformWithGitHub();
    if (returnTo === "compose") router.replace("/community/compose");
    else router.back();
  };

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.header}>
        <Pressable
          accessibilityLabel="返回"
          hitSlop={8}
          onPress={() => router.back()}
          style={styles.headerAction}
        >
          <ChevronLeft color={colors.ink} size={25} />
        </Pressable>
        <Text style={styles.headerTitle}>Platform 登录</Text>
        <View style={styles.headerAction} />
      </View>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.brandIcon}>
            <LogIn color={colors.white} size={27} />
          </View>
          <Text style={styles.title}>连接 AgentScope 社区</Text>
          <Text style={styles.copy}>
            登录后可在 App 内同步点赞、评论和发布。社区登录状态与 QwenPaw 配对彼此独立。
          </Text>
          <View style={styles.form}>
            <PlatformAuthForm
              initialMode={view === "register" ? "register" : "login"}
              loginLabel="登录社区"
              onGitHubLogin={submitGitHub}
              onPasswordLogin={submit}
            />
          </View>
          <View style={styles.securityNote}>
            <ShieldCheck color={colors.accentDark} size={17} />
            <Text style={styles.securityCopy}>
              登录令牌仅保存在本机钥匙串中，过期后使用 Platform 刷新令牌续期。
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.canvas },
  flex: { flex: 1 },
  header: { height: 52, flexDirection: "row", alignItems: "center" },
  headerAction: { width: 52, height: 52, alignItems: "center", justifyContent: "center" },
  headerTitle: { flex: 1, color: colors.ink, fontSize: 17, fontWeight: "600", textAlign: "center" },
  content: {
    width: "100%",
    maxWidth: 520,
    alignSelf: "center",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
    paddingBottom: spacing.xl,
  },
  brandIcon: {
    width: 58,
    height: 58,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 18,
    backgroundColor: colors.accent,
  },
  title: { marginTop: spacing.lg, color: colors.ink, fontSize: 27, fontWeight: "700", letterSpacing: -0.7 },
  copy: { marginTop: spacing.sm, color: colors.muted, fontSize: 14, lineHeight: 22 },
  form: { gap: spacing.md, marginTop: spacing.xl },
  securityNote: {
    flexDirection: "row",
    gap: 9,
    marginTop: spacing.lg,
    padding: 13,
    borderRadius: radius.md,
    backgroundColor: colors.accentSoft,
  },
  securityCopy: { flex: 1, color: colors.muted, fontSize: 11, lineHeight: 17 },
});
