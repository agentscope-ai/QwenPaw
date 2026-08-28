import { CameraView, useCameraPermissions } from "expo-camera";
import { router } from "expo-router";
import { ArrowLeft, Camera, ShieldCheck } from "lucide-react-native";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { redeemPairing } from "../api/client";
import { parsePairingUri } from "../api/pairing";
import { PrimaryButton } from "../components/PrimaryButton";
import { useAppStore } from "../store/app";
import { colors, radius, spacing } from "../theme/tokens";

export default function ScanScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const connect = useAppStore((state) => state.connect);
  const [scanned, setScanned] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCode = async (data: string) => {
    if (scanned) return;
    setScanned(true);
    setError(null);
    try {
      const payload = parsePairingUri(data);
      const connection = await redeemPairing(payload.baseUrl, payload.ticket);
      await connect(connection);
      router.replace("/chats");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Pairing failed.");
      setScanned(false);
    }
  };

  if (!permission?.granted) {
    return (
      <SafeAreaView style={styles.permission}>
        <View style={styles.permissionIcon}><Camera size={30} color={colors.accentDark} /></View>
        <Text style={styles.permissionTitle}>Camera access</Text>
        <Text style={styles.permissionCopy}>
          QwenPaw only uses the camera to read your short-lived pairing code.
        </Text>
        <PrimaryButton label="Allow camera" icon={Camera} onPress={() => void requestPermission()} />
        <PrimaryButton label="Go back" tone="light" onPress={() => router.back()} />
      </SafeAreaView>
    );
  }

  return (
    <View style={styles.root}>
      <CameraView
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        onBarcodeScanned={({ data }) => void handleCode(data)}
        style={StyleSheet.absoluteFill}
      />
      <View style={styles.shade} />
      <SafeAreaView style={styles.overlay}>
        <View style={styles.header}>
          <Pressable accessibilityLabel="Back" onPress={() => router.back()} style={styles.iconButton}>
            <ArrowLeft color={colors.white} size={22} />
          </Pressable>
          <View style={styles.secureLabel}>
            <ShieldCheck color={colors.white} size={16} />
            <Text style={styles.secureText}>Secure pairing</Text>
          </View>
          <View style={styles.iconSpacer} />
        </View>
        <View style={styles.center}>
          <View style={styles.frame}>
            <View style={[styles.corner, styles.topLeft]} />
            <View style={[styles.corner, styles.topRight]} />
            <View style={[styles.corner, styles.bottomLeft]} />
            <View style={[styles.corner, styles.bottomRight]} />
          </View>
          <Text style={styles.title}>{scanned ? "Linking…" : "Scan QwenPaw Console"}</Text>
          <Text style={styles.copy}>The pairing code expires after two minutes.</Text>
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.black },
  shade: { ...StyleSheet.absoluteFill, backgroundColor: "rgba(10,12,10,0.40)" },
  overlay: { flex: 1, padding: spacing.lg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  iconButton: { width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(0,0,0,0.35)", alignItems: "center", justifyContent: "center" },
  iconSpacer: { width: 44 },
  secureLabel: { flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.md, height: 38, borderRadius: radius.pill, backgroundColor: "rgba(0,0,0,0.35)" },
  secureText: { color: colors.white, fontSize: 13, fontWeight: "600" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  frame: { width: 260, height: 260, marginBottom: spacing.lg },
  corner: { position: "absolute", width: 54, height: 54, borderColor: colors.white },
  topLeft: { top: 0, left: 0, borderTopWidth: 4, borderLeftWidth: 4, borderTopLeftRadius: 24 },
  topRight: { top: 0, right: 0, borderTopWidth: 4, borderRightWidth: 4, borderTopRightRadius: 24 },
  bottomLeft: { bottom: 0, left: 0, borderBottomWidth: 4, borderLeftWidth: 4, borderBottomLeftRadius: 24 },
  bottomRight: { bottom: 0, right: 0, borderBottomWidth: 4, borderRightWidth: 4, borderBottomRightRadius: 24 },
  title: { color: colors.white, fontSize: 24, fontWeight: "600", letterSpacing: -0.6 },
  copy: { color: "rgba(255,255,255,0.72)", fontSize: 14 },
  error: { color: "#FFD0CB", textAlign: "center", fontSize: 14 },
  permission: { flex: 1, justifyContent: "center", padding: spacing.xl, gap: spacing.md, backgroundColor: colors.canvas },
  permissionIcon: { width: 64, height: 64, borderRadius: 22, backgroundColor: colors.accentSoft, alignItems: "center", justifyContent: "center" },
  permissionTitle: { fontSize: 30, fontWeight: "600", letterSpacing: -1, color: colors.ink },
  permissionCopy: { fontSize: 16, lineHeight: 24, color: colors.muted, marginBottom: spacing.md },
});
