import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import {
  ArrowLeft,
  ArrowRight,
  Bug,
  ChevronRight,
  Cloud,
  Link2,
  QrCode,
  RefreshCw,
  Server,
  Trash2,
  WifiOff,
} from "lucide-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  BackHandler,
  Image,
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
  loginQwenPaw,
} from "../api/client";
import {
  getPlatformAccessToken,
  loginAgentScopePlatform,
  loginAgentScopePlatformWithGitHub,
} from "../api/platform";
import { isPlatformRateLimitError } from "../api/platformError";
import {
  buildDebugBaseUrl,
  DEFAULT_DEBUG_HOST,
  DEFAULT_DEBUG_PORT,
} from "../api/debug";
import {
  connectionTimeoutMessage,
  type ConnectionAttempt,
  startConnectionAttempt,
} from "../api/connectionAttempt";
import { normalizeBaseUrl } from "../api/pairing";
import type { Connection } from "../api/types";
import { Field } from "../components/Field";
import { IosGroup, IosRow } from "../components/IosList";
import { MobileAlert } from "../components/MobileAlert";
import { PrimaryButton } from "../components/PrimaryButton";
import { PlatformAuthForm } from "../features/platform/PlatformAuthForm";
import { workspaceName } from "../features/workspaces/WorkspaceSwitcher";
import { useAppStore } from "../store/app";
import { connectionKey } from "../storage/connection";
import { qwenPawBrandAssets } from "../theme/brandAssets";
import { colors, radius, spacing } from "../theme/tokens";

type Mode = "choice" | "self" | "direct" | "platform" | "debug";

export default function ConnectScreen() {
  const { add, platformLogin } = useLocalSearchParams<{
    add?: string;
    platformLogin?: string;
  }>();
  const adding = add === "1";
  const status = useAppStore((state) => state.status);
  const connection = useAppStore((state) => state.connection);
  const connect = useAppStore((state) => state.connect);
  const [mode, setMode] = useState<Mode>(
    platformLogin === "1" ? "platform" : "choice",
  );
  const [baseUrl, setBaseUrl] = useState("");
  const [debugHost, setDebugHost] = useState(DEFAULT_DEBUG_HOST);
  const [debugPort, setDebugPort] = useState(String(DEFAULT_DEBUG_PORT));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [platformChecking, setPlatformChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [choosingAnother, setChoosingAnother] = useState(false);
  const directAttempt = useRef<ConnectionAttempt | null>(null);

  const goBack = useCallback(() => {
    directAttempt.current?.cancel();
    setError(null);
    setMode((currentMode) => (
      currentMode === "direct" || currentMode === "debug"
        ? "self"
        : "choice"
    ));
  }, []);

  useEffect(() => () => {
    directAttempt.current?.cancel();
    directAttempt.current?.dispose();
  }, []);

  useFocusEffect(useCallback(() => {
    if (Platform.OS !== "android") return undefined;
    const subscription = BackHandler.addEventListener(
      "hardwareBackPress",
      () => {
        if (mode === "choice") return false;
        goBack();
        return true;
      },
    );
    return () => subscription.remove();
  }, [goBack, mode]));

  useEffect(() => {
    if (status === "ready" && !adding) router.replace("/chats");
  }, [adding, status]);

  if (status === "booting") {
    return <View style={styles.loading}><ActivityIndicator color={colors.accent} /></View>;
  }

  if (!adding && !choosingAnother && connection && status !== "ready") {
    return (
      <DisconnectedHome
        connection={connection}
        onChooseAnother={() => {
          setError(null);
          setChoosingAnother(true);
        }}
      />
    );
  }

  const connectResolved = async (
    rawUrl: string,
    account: string,
    secret: string,
    source: Connection["source"],
    signal?: AbortSignal,
  ) => {
    const url = normalizeBaseUrl(rawUrl);
    const nextConnection = await loginQwenPaw(
      url,
      account,
      secret,
      source,
      undefined,
      signal,
    );
    await connect(nextConnection, signal);
    router.replace("/chats");
  };

  const submitDirect = async (resolvedUrl?: string) => {
    const rawUrl = resolvedUrl ?? baseUrl;
    const attempt = startConnectionAttempt();
    directAttempt.current?.cancel();
    directAttempt.current?.dispose();
    directAttempt.current = attempt;
    setBusy(true);
    setError(null);
    try {
      await connectResolved(
        rawUrl,
        username,
        password,
        "private",
        attempt.signal,
      );
    } catch (caught) {
      if (attempt.didTimeout()) {
        setError(connectionTimeoutMessage(rawUrl));
      } else if (attempt.signal.aborted) {
        setError("已取消连接，你可以修改地址后重试。");
      } else {
        setError(errorMessage(caught, "连接失败，请检查服务器地址。"));
      }
    } finally {
      attempt.dispose();
      if (directAttempt.current === attempt) directAttempt.current = null;
      setBusy(false);
    }
  };

  const cancelDirect = () => directAttempt.current?.cancel();

  const submitPlatform = async (account: string, platformPassword: string) => {
    await loginAgentScopePlatform(account, platformPassword);
    openPlatformDeploy();
  };

  const submitPlatformGitHub = async () => {
    await loginAgentScopePlatformWithGitHub();
    openPlatformDeploy();
  };

  const choosePlatform = async () => {
    setPlatformChecking(true);
    setError(null);
    try {
      if (await getPlatformAccessToken()) {
        openPlatformDeploy();
      } else {
        setMode("platform");
      }
    } catch (caught) {
      setError(isPlatformRateLimitError(caught)
        ? "Platform 请求较多，登录态仍已保留，请稍后再试。"
        : errorMessage(caught, "暂时无法连接 Platform，请稍后再试。"));
    } finally {
      setPlatformChecking(false);
    }
  };

  const openPlatformDeploy = () => {
    router.replace({
      pathname: "/platform/deploy",
      params: { add: adding ? "1" : "0" },
    });
  };

  return (
    <SafeAreaView style={styles.root}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.flex}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <BrandHeader adding={adding} mode={mode} onBack={goBack} />
          {mode === "choice" ? (
            <ChoicePanel
              adding={adding}
              onMode={setMode}
              onPlatform={() => void choosePlatform()}
              platformChecking={platformChecking}
            />
          ) : null}
          {mode === "choice" && error ? (
            <Text style={styles.choiceError}>{error}</Text>
          ) : null}
          {mode === "self" ? <SelfPanel onMode={setMode} /> : null}
          {mode === "direct" || mode === "platform" || mode === "debug" ? (
            <View style={styles.formCard}>
              <View style={styles.formHeading}>
                <Text style={styles.formTitle}>{modeTitle(mode)}</Text>
                <Text style={styles.formCopy}>{modeCopy(mode)}</Text>
              </View>
              {mode === "direct" ? (
                <>
                  <Field autoCapitalize="none" autoCorrect={false} keyboardType="url" label="QwenPaw 地址" onChangeText={setBaseUrl} placeholder="http://192.168.1.20:8088" value={baseUrl} />
                  <Credentials password={password} setPassword={setPassword} setUsername={setUsername} username={username} />
                  <PrimaryButton disabled={!baseUrl} icon={ArrowRight} label="配对并连接" loading={busy} onPress={() => void submitDirect()} />
                  {busy ? (
                    <Pressable onPress={cancelDirect} style={styles.textButton}>
                      <Text style={styles.textButtonLabel}>取消连接</Text>
                    </Pressable>
                  ) : null}
                </>
              ) : null}
              {mode === "platform" ? (
                <PlatformAuthForm
                  loginLabel="登录并查找 QwenPaw"
                  onGitHubLogin={submitPlatformGitHub}
                  onPasswordLogin={submitPlatform}
                >
                  <Text style={styles.platformHint}>此登录态也会用于社区；浏览社区不需要登录。</Text>
                </PlatformAuthForm>
              ) : null}
              {__DEV__ && mode === "debug" ? (
                <>
                  <Field autoCapitalize="none" autoCorrect={false} label="Host" onChangeText={setDebugHost} placeholder={DEFAULT_DEBUG_HOST} value={debugHost} />
                  <Field keyboardType="number-pad" label="Port" onChangeText={setDebugPort} placeholder={String(DEFAULT_DEBUG_PORT)} value={debugPort} />
                  <Credentials password={password} setPassword={setPassword} setUsername={setUsername} username={username} />
                  <PrimaryButton icon={Bug} label="连接本机服务" loading={busy} onPress={() => void submitDirect(buildDebugBaseUrl(debugHost, debugPort))} />
                </>
              ) : null}
              {error ? <Text style={styles.error}>{error}</Text> : null}
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function DisconnectedHome({
  connection,
  onChooseAnother,
}: {
  connection: Connection;
  onChooseAnother: () => void;
}) {
  const status = useAppStore((state) => state.status);
  const connections = useAppStore((state) => state.connections);
  const connect = useAppStore((state) => state.connect);
  const disconnect = useAppStore((state) => state.disconnect);
  const switchConnection = useAppStore((state) => state.switchConnection);
  const storeError = useAppStore((state) => state.error);
  const [actionError, setActionError] = useState<string | null>(null);
  const [switchingKey, setSwitchingKey] = useState<string | null>(null);
  const currentKey = connectionKey(connection);
  const alternatives = connections.filter(
    (item) => connectionKey(item) !== currentKey,
  );
  const displayedError = actionError || storeError;

  const retry = async () => {
    setActionError(null);
    try {
      await connect(connection);
      router.replace("/chats");
    } catch (caught) {
      setActionError(errorMessage(caught, "暂时无法连接，请稍后重试。"));
    }
  };

  const switchTo = async (next: Connection) => {
    const key = connectionKey(next);
    setSwitchingKey(key);
    setActionError(null);
    try {
      await switchConnection(key);
      router.replace("/chats");
    } catch (caught) {
      setActionError(errorMessage(caught, "无法连接这只 QwenPaw。"));
    } finally {
      setSwitchingKey(null);
    }
  };

  const confirmRemove = () => {
    MobileAlert.alert(
      `移除${workspaceName(connection)}？`,
      "只会取消这台设备与该 QwenPaw 的配对，不会删除会话或服务数据。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "移除",
          style: "destructive",
          onPress: () => void disconnect().catch((caught) => {
            setActionError(errorMessage(caught, "暂时无法移除，请稍后重试。"));
          }),
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.reconnectRoot}>
      <ScrollView
        contentContainerStyle={styles.reconnectContent}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.reconnectIntro}>
          <Image
            accessible={false}
            resizeMode="contain"
            source={qwenPawBrandAssets.wave}
            style={styles.reconnectMascot}
          />
          <View style={styles.reconnectHeading}>
            <Text maxFontSizeMultiplier={1.35} style={styles.reconnectEyebrow}>
              QWENPAW
            </Text>
            <Text maxFontSizeMultiplier={1.4} style={styles.reconnectTitle}>
              连接已中断
            </Text>
            <Text maxFontSizeMultiplier={1.4} style={styles.reconnectSubtitle}>
              重试当前连接，或切换到另一只已配对的 QwenPaw。
            </Text>
          </View>
        </View>

        <View style={styles.currentConnectionCard}>
          <View style={styles.currentConnectionTop}>
            <View style={styles.connectionIcon}>
              {connection.source === "platform"
                ? <Cloud color={colors.accentDark} size={22} strokeWidth={1.9} />
                : <Server color={colors.accentDark} size={22} strokeWidth={1.9} />}
            </View>
            <View style={styles.currentConnectionBody}>
              <Text maxFontSizeMultiplier={1.35} numberOfLines={1} style={styles.currentConnectionTitle}>
                {workspaceName(connection)}
              </Text>
              <Text maxFontSizeMultiplier={1.3} style={styles.currentConnectionSource}>
                {connection.source === "platform"
                  ? "AgentScope Platform"
                  : "私人部署"}
              </Text>
            </View>
            <View style={styles.offlineStatus}>
              <WifiOff color={colors.danger} size={13} strokeWidth={2} />
              <Text style={styles.offlineStatusText}>未连接</Text>
            </View>
          </View>
          <Text maxFontSizeMultiplier={1.25} numberOfLines={1} style={styles.connectionHost}>
            {connectionHost(connection.baseUrl)}
          </Text>
          {displayedError ? (
            <View accessibilityRole="alert" style={styles.connectionError}>
              <Text maxFontSizeMultiplier={1.3} numberOfLines={3} style={styles.connectionErrorText}>
                {displayedError}
              </Text>
            </View>
          ) : null}
          <PrimaryButton
            icon={RefreshCw}
            label="重新连接"
            loading={status === "connecting"}
            onPress={() => void retry()}
          />
        </View>

        {alternatives.length ? (
          <IosGroup title="其他已配对的 QwenPaw">
            {alternatives.map((item) => (
              <IosRow
                key={connectionKey(item)}
                icon={item.source === "platform" ? Cloud : Server}
                label={workspaceName(item)}
                onPress={() => void switchTo(item)}
                subtitle={item.source === "platform" ? "AgentScope Platform" : "私人部署"}
                trailing={switchingKey === connectionKey(item) ? "连接中" : "切换"}
              />
            ))}
          </IosGroup>
        ) : null}

        <IosGroup title="连接管理">
          <IosRow
            icon={Link2}
            label="配对另一只 QwenPaw"
            onPress={onChooseAnother}
            subtitle="扫码、局域网或 AgentScope Platform"
          />
        </IosGroup>

        <IosGroup>
          <IosRow
            destructive
            icon={Trash2}
            label="移除当前 QwenPaw"
            onPress={confirmRemove}
          />
        </IosGroup>
      </ScrollView>
    </SafeAreaView>
  );
}

function connectionHost(value: string): string {
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}

function BrandHeader({ adding, mode, onBack }: { adding: boolean; mode: Mode; onBack: () => void }) {
  return (
    <View style={styles.brandHeader}>
      {mode === "choice" && !adding ? (
        <View style={styles.brandMark}>
          <Image
            accessible={false}
            resizeMode="contain"
            source={qwenPawBrandAssets.wave}
            style={styles.brandImage}
          />
        </View>
      ) : (
        <Pressable accessibilityLabel="返回" onPress={() => mode === "choice" ? router.back() : onBack()} style={styles.back}><ArrowLeft color={colors.ink} size={22} /></Pressable>
      )}
      <Text maxFontSizeMultiplier={1.35} style={styles.brand}>{adding ? "再配对一只 QwenPaw" : "QwenPaw"}</Text>
    </View>
  );
}

function ChoicePanel({
  adding,
  onMode,
  onPlatform,
  platformChecking,
}: {
  adding: boolean;
  onMode: (mode: Mode) => void;
  onPlatform: () => void;
  platformChecking: boolean;
}) {
  return (
    <View style={styles.choicePanel}>
      <View style={styles.intro}>
        <Text maxFontSizeMultiplier={1.35} style={styles.title}>{adding ? "再配对一只 QwenPaw" : "选择你的 QwenPaw"}</Text>
        <Text maxFontSizeMultiplier={1.45} style={styles.subtitle}>{adding ? "配对时不会断开当前 QwenPaw，完成后可以随时切换。" : "使用 Platform 云端 QwenPaw，或安全连接你自己的部署。"}</Text>
      </View>
      <ConnectionChoice
        copy="复用已登录的 Platform 账号并打开云端 QwenPaw"
        icon={Cloud}
        label="使用 AgentScope Platform"
        loading={platformChecking}
        onPress={onPlatform}
        primary
      />
      <ConnectionChoice icon={Link2} label="配对自己的 QwenPaw" copy="扫码配对，或连接局域网与私有服务" onPress={() => onMode("self")} />
      <View style={styles.choiceMascot}>
        <Image
          accessible={false}
          resizeMode="contain"
          source={qwenPawBrandAssets.full}
          style={styles.choiceMascotImage}
        />
        <View style={styles.choiceMascotCopy}>
          <Text maxFontSizeMultiplier={1.35} style={styles.choiceMascotTitle}>一处连接，多端随时切换</Text>
          <Text maxFontSizeMultiplier={1.35} style={styles.choiceMascotText}>
            Platform、本机与私人部署都由工作台统一管理。
          </Text>
        </View>
      </View>
      <Text style={styles.persistence}>QwenPaw 配对与 Platform 社区账号彼此独立，可在“工作台”中管理。</Text>
    </View>
  );
}

function ConnectionChoice({
  icon: Icon,
  label,
  copy,
  onPress,
  primary = false,
  loading = false,
}: {
  icon: typeof Cloud;
  label: string;
  copy: string;
  onPress: () => void;
  primary?: boolean;
  loading?: boolean;
}) {
  return (
    <Pressable
      disabled={loading}
      onPress={onPress}
      style={({ pressed }) => [
        styles.choice,
        primary && styles.primaryChoice,
        pressed && styles.pressed,
      ]}
    >
      <View style={styles.choiceIcon}><Icon color={colors.accentDark} size={23} /></View>
      <View style={styles.choiceBody}>
        <Text maxFontSizeMultiplier={1.35} style={styles.choiceTitle}>{label}</Text>
        <Text maxFontSizeMultiplier={1.3} style={styles.choiceCopy}>{copy}</Text>
      </View>
      {loading ? (
        <ActivityIndicator color={colors.accent} size="small" />
      ) : (
        <ChevronRight color={colors.faint} size={20} />
      )}
    </Pressable>
  );
}

function SelfPanel({ onMode }: { onMode: (mode: Mode) => void }) {
  return (
    <View style={styles.selfPanel}>
      <View style={styles.intro}><Text style={styles.formTitle}>配对自己的 QwenPaw</Text><Text style={styles.formCopy}>推荐从已登录 Console 扫码；配对后，除非你主动移除，否则会一直保持连接。</Text></View>
      <View style={styles.scanArt}><QrCode color={colors.accent} size={58} strokeWidth={1.35} /></View>
      <PrimaryButton icon={QrCode} label="扫码配对" onPress={() => router.push("/scan")} />
      <Pressable onPress={() => onMode("direct")} style={styles.manualLink}><Server color={colors.muted} size={17} /><Text style={styles.manualText}>手动输入服务地址</Text></Pressable>
      {__DEV__ ? <Pressable onPress={() => onMode("debug")} style={styles.debugLink}><Bug color={colors.faint} size={14} /><Text style={styles.debugText}>本机 Debug 连接</Text></Pressable> : null}
      <Text style={styles.persistence}>凭据保存在设备安全存储中，不主动移除就会保持配对。</Text>
    </View>
  );
}

function Credentials({ password, setPassword, setUsername, username }: { password: string; setPassword: (value: string) => void; setUsername: (value: string) => void; username: string }) {
  return (
    <>
      <Field autoCapitalize="none" label="用户名" onChangeText={setUsername} placeholder="未开启登录时可留空" value={username} />
      <Field label="密码" onChangeText={setPassword} placeholder="未开启登录时可留空" secureTextEntry value={password} />
    </>
  );
}

function modeTitle(mode: Mode): string {
  if (mode === "direct") return "手动连接";
  if (mode === "platform") return "AgentScope Platform";
  return "本机 Debug";
}

function modeCopy(mode: Mode): string {
  if (mode === "direct") return "输入手机或模拟器能够访问的 QwenPaw 地址。";
  if (mode === "platform") return "登录后自动查找并启动你的云端 QwenPaw。";
  return "无效 Host 或 Port 会回退到 127.0.0.1:8088。";
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.canvas },
  flex: { flex: 1 },
  loading: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.canvas },
  content: { width: "100%", maxWidth: 520, minHeight: "100%", alignSelf: "center", paddingHorizontal: spacing.lg, paddingBottom: spacing.xl },
  brandHeader: { height: 62, flexDirection: "row", alignItems: "center", gap: spacing.sm },
  brandMark: {
    width: 42,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
  },
  brandImage: { width: 42, height: 42 },
  back: { width: 34, height: 34, alignItems: "center", justifyContent: "center" },
  brand: { color: colors.ink, fontSize: 18, fontWeight: "700" },
  choicePanel: { flex: 1, gap: 12, paddingTop: spacing.xl },
  intro: { gap: spacing.sm, marginBottom: spacing.md },
  title: { color: colors.ink, fontSize: 34, lineHeight: 41, fontWeight: "700", letterSpacing: -1.1 },
  subtitle: { color: colors.muted, fontSize: 16, lineHeight: 24 },
  choice: { minHeight: 108, flexDirection: "row", alignItems: "center", gap: 13, padding: spacing.md, borderWidth: 1, borderColor: colors.line, borderRadius: 21, backgroundColor: colors.surface },
  primaryChoice: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  choiceIcon: { width: 46, height: 46, alignItems: "center", justifyContent: "center", borderRadius: 14, backgroundColor: colors.surfaceStrong },
  choiceBody: { flex: 1, minWidth: 0, gap: 5 },
  choiceTitle: { color: colors.ink, fontSize: 16, fontWeight: "700" },
  choiceCopy: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  choiceMascot: {
    minHeight: 112,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    overflow: "hidden",
    marginTop: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSoft,
  },
  choiceMascotImage: { width: 104, height: 104, alignSelf: "flex-end" },
  choiceMascotCopy: { flex: 1, minWidth: 0, gap: 5 },
  choiceMascotTitle: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  choiceMascotText: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  selfPanel: { flex: 1, gap: spacing.md, paddingTop: spacing.xl },
  scanArt: { width: 126, height: 126, alignSelf: "center", alignItems: "center", justifyContent: "center", marginVertical: spacing.md, borderRadius: 36, backgroundColor: colors.accentSoft },
  manualLink: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  manualText: { color: colors.muted, fontSize: 14, fontWeight: "600" },
  debugLink: { alignSelf: "center", flexDirection: "row", alignItems: "center", gap: spacing.xs, padding: spacing.sm },
  debugText: { color: colors.faint, fontSize: 12 },
  persistence: { color: colors.faint, fontSize: 11, lineHeight: 17, textAlign: "center", marginTop: "auto" },
  formCard: { gap: spacing.md, padding: spacing.md, marginTop: spacing.lg, borderRadius: radius.lg, backgroundColor: colors.surface },
  formHeading: { gap: spacing.xs, paddingBottom: spacing.sm },
  formTitle: { color: colors.ink, fontSize: 25, fontWeight: "700" },
  formCopy: { color: colors.muted, fontSize: 14, lineHeight: 20 },
  platformHint: { color: colors.faint, fontSize: 11, lineHeight: 17, textAlign: "center" },
  error: { color: colors.danger, fontSize: 13, lineHeight: 19 },
  choiceError: {
    marginTop: spacing.md,
    color: colors.danger,
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center",
  },
  pressed: { opacity: 0.72 },
  reconnectRoot: { flex: 1, backgroundColor: colors.groupedBackground },
  reconnectContent: {
    width: "100%",
    maxWidth: 520,
    minHeight: "100%",
    alignSelf: "center",
    gap: spacing.lg,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  reconnectIntro: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.sm,
  },
  reconnectMascot: { width: 72, height: 72 },
  reconnectHeading: { flex: 1, minWidth: 0, gap: 3 },
  reconnectEyebrow: {
    color: colors.accentDark,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.4,
  },
  reconnectTitle: {
    color: colors.ink,
    fontSize: 28,
    fontWeight: "700",
    letterSpacing: -0.7,
  },
  reconnectSubtitle: { color: colors.muted, fontSize: 14, lineHeight: 20 },
  currentConnectionCard: {
    gap: spacing.md,
    padding: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  currentConnectionTop: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  connectionIcon: {
    width: 46,
    height: 46,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 14,
    backgroundColor: colors.accentSoft,
  },
  currentConnectionBody: { flex: 1, minWidth: 0, gap: 3 },
  currentConnectionTitle: { color: colors.ink, fontSize: 17, fontWeight: "700" },
  currentConnectionSource: { color: colors.muted, fontSize: 12 },
  offlineStatus: {
    minHeight: 30,
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSoft,
  },
  offlineStatusText: { color: colors.danger, fontSize: 12, fontWeight: "600" },
  connectionHost: {
    color: colors.faint,
    fontSize: 12,
    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
  },
  connectionError: {
    paddingHorizontal: 12,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    backgroundColor: colors.accentSoft,
  },
  connectionErrorText: { color: colors.danger, fontSize: 12, lineHeight: 18 },
  textButton: { minHeight: 42, alignItems: "center", justifyContent: "center" },
  textButtonLabel: { color: colors.muted, fontSize: 14, fontWeight: "600" },
});
