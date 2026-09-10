import Constants from "expo-constants";
import { RefreshCw, WifiOff } from "lucide-react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DevSettings,
  Image,
  NativeModules,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { qwenPawBrandAssets } from "../theme/brandAssets";
import { colors, radius, spacing } from "../theme/tokens";
import { isMetroRunningStatus, metroStatusUrl } from "./metroStatus";

const POLL_INTERVAL_MS = 2500;
const REQUEST_TIMEOUT_MS = 1400;
const FAILURE_THRESHOLD = 2;

type ConnectionState = "checking" | "connected" | "disconnected";

type SourceCodeModule = {
  getConstants?: () => { scriptURL?: unknown };
  scriptURL?: unknown;
};

function loadedScriptUrl(): string | undefined {
  const sourceCode = NativeModules.SourceCode as SourceCodeModule | undefined;
  const value = sourceCode?.getConstants?.().scriptURL ?? sourceCode?.scriptURL;
  return typeof value === "string" ? value : undefined;
}

export function MetroConnectionGuard() {
  const statusUrl = useMemo(() => metroStatusUrl(
    loadedScriptUrl(),
    Constants.expoConfig?.hostUri,
  ), []);
  const [state, setState] = useState<ConnectionState>("checking");
  const [checking, setChecking] = useState(false);
  const stateRef = useRef<ConnectionState>("checking");
  const failures = useRef(0);

  const updateState = useCallback((next: ConnectionState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const probe = useCallback(async (reloadOnRecovery = false) => {
    if (!statusUrl) return false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(statusUrl, {
        cache: "no-store",
        signal: controller.signal,
      });
      const running = response.ok && isMetroRunningStatus(await response.text());
      if (!running) throw new Error("Metro status is not running");
      failures.current = 0;
      const recovered = stateRef.current === "disconnected";
      updateState("connected");
      if (recovered && reloadOnRecovery) DevSettings.reload();
      return true;
    } catch {
      failures.current += 1;
      if (failures.current >= FAILURE_THRESHOLD) {
        updateState("disconnected");
      }
      return false;
    } finally {
      clearTimeout(timeout);
    }
  }, [statusUrl, updateState]);

  useEffect(() => {
    if (!statusUrl) return undefined;
    const initial = setTimeout(() => void probe(), 0);
    const interval = setInterval(() => void probe(true), POLL_INTERVAL_MS);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
    };
  }, [probe, statusUrl]);

  const retry = async () => {
    setChecking(true);
    const connected = await probe(false);
    setChecking(false);
    if (connected) DevSettings.reload();
  };

  if (!statusUrl || state !== "disconnected") return null;

  return (
    <SafeAreaView accessibilityViewIsModal style={styles.overlay}>
      <View style={styles.card}>
        <View style={styles.illustration}>
          <Image
            accessible={false}
            resizeMode="contain"
            source={qwenPawBrandAssets.head}
            style={styles.paw}
          />
          <View style={styles.offlineBadge}>
            <WifiOff color={colors.white} size={19} strokeWidth={2.2} />
          </View>
        </View>
        <Text maxFontSizeMultiplier={1.4} style={styles.title}>
          开发服务未连接
        </Text>
        <Text maxFontSizeMultiplier={1.4} style={styles.copy}>
          QwenPaw Debug App 需要本机 Metro 才能加载画面。请在项目目录运行：
        </Text>
        <View style={styles.command}>
          <Text selectable style={styles.commandText}>npm start</Text>
        </View>
        <Pressable
          accessibilityLabel="重新连接 Metro"
          accessibilityRole="button"
          disabled={checking}
          onPress={() => void retry()}
          style={({ pressed }) => [
            styles.retry,
            pressed && styles.pressed,
            checking && styles.disabled,
          ]}
        >
          <RefreshCw color={colors.white} size={19} />
          <Text style={styles.retryText}>
            {checking ? "正在检测" : "重新连接"}
          </Text>
        </Pressable>
        <Text maxFontSizeMultiplier={1.3} style={styles.hint}>
          Release 版本内置完整画面，不需要 Metro，也不会显示此提示。
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  overlay: {
    position: "absolute",
    inset: 0,
    zIndex: 10000,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
    backgroundColor: colors.groupedBackground,
  },
  card: {
    width: "100%",
    maxWidth: 460,
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xl,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  illustration: { position: "relative", marginBottom: spacing.md },
  paw: { width: 92, height: 92 },
  offlineBadge: {
    position: "absolute",
    right: -3,
    bottom: 1,
    width: 36,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 3,
    borderColor: colors.surface,
    borderRadius: 18,
    backgroundColor: colors.accent,
  },
  title: {
    color: colors.ink,
    fontSize: 25,
    fontWeight: "700",
    letterSpacing: -0.5,
  },
  copy: {
    marginTop: spacing.sm,
    color: colors.muted,
    fontSize: 14,
    lineHeight: 21,
    textAlign: "center",
  },
  command: {
    width: "100%",
    marginTop: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSoft,
  },
  commandText: {
    color: colors.ink,
    fontFamily: "Menlo",
    fontSize: 14,
    textAlign: "center",
  },
  retry: {
    width: "100%",
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    marginTop: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.accent,
  },
  retryText: { color: colors.white, fontSize: 16, fontWeight: "700" },
  hint: {
    marginTop: spacing.md,
    color: colors.faint,
    fontSize: 12,
    lineHeight: 18,
    textAlign: "center",
  },
  pressed: { opacity: 0.78 },
  disabled: { opacity: 0.5 },
});
