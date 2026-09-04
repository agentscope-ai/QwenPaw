import { MobileAlert } from "@/components/MobileAlert";
import { router, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import {
  ArrowLeft,
  Check,
  Cloud,
  ExternalLink,
  KeyRound,
  RefreshCw,
  Rocket,
  ShieldAlert,
  TerminalSquare,
} from "lucide-react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  BackHandler,
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
  QwenPawCredentialsRequiredError,
} from "../../api/client";
import { resolvePlatformQwenPawAccess } from "../../api/platformGateway";
import {
  isPlatformRateLimitError,
  platformRateLimitDelay,
} from "../../api/platformError";
import { PrimaryButton } from "../../components/PrimaryButton";
import {
  createPlatformQwenPaw,
  getPlatformDeployment,
  getPlatformDeploymentLogs,
  listPlatformDeployments,
  resetPlatformQwenPawAuth,
  restartPlatformDeployment,
  startPlatformDeployment,
  switchPlatformDeploymentVersion,
} from "../../features/platform/deployment";
import {
  deploymentStatusPresentation,
  isGitHubBindingError,
  platformMobileCompatibility,
  platformDeploymentErrorMessage,
  type PlatformDeployment,
} from "../../features/platform/deploymentModel";
import { findConnectionByBaseUrl } from "../../storage/connectionModel";
import { useAppStore } from "../../store/app";
import { colors, radius, spacing } from "../../theme/tokens";
import { PLATFORM_BASE_URL } from "../../config/platform";

const POLL_INTERVAL_MS = 10_000;
const LOG_POLL_EVERY = 2;
const PLATFORM_SETTINGS_URL = `${PLATFORM_BASE_URL}/settings`;

interface DeploymentRefreshResult {
  deployment: PlatformDeployment | null;
  error: unknown | null;
}

export default function PlatformDeployScreen() {
  const { add } = useLocalSearchParams<{ add?: string }>();
  const connect = useAppStore((state) => state.connect);
  const connections = useAppStore((state) => state.connections);
  const logoutPlatform = useAppStore((state) => state.logoutPlatform);
  const [appId, setAppId] = useState<string | null>(null);
  const [deployment, setDeployment] = useState<PlatformDeployment | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [checking, setChecking] = useState(true);
  const [creating, setCreating] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [resettingAuth, setResettingAuth] = useState(false);
  const [switchingVersion, setSwitchingVersion] = useState<
    "preview" | "stable" | null
  >(null);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [pollRevision, setPollRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [rateLimited, setRateLimited] = useState(false);
  const [needsPlatformSettings, setNeedsPlatformSettings] = useState(false);
  const actionRef = useRef("");
  const pairingRef = useRef("");
  const refreshInFlightRef = useRef<Promise<DeploymentRefreshResult> | null>(
    null,
  );
  const compatibility = useMemo(
    () => platformMobileCompatibility(deployment?.versionType),
    [deployment?.versionType],
  );

  const showError = useCallback((caught: unknown) => {
    const limited = isPlatformRateLimitError(caught);
    setRateLimited(limited);
    setNeedsPlatformSettings(!limited && isGitHubBindingError(caught));
    setError(limited ? null : platformDeploymentErrorMessage(caught));
  }, []);

  const goBack = useCallback(() => {
    router.replace({
      pathname: "/",
      params: { add: add === "1" ? "1" : "0" },
    });
  }, [add]);

  useEffect(() => {
    if (Platform.OS !== "android") return undefined;
    const subscription = BackHandler.addEventListener(
      "hardwareBackPress",
      () => {
        goBack();
        return true;
      },
    );
    return () => subscription.remove();
  }, [goBack]);

  const checkDeployments = useCallback(async (): Promise<unknown | null> => {
    setChecking(true);
    setError(null);
    setNeedsPlatformSettings(false);
    try {
      const deployments = await listPlatformDeployments();
      const first = deployments[0];
      if (!first) {
        setAppId(null);
        setDeployment(null);
        setLogs([]);
        setRateLimited(false);
        return null;
      }
      setAppId(first.appId);
      setRateLimited(false);
      return null;
    } catch (caught) {
      showError(caught);
      return caught;
    } finally {
      setChecking(false);
    }
  }, [showError]);

  const refreshDeployment = useCallback(
    (id: string, includeLogs = false): Promise<DeploymentRefreshResult> => {
      if (refreshInFlightRef.current) return refreshInFlightRef.current;
      const request = (async (): Promise<DeploymentRefreshResult> => {
        try {
          const next = await getPlatformDeployment(id);
          setDeployment(next);
          if (includeLogs && !isTerminalDeployment(next)) {
            try {
              const nextLogs = await getPlatformDeploymentLogs(id);
              if (nextLogs.length) setLogs(nextLogs);
            } catch (caught) {
              if (isPlatformRateLimitError(caught)) throw caught;
            }
          }
          setError(null);
          setRateLimited(false);
          setNeedsPlatformSettings(false);
          return { deployment: next, error: null };
        } catch (caught) {
          showError(caught);
          return { deployment: null, error: caught };
        } finally {
          refreshInFlightRef.current = null;
        }
      })();
      refreshInFlightRef.current = request;
      return request;
    },
    [showError],
  );

  const pairDeployment = useCallback(
    async (accessUrl: string) => {
      const attemptKey = accessUrl.trim();
      pairingRef.current = attemptKey;
      setConnecting(true);
      setConnectionError(null);
      try {
        const access = await resolvePlatformQwenPawAccess(accessUrl);
        const savedConnection = findConnectionByBaseUrl(
          connections,
          "platform",
          access.baseUrl,
        );
        const connection = savedConnection
          ? { ...savedConnection, platformAccessPath: access.accessPath }
          : await loginQwenPaw(
              access.baseUrl,
              "",
              "",
              "platform",
              access.accessPath,
            );
        await connect(connection);
        router.replace("/chats");
      } catch (caught) {
        pairingRef.current = "";
        if (isPlatformRateLimitError(caught)) {
          setRateLimited(true);
          setConnectionError(null);
        } else if (caught instanceof QwenPawCredentialsRequiredError) {
          setNeedsAuth(true);
          setConnectionError(null);
        } else {
          setConnectionError(
            errorMessage(caught, "QwenPaw 配对失败，请重试。"),
          );
        }
      } finally {
        setConnecting(false);
      }
    },
    [connect, connections],
  );

  useEffect(() => {
    let cancelled = false;
    let failureCount = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const check = async () => {
      const caught = await checkDeployments();
      if (cancelled) return;
      const retryDelay = platformRateLimitDelay(caught, failureCount);
      if (retryDelay === null) return;
      failureCount += 1;
      timer = setTimeout(() => void check(), retryDelay);
    };
    timer = setTimeout(() => void check(), 0);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [checkDeployments, pollRevision]);

  useEffect(() => {
    if (!appId) return;
    let cancelled = false;
    let failureCount = 0;
    let pollCount = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      const result = await refreshDeployment(
        appId,
        pollCount % LOG_POLL_EVERY === 0,
      );
      if (cancelled) return;
      if (result.error) {
        const retryDelay = platformRateLimitDelay(result.error, failureCount);
        if (retryDelay !== null) {
          failureCount += 1;
          timer = setTimeout(() => void poll(), retryDelay);
          return;
        }
      } else {
        failureCount = 0;
        if (result.deployment && isTerminalDeployment(result.deployment)) {
          return;
        }
      }
      pollCount += 1;
      timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };
    timer = setTimeout(() => void poll(), 0);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [appId, pollRevision, refreshDeployment]);

  useEffect(() => {
    if (!deployment) return;
    const { appId: id, status } = deployment;
    if (status !== "sleeping" && status !== "stopped") return;
    const actionKey = `${id}:${status}`;
    if (actionRef.current === actionKey) return;
    actionRef.current = actionKey;
    void startPlatformDeployment(id)
      .then(() =>
        setDeployment((current) =>
          current?.appId === id ? { ...current, status: "waking_up" } : current,
        ),
      )
      .catch((caught) => {
        actionRef.current = "";
        showError(caught);
      });
  }, [deployment, refreshDeployment, showError]);

  useEffect(() => {
    const accessUrl = deployment?.accessUrl;
    if (
      deployment?.status !== "running" ||
      !accessUrl ||
      needsAuth ||
      !compatibility.compatible ||
      pairingRef.current === accessUrl.trim()
    )
      return;
    void pairDeployment(accessUrl);
  }, [compatibility.compatible, deployment, needsAuth, pairDeployment]);

  const continueWithPlatform = () => {
    if (!appId) return;
    MobileAlert.alert(
      "完成安全配对？",
      "QwenPaw 将重启一次以完成安全配对。会话、配置和 Agent workspace 都会保留。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "继续并重启",
          onPress: () => void resetQwenPawAuth(appId),
        },
      ],
    );
  };

  const resetQwenPawAuth = async (id: string) => {
    setResettingAuth(true);
    setConnectionError(null);
    try {
      await resetPlatformQwenPawAuth(id);
      await restartPlatformDeployment(id);
      pairingRef.current = "";
      actionRef.current = "";
      setNeedsAuth(false);
      setDeployment((current) =>
        current?.appId === id ? { ...current, status: "starting" } : current,
      );
      setPollRevision((current) => current + 1);
    } catch (caught) {
      setConnectionError(
        errorMessage(caught, "无法更新 QwenPaw 登录方式，请稍后重试。"),
      );
    } finally {
      setResettingAuth(false);
    }
  };

  const createDeployment = async () => {
    setCreating(true);
    setError(null);
    setNeedsPlatformSettings(false);
    setNeedsAuth(false);
    setConnectionError(null);
    try {
      const id = await createPlatformQwenPaw();
      setAppId(id);
      setDeployment({
        appId: id,
        status: "creating",
        accessUrl: "",
      });
      setLogs([]);
    } catch (caught) {
      showError(caught);
      if (isPlatformRateLimitError(caught)) {
        setPollRevision((current) => current + 1);
      }
    } finally {
      setCreating(false);
    }
  };

  const confirmRestartDeployment = () => {
    if (!appId || recovering) return;
    MobileAlert.alert(
      "重新启动 QwenPaw？",
      "Platform 会重建运行服务，但保留这只 QwenPaw 的会话、配置和 Agent workspace。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "重新启动",
          onPress: () => void restartFailedDeployment(appId),
        },
      ],
    );
  };

  const restartFailedDeployment = async (id: string) => {
    setRecovering(true);
    setError(null);
    setConnectionError(null);
    try {
      await restartPlatformDeployment(id);
      actionRef.current = "";
      pairingRef.current = "";
      setDeployment((current) =>
        current?.appId === id
          ? {
              ...current,
              status: "restarting",
              message: "正在重新启动 QwenPaw",
              errorMessage: undefined,
            }
          : current,
      );
      setPollRevision((current) => current + 1);
    } catch (caught) {
      setConnectionError(
        errorMessage(caught, "无法重新启动 QwenPaw，请稍后重试。"),
      );
    } finally {
      setRecovering(false);
    }
  };

  const confirmVersionSwitch = (version: "preview" | "stable") => {
    if (!appId || switchingVersion) return;
    const label = version === "stable" ? "稳定版" : "Beta";
    MobileAlert.alert(
      `切换到 QwenPaw ${label}？`,
      "Platform 会替换当前运行镜像，服务将短暂中断。不同版本可能使用独立数据目录。",
      [
        { text: "取消", style: "cancel" },
        {
          text: `切换到${label}`,
          onPress: () => void switchDeploymentVersion(appId, version),
        },
      ],
    );
  };

  const switchDeploymentVersion = async (
    id: string,
    version: "preview" | "stable",
  ) => {
    setSwitchingVersion(version);
    setError(null);
    setConnectionError(null);
    try {
      await switchPlatformDeploymentVersion(id, version);
      pairingRef.current = "";
      setDeployment((current) =>
        current?.appId === id
          ? {
              ...current,
              status: "updating",
              message:
                version === "stable"
                  ? "正在切换到 QwenPaw 稳定版"
                  : "正在切换到 QwenPaw Beta",
              errorMessage: undefined,
            }
          : current,
      );
      setPollRevision((current) => current + 1);
    } catch (caught) {
      setConnectionError(
        errorMessage(caught, "无法切换 QwenPaw 版本，请稍后重试。"),
      );
    } finally {
      setSwitchingVersion(null);
    }
  };

  const status = useMemo(() => {
    const presentation = deploymentStatusPresentation(
      rateLimited
        ? "rate_limited"
        : creating
        ? "creating"
        : deployment?.status ?? "idle",
    );
    return deployment?.message && !deployment.errorMessage
      ? { ...presentation, detail: deployment.message }
      : presentation;
  }, [creating, deployment, rateLimited]);
  const hasDeployment = Boolean(appId);
  const progress = deploymentProgress(deployment?.status, hasDeployment);
  const deploymentFailure =
    deployment?.status === "failed" && deployment.errorMessage
      ? platformDeploymentErrorMessage(new Error(deployment.errorMessage))
      : null;

  const switchPlatformAccount = async () => {
    await logoutPlatform();
    router.replace({
      pathname: "/",
      params: {
        add: add === "1" ? "1" : "0",
        platformLogin: "1",
      },
    });
  };

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.fixedHeader}>
        <View style={styles.header}>
          <Pressable
            accessibilityLabel="返回"
            accessibilityRole="button"
            onPress={goBack}
            style={({ pressed }) => [styles.back, pressed && styles.pressed]}
          >
            <ArrowLeft color={colors.ink} size={22} />
          </Pressable>
          <Text style={styles.headerTitle}>云端 QwenPaw</Text>
          <View style={styles.headerSpacer} />
        </View>
      </View>
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.hero}>
          <View style={styles.heroIcon}>
            <Cloud color={colors.white} size={25} />
          </View>
          <Text style={styles.title}>
            {hasDeployment ? "正在打开你的 QwenPaw" : "创建你的云端 QwenPaw"}
          </Text>
          <Text style={styles.subtitle}>
            {hasDeployment
              ? "登录态已经保留。服务就绪后会自动完成配对，无需再次登录 Platform。"
              : "一键创建隔离的云端实例。对话、Skills 与配置会持久保存，重新部署时自动恢复。"}
          </Text>
        </View>

        {checking ? (
          <View style={styles.checkingCard}>
            <ActivityIndicator color={colors.accent} />
            <Text style={styles.checkingText}>正在检查 Platform 部署…</Text>
          </View>
        ) : (
          <>
            <View style={styles.progressCard}>
              <View style={styles.statusHeading}>
                <View style={styles.statusCopy}>
                  <Text style={styles.statusLabel}>{status.label}</Text>
                  <Text style={styles.statusDetail}>{status.detail}</Text>
                </View>
                {status.active || connecting ? (
                  <ActivityIndicator color={colors.accent} />
                ) : status.failed ? (
                  <RefreshCw color={colors.danger} size={20} />
                ) : hasDeployment ? (
                  <Check color={colors.accent} size={21} />
                ) : (
                  <Cloud color={colors.accent} size={21} />
                )}
              </View>
              <View style={styles.steps}>
                <ProgressStep index={1} label="创建实例" progress={progress} />
                <View
                  style={[styles.stepLine, progress > 1 && styles.stepLineDone]}
                />
                <ProgressStep index={2} label="启动服务" progress={progress} />
                <View
                  style={[styles.stepLine, progress > 2 && styles.stepLineDone]}
                />
                <ProgressStep index={3} label="安全配对" progress={progress} />
              </View>
            </View>

            {deployment?.status === "running" && !compatibility.compatible ? (
              <View style={styles.authCard}>
                <View style={styles.authIcon}>
                  <ShieldAlert color={colors.accentDark} size={21} />
                </View>
                <Text style={styles.authTitle}>当前镜像暂不支持 Mobile</Text>
                <Text style={styles.authCopy}>
                  已检测到 {compatibility.label}。QwenPaw Mobile 目前支持
                  稳定版和 Beta，切换后会自动继续配对。
                </Text>
                <PrimaryButton
                  label="切换到稳定版（推荐）"
                  loading={switchingVersion === "stable"}
                  disabled={switchingVersion === "preview"}
                  onPress={() => confirmVersionSwitch("stable")}
                />
                <PrimaryButton
                  label="切换到 Beta"
                  loading={switchingVersion === "preview"}
                  disabled={switchingVersion === "stable"}
                  onPress={() => confirmVersionSwitch("preview")}
                  tone="light"
                />
                <Text style={styles.authFootnote}>
                  版本切换由 Platform 执行；Mobile 只调用公开接口并追踪状态。
                </Text>
              </View>
            ) : null}

            {needsAuth && deployment?.accessUrl ? (
              <View style={styles.authCard}>
                <View style={styles.authIcon}>
                  <KeyRound color={colors.accentDark} size={21} />
                </View>
                <Text style={styles.authTitle}>完成安全配对</Text>
                <Text style={styles.authCopy}>
                  还差最后一步。使用当前 Platform 登录完成配对，之后即可直接
                  打开这只 QwenPaw。
                </Text>
                <PrimaryButton
                  label="继续配对"
                  loading={resettingAuth}
                  onPress={continueWithPlatform}
                />
                <Text style={styles.authFootnote}>
                  配对过程中服务会重启；不会删除任何工作数据。
                </Text>
              </View>
            ) : null}

            {hasDeployment ? (
              <View style={styles.logCard}>
                <View style={styles.logHeader}>
                  <TerminalSquare color="#FFB36E" size={17} />
                  <Text style={styles.logTitle}>部署日志</Text>
                  <View style={styles.liveDot} />
                  <Text style={styles.liveText}>LIVE</Text>
                </View>
                <View style={styles.logBody}>
                  {logs.length ? (
                    logs.slice(-40).map((line, index) => (
                      <Text key={`${index}-${line}`} style={styles.logLine}>
                        {line}
                      </Text>
                    ))
                  ) : (
                    <Text style={styles.logEmpty}>
                      {deployment?.message || "等待 Platform 返回部署日志…"}
                    </Text>
                  )}
                </View>
              </View>
            ) : null}

            {error || connectionError || deploymentFailure ? (
              <Text accessibilityRole="alert" style={styles.error}>
                {error || connectionError || deploymentFailure}
              </Text>
            ) : null}

            <View style={styles.actions}>
              {!rateLimited && !hasDeployment ? (
                <PrimaryButton
                  icon={Rocket}
                  label="部署我的 QwenPaw"
                  loading={creating}
                  onPress={() => void createDeployment()}
                />
              ) : null}

              {status.failed && appId ? (
                <>
                  <PrimaryButton
                    icon={RefreshCw}
                    label="重新启动 QwenPaw"
                    loading={recovering}
                    onPress={confirmRestartDeployment}
                  />
                  <PrimaryButton
                    icon={RefreshCw}
                    label="重新检查状态"
                    onPress={() => void refreshDeployment(appId)}
                    tone="light"
                  />
                  <PrimaryButton
                    icon={ArrowLeft}
                    label="返回选择其他 QwenPaw"
                    onPress={goBack}
                    tone="light"
                  />
                </>
              ) : null}

              {error && hasDeployment && !status.failed ? (
                <PrimaryButton
                  icon={RefreshCw}
                  label="重新检查部署"
                  onPress={() => void refreshDeployment(appId as string)}
                  tone="light"
                />
              ) : null}

              {needsPlatformSettings ? (
                <PrimaryButton
                  icon={ExternalLink}
                  label="前往 Platform 绑定 GitHub"
                  onPress={() =>
                    void WebBrowser.openBrowserAsync(PLATFORM_SETTINGS_URL)
                  }
                  tone="light"
                />
              ) : null}
            </View>
          </>
        )}

        <Pressable
          onPress={() => void switchPlatformAccount()}
          style={styles.switchAccount}
        >
          <Text style={styles.switchAccountText}>切换 Platform 账号</Text>
        </Pressable>
        <Text style={styles.footer}>
          Platform 账号与 QwenPaw 配对相互独立；离开此页不会退出 Platform。
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function ProgressStep({
  index,
  label,
  progress,
}: {
  index: number;
  label: string;
  progress: number;
}) {
  const done = progress > index;
  const active = progress === index;
  return (
    <View style={styles.step}>
      <View
        style={[
          styles.stepCircle,
          done && styles.stepCircleDone,
          active && styles.stepCircleActive,
        ]}
      >
        {done ? (
          <Check color={colors.white} size={13} strokeWidth={3} />
        ) : (
          <Text style={[styles.stepNumber, active && styles.stepNumberActive]}>
            {index}
          </Text>
        )}
      </View>
      <Text
        style={[styles.stepLabel, (done || active) && styles.stepLabelActive]}
      >
        {label}
      </Text>
    </View>
  );
}

function deploymentProgress(
  status: string | undefined,
  exists: boolean,
): number {
  if (!exists) return 1;
  if (status === "running") return 3;
  if (
    [
      "restarting",
      "starting",
      "sleeping",
      "updating",
      "waking_up",
      "stopped",
    ].includes(status ?? "")
  ) {
    return 2;
  }
  return 1;
}

function isTerminalDeployment(deployment: PlatformDeployment): boolean {
  if (deployment.status === "failed" || deployment.status === "deleted") {
    return true;
  }
  return deployment.status === "running" && Boolean(deployment.accessUrl);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.canvas },
  fixedHeader: {
    width: "100%",
    maxWidth: 560,
    alignSelf: "center",
    paddingHorizontal: spacing.md,
    backgroundColor: colors.canvas,
  },
  content: {
    width: "100%",
    maxWidth: 560,
    minHeight: "100%",
    alignSelf: "center",
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xl,
  },
  header: {
    height: 56,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  back: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  headerTitle: { color: colors.ink, fontSize: 17, fontWeight: "700" },
  headerSpacer: { width: 40 },
  hero: { gap: spacing.sm, paddingTop: spacing.lg, paddingBottom: spacing.lg },
  heroIcon: {
    width: 54,
    height: 54,
    marginBottom: spacing.sm,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 17,
    backgroundColor: colors.accent,
  },
  title: {
    color: colors.ink,
    fontSize: 31,
    lineHeight: 38,
    fontWeight: "700",
    letterSpacing: -0.8,
  },
  subtitle: { color: colors.muted, fontSize: 15, lineHeight: 23 },
  checkingCard: {
    minHeight: 120,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  checkingText: { color: colors.muted, fontSize: 14 },
  progressCard: {
    gap: spacing.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  statusHeading: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  statusCopy: { flex: 1, gap: 5 },
  statusLabel: { color: colors.ink, fontSize: 19, fontWeight: "700" },
  statusDetail: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  steps: { flexDirection: "row", alignItems: "flex-start" },
  step: { width: 70, alignItems: "center", gap: 7 },
  stepCircle: {
    width: 28,
    height: 28,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.hairline,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
  },
  stepCircleActive: {
    borderColor: colors.accent,
    backgroundColor: colors.accentSoft,
  },
  stepCircleDone: {
    borderColor: colors.accent,
    backgroundColor: colors.accent,
  },
  stepNumber: { color: colors.faint, fontSize: 12, fontWeight: "700" },
  stepNumberActive: { color: colors.accentDark },
  stepLabel: { color: colors.faint, fontSize: 11, fontWeight: "600" },
  stepLabelActive: { color: colors.ink },
  stepLine: {
    flex: 1,
    height: 1,
    marginTop: 14,
    backgroundColor: colors.hairline,
  },
  stepLineDone: { backgroundColor: colors.accent },
  authCard: {
    gap: spacing.md,
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  authIcon: {
    width: 42,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 13,
    backgroundColor: colors.accentSoft,
  },
  authTitle: { color: colors.ink, fontSize: 17, fontWeight: "700" },
  authCopy: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  authFootnote: {
    color: colors.faint,
    fontSize: 11,
    lineHeight: 17,
    textAlign: "center",
  },
  logCard: {
    marginTop: spacing.md,
    overflow: "hidden",
    borderRadius: radius.lg,
    backgroundColor: "#211D1A",
  },
  logHeader: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#413A35",
  },
  logTitle: { flex: 1, color: "#F8EEE7", fontSize: 13, fontWeight: "700" },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.accent,
  },
  liveText: {
    color: "#AFA39A",
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 1,
  },
  logBody: { minHeight: 132, maxHeight: 260, gap: 7, padding: spacing.md },
  logLine: {
    color: "#D9CEC6",
    fontSize: 11,
    lineHeight: 17,
    fontFamily: "Menlo",
  },
  logEmpty: { color: "#8F857E", fontSize: 11, fontFamily: "Menlo" },
  error: {
    marginTop: spacing.md,
    color: colors.danger,
    fontSize: 13,
    lineHeight: 19,
  },
  actions: { gap: spacing.sm, marginTop: spacing.md },
  switchAccount: {
    minHeight: 44,
    marginTop: spacing.lg,
    alignItems: "center",
    justifyContent: "center",
  },
  switchAccountText: { color: colors.muted, fontSize: 13, fontWeight: "600" },
  footer: {
    marginTop: "auto",
    paddingTop: spacing.xl,
    color: colors.faint,
    fontSize: 11,
    lineHeight: 17,
    textAlign: "center",
  },
  pressed: { opacity: 0.6 },
});
