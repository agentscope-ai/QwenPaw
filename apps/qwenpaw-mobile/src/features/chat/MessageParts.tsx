import { MobileAlert } from "@/components/MobileAlert";
import {
  AudioLines,
  Download,
  FileText,
  Film,
  Share2,
} from "lucide-react-native";
import { useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import Markdown from "react-native-markdown-display";
import { SafeAreaView } from "react-native-safe-area-context";

import { mediaSource } from "../../api/client";
import type { Connection, DisplayPart } from "../../api/types";
import { colors, radius, spacing } from "../../theme/tokens";
import {
  AnchoredActionMenu,
  type AnchorRect,
} from "./AnchoredActionMenu";
import { saveImageToLibrary, shareMedia } from "./mediaActions";

type MediaPart = Exclude<DisplayPart, { type: "text" }>;

export function MessageParts({
  connection,
  compact = false,
  parts,
  selecting = false,
  user = false,
}: {
  connection: Connection;
  compact?: boolean;
  parts: DisplayPart[];
  selecting?: boolean;
  user?: boolean;
}) {
  const viewport = useWindowDimensions();
  const [preview, setPreview] = useState<MediaPart | null>(null);
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState<{
    anchor: AnchorRect;
    part: MediaPart;
  } | null>(null);
  const longPressed = useRef(false);
  const mediaRefs = useRef(new Map<string, View>());

  const runAction = async (action: "save" | "share", part: MediaPart) => {
    setBusy(true);
    try {
      if (action === "save" && part.type === "image") {
        await saveImageToLibrary(connection, part);
        MobileAlert.alert("已保存", "图片已保存到照片。");
      } else {
        await shareMedia(connection, part);
      }
    } catch (error) {
      MobileAlert.alert(
        action === "save" ? "保存失败" : "分享失败",
        error instanceof Error ? error.message : "请稍后重试。",
      );
    } finally {
      setBusy(false);
    }
  };

  const showAnchoredActions = (part: MediaPart, key: string) => {
    mediaRefs.current.get(key)?.measureInWindow((x, y, width, height) => {
      setMenu({ anchor: { x, y, width, height }, part });
    });
  };

  return (
    <>
      <View style={styles.parts}>
        {parts.map((part, index) => {
          if (part.type === "text") {
            return user ? (
              <Text
                key={`text-${index}`}
                selectable={selecting}
                selectionColor={colors.accentSoft}
                style={styles.userText}
              >
                {part.text}
              </Text>
            ) : selecting ? (
              <Text
                key={`text-${index}`}
                selectable
                selectionColor={colors.accentSoft}
                style={styles.selectionText}
              >
                {part.text}
              </Text>
            ) : (
              <Markdown key={`text-${index}`} style={markdownStyles}>{part.text}</Markdown>
            );
          }
          if (part.type === "image") {
            const mediaKey = `${part.type}-${part.url}-${index}`;
            return (
              <Pressable
                delayLongPress={320}
                key={mediaKey}
                onLongPress={(event) => {
                  event.stopPropagation();
                  longPressed.current = true;
                  showAnchoredActions(part, mediaKey);
                }}
                onPress={(event) => {
                  event.stopPropagation();
                  if (longPressed.current) {
                    longPressed.current = false;
                    return;
                  }
                  setPreview(part);
                }}
                ref={(node) => {
                  if (node) mediaRefs.current.set(mediaKey, node);
                  else mediaRefs.current.delete(mediaKey);
                }}
                style={[styles.imageFrame, compact && styles.imageFrameCompact]}
              >
                <Image
                  resizeMode="cover"
                  source={mediaSource(connection, part.url)}
                  style={styles.image}
                />
              </Pressable>
            );
          }
          const mediaKey = `${part.type}-${part.url}-${index}`;
          return (
            <Pressable
              delayLongPress={320}
              key={mediaKey}
              onLongPress={(event) => {
                event.stopPropagation();
                longPressed.current = true;
                showAnchoredActions(part, mediaKey);
              }}
              onPress={(event) => {
                event.stopPropagation();
                if (longPressed.current) {
                  longPressed.current = false;
                  return;
                }
                void runAction("share", part);
              }}
              ref={(node) => {
                if (node) mediaRefs.current.set(mediaKey, node);
                else mediaRefs.current.delete(mediaKey);
              }}
              style={[styles.fileCard, user && styles.userFileCard]}
            >
              <View style={[styles.fileIcon, user && styles.userFileIcon]}>
                {part.type === "video" ? (
                  <Film color={user ? colors.white : colors.accentDark} size={19} />
                ) : part.type === "audio" ? (
                  <AudioLines color={user ? colors.white : colors.accentDark} size={19} />
                ) : (
                  <FileText color={user ? colors.white : colors.accentDark} size={19} />
                )}
              </View>
              <View style={styles.fileBody}>
                <Text numberOfLines={1} style={[styles.fileName, user && styles.userFileText]}>
                  {part.name || mediaLabel(part.type)}
                </Text>
                <Text style={[styles.fileMeta, user && styles.userFileMeta]}>
                  {mediaLabel(part.type)} · 点击打开
                </Text>
              </View>
            </Pressable>
          );
        })}
      </View>
      <Modal animationType="fade" onRequestClose={() => setPreview(null)} visible={Boolean(preview)}>
        <Pressable
          accessibilityLabel="轻点关闭图片，长按显示保存选项"
          delayLongPress={420}
          onLongPress={() => {
            if (!preview) return;
            longPressed.current = true;
            setMenu({
              anchor: {
                height: 2,
                width: 2,
                x: viewport.width / 2 - 1,
                y: viewport.height - 92,
              },
              part: preview,
            });
          }}
          onPress={() => {
            if (longPressed.current) {
              longPressed.current = false;
              return;
            }
            setPreview(null);
          }}
          style={styles.previewRoot}
        >
          <SafeAreaView pointerEvents="none" style={styles.previewSafeArea}>
            <View style={styles.previewHint}>
              <Download color={colors.white} size={15} />
              <Text style={styles.previewHintText}>轻点退出 · 长按保存或分享</Text>
              <Share2 color={colors.white} size={15} />
            </View>
            {preview?.type === "image" ? (
              <Image
                resizeMode="contain"
                source={mediaSource(connection, preview.url)}
                style={styles.fullImage}
              />
            ) : null}
            {busy ? (
              <View style={styles.busy}>
                <ActivityIndicator color={colors.white} />
              </View>
            ) : null}
          </SafeAreaView>
        </Pressable>
      </Modal>
      <AnchoredActionMenu
        actions={menu?.part.type === "image"
          ? [
            {
              icon: Download,
              label: "保存",
              onPress: () => void runAction("save", menu.part),
            },
            {
              icon: Share2,
              label: "分享",
              onPress: () => void runAction("share", menu.part),
            },
          ]
          : menu
            ? [{
              icon: Share2,
              label: "分享",
              onPress: () => void runAction("share", menu.part),
            }]
            : []}
        anchor={menu?.anchor ?? null}
        onClose={() => setMenu(null)}
      />
    </>
  );
}

function mediaLabel(type: DisplayPart["type"]): string {
  if (type === "video") return "视频";
  if (type === "audio") return "音频";
  if (type === "image") return "图片";
  return "文件";
}

const markdownStyles = {
  body: { color: colors.ink, fontSize: 16, lineHeight: 26 },
  paragraph: { marginTop: 0, marginBottom: 12 },
  heading1: {
    marginTop: 8,
    marginBottom: 10,
    color: colors.ink,
    fontSize: 22,
    lineHeight: 29,
    fontWeight: "700" as const,
  },
  heading2: {
    marginTop: 8,
    marginBottom: 8,
    color: colors.ink,
    fontSize: 19,
    lineHeight: 26,
    fontWeight: "700" as const,
  },
  heading3: {
    marginTop: 6,
    marginBottom: 7,
    color: colors.ink,
    fontSize: 17,
    lineHeight: 24,
    fontWeight: "700" as const,
  },
  strong: { color: colors.ink, fontWeight: "700" as const },
  bullet_list: { marginBottom: 10 },
  ordered_list: { marginBottom: 10 },
  list_item: { marginBottom: 4 },
  blockquote: {
    marginVertical: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderLeftWidth: 3,
    borderLeftColor: colors.accent,
    backgroundColor: colors.accentSoft,
  },
  code_inline: {
    paddingHorizontal: 4,
    borderRadius: 5,
    backgroundColor: colors.searchBackground,
    color: colors.ink,
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace" }),
    fontSize: 14,
    lineHeight: 20,
  },
  fence: {
    padding: 13,
    borderColor: colors.black,
    borderRadius: 12,
    backgroundColor: colors.black,
    color: "#E7ECE7",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace" }),
    fontSize: 13,
    lineHeight: 20,
  },
  link: { color: colors.accentDark, textDecorationLine: "underline" as const },
};

const styles = StyleSheet.create({
  parts: { gap: spacing.sm },
  userText: { color: colors.white, fontSize: 16, lineHeight: 24 },
  selectionText: { color: colors.ink, fontSize: 16, lineHeight: 26 },
  imageFrame: { width: "100%", aspectRatio: 1.28, overflow: "hidden", borderRadius: radius.md, backgroundColor: colors.pressed },
  imageFrameCompact: { maxHeight: 180, aspectRatio: 1.8 },
  image: { width: "100%", height: "100%" },
  fileCard: { minHeight: 62, flexDirection: "row", alignItems: "center", gap: 10, padding: 10, borderRadius: radius.md, backgroundColor: colors.accentSoft },
  userFileCard: { backgroundColor: "rgba(255,255,255,0.16)" },
  fileIcon: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 12, backgroundColor: colors.surfaceStrong },
  userFileIcon: { backgroundColor: "rgba(255,255,255,0.15)" },
  fileBody: { flex: 1, minWidth: 0, gap: 3 },
  fileName: { color: colors.ink, fontSize: 14, fontWeight: "600" },
  fileMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  userFileText: { color: colors.white },
  userFileMeta: { color: "rgba(255,255,255,0.72)" },
  previewRoot: { flex: 1, backgroundColor: colors.black },
  previewSafeArea: { flex: 1 },
  previewHint: { position: "absolute", zIndex: 2, top: 14, alignSelf: "center", flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 18, backgroundColor: "rgba(20,20,20,0.72)" },
  previewHintText: { color: colors.white, fontSize: 11, fontWeight: "600" },
  fullImage: { flex: 1, width: "100%" },
  busy: { position: "absolute", inset: 0, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.42)" },
});
