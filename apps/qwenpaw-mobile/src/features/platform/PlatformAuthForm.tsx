import { GitBranch, LogIn, MailCheck, UserPlus } from "lucide-react-native";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  isPlatformOAuthCancelledError,
  registerAgentScopePlatform,
  sendPlatformVerificationCode,
} from "../../api/platform";
import { Field } from "../../components/Field";
import { PrimaryButton } from "../../components/PrimaryButton";
import { colors, radius, spacing } from "../../theme/tokens";
import { isValidPlatformEmail, platformRegistrationError } from "./authModel";

type AuthMode = "login" | "register";

export function PlatformAuthForm({
  children,
  initialMode = "login",
  loginLabel = "登录 Platform",
  onGitHubLogin,
  onPasswordLogin,
}: {
  children?: ReactNode;
  initialMode?: AuthMode;
  loginLabel?: string;
  onGitHubLogin: () => Promise<void>;
  onPasswordLogin: (account: string, password: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verifyCode, setVerifyCode] = useState("");
  const [countdown, setCountdown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [codeBusy, setCodeBusy] = useState(false);
  const [oauthBusy, setOauthBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setInterval(() => {
      setCountdown((current) => Math.max(0, current - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [countdown]);

  const switchMode = (next: AuthMode) => {
    setMode(next);
    setError(null);
  };

  const sendCode = async () => {
    if (!isValidPlatformEmail(account)) {
      setError("请输入有效的邮箱地址");
      return;
    }
    setCodeBusy(true);
    setError(null);
    try {
      await sendPlatformVerificationCode(account.trim());
      setCountdown(60);
    } catch (caught) {
      setError(errorMessage(caught, "验证码发送失败，请稍后重试"));
    } finally {
      setCodeBusy(false);
    }
  };

  const submit = async () => {
    if (mode === "register") {
      const validation = platformRegistrationError({
        account,
        confirmPassword,
        password,
        verifyCode,
      });
      if (validation) {
        setError(validation);
        return;
      }
    } else if (!account.trim() || !password) {
      setError("请输入账号和密码");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await registerAgentScopePlatform(
          account.trim(),
          password,
          verifyCode.trim(),
        );
      }
      await onPasswordLogin(account.trim(), password);
    } catch (caught) {
      setError(
        errorMessage(
          caught,
          mode === "register" ? "注册失败，请稍后重试" : "Platform 登录失败",
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  const openGitHub = async () => {
    setOauthBusy(true);
    setError(null);
    try {
      await onGitHubLogin();
    } catch (caught) {
      if (isPlatformOAuthCancelledError(caught)) return;
      setError(errorMessage(caught, "GitHub 登录失败，请重试"));
    } finally {
      setOauthBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <View style={styles.segment}>
        <Segment
          active={mode === "login"}
          label="登录"
          onPress={() => switchMode("login")}
        />
        <Segment
          active={mode === "register"}
          label="注册"
          onPress={() => switchMode("register")}
        />
      </View>
      <Field
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        label={mode === "register" ? "邮箱" : "AgentScope 账号"}
        onChangeText={setAccount}
        placeholder={mode === "register" ? "用于接收验证码" : "邮箱或账号"}
        value={account}
      />
      {mode === "register" ? (
        <View style={styles.codeRow}>
          <View style={styles.codeField}>
            <Field
              keyboardType="number-pad"
              label="验证码"
              onChangeText={setVerifyCode}
              placeholder="邮箱验证码"
              value={verifyCode}
            />
          </View>
          <Pressable
            disabled={codeBusy || countdown > 0}
            onPress={() => void sendCode()}
            style={({ pressed }) => [
              styles.codeButton,
              (codeBusy || countdown > 0) && styles.disabled,
              pressed && styles.pressed,
            ]}
          >
            <MailCheck color={colors.accentDark} size={17} />
            <Text style={styles.codeButtonText}>
              {countdown > 0 ? `${countdown}s` : "发送验证码"}
            </Text>
          </Pressable>
        </View>
      ) : null}
      <Field
        autoComplete={mode === "login" ? "current-password" : "new-password"}
        label="密码"
        onChangeText={setPassword}
        placeholder={
          mode === "register" ? "至少 8 位，首位为字母" : "Platform 密码"
        }
        secureTextEntry
        value={password}
      />
      {mode === "register" ? (
        <Field
          autoComplete="new-password"
          label="确认密码"
          onChangeText={setConfirmPassword}
          placeholder="再次输入密码"
          secureTextEntry
          value={confirmPassword}
        />
      ) : null}
      {children}
      <PrimaryButton
        disabled={!account.trim() || !password}
        icon={mode === "register" ? UserPlus : LogIn}
        label={mode === "register" ? "注册并继续" : loginLabel}
        loading={busy}
        onPress={() => void submit()}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.divider}>
        <View style={styles.dividerLine} />
        <Text style={styles.dividerText}>或</Text>
        <View style={styles.dividerLine} />
      </View>
      <Pressable
        accessibilityRole="button"
        disabled={oauthBusy || busy}
        onPress={() => void openGitHub()}
        style={({ pressed }) => [
          styles.githubButton,
          (oauthBusy || busy) && styles.disabled,
          pressed && styles.pressed,
        ]}
      >
        {oauthBusy ? (
          <ActivityIndicator color={colors.ink} size="small" />
        ) : (
          <GitBranch color={colors.ink} size={20} />
        )}
        <Text style={styles.githubText}>
          {oauthBusy ? "正在完成授权…" : "使用 GitHub 登录"}
        </Text>
      </Pressable>
      <Text style={styles.oauthHint}>
        {Platform.OS === "android"
          ? "将在 App 内完成安全授权，成功后自动继续。"
          : "将在系统安全认证页完成授权，成功后自动返回 QwenPaw。"}
      </Text>
    </View>
  );
}

function Segment({
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
      onPress={onPress}
      style={[styles.segmentItem, active && styles.segmentItemActive]}
    >
      <Text style={[styles.segmentText, active && styles.segmentTextActive]}>
        {label}
      </Text>
    </Pressable>
  );
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

const styles = StyleSheet.create({
  root: { gap: spacing.md },
  segment: {
    flexDirection: "row",
    gap: 3,
    padding: 3,
    borderRadius: radius.md,
    backgroundColor: colors.groupedBackground,
  },
  segmentItem: {
    flex: 1,
    minHeight: 38,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.sm,
  },
  segmentItemActive: { backgroundColor: colors.surfaceStrong },
  segmentText: { color: colors.muted, fontSize: 13, fontWeight: "600" },
  segmentTextActive: { color: colors.ink },
  codeRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm },
  codeField: { flex: 1 },
  codeButton: {
    minWidth: 118,
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.accentSoft,
  },
  codeButtonText: { color: colors.accentDark, fontSize: 12, fontWeight: "700" },
  divider: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dividerLine: {
    flex: 1,
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.hairline,
  },
  dividerText: { color: colors.faint, fontSize: 11 },
  githubButton: {
    minHeight: 50,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 9,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceStrong,
  },
  githubText: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  oauthHint: {
    color: colors.faint,
    fontSize: 10,
    lineHeight: 16,
    textAlign: "center",
  },
  error: { color: colors.danger, fontSize: 13, lineHeight: 19 },
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.7 },
});
