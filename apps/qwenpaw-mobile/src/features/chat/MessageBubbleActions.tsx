import * as Clipboard from "expo-clipboard";
import { Check, Copy, TextSelect, X } from "lucide-react-native";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import {
  BackHandler,
  Pressable,
  StyleSheet,
  Text,
  type StyleProp,
  View,
  type ViewStyle,
} from "react-native";

import { colors } from "../../theme/tokens";
import {
  AnchoredActionMenu,
  type AnchorRect,
} from "./AnchoredActionMenu";

export function MessageBubbleActions({
  children,
  inverted = false,
  style,
  text,
}: {
  children: ReactNode | ((selecting: boolean) => ReactNode);
  inverted?: boolean;
  style?: StyleProp<ViewStyle>;
  text: string;
}) {
  const [selecting, setSelecting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [menuAnchor, setMenuAnchor] = useState<AnchorRect | null>(null);
  const bubbleRef = useRef<View>(null);

  useEffect(() => {
    if (!selecting) return undefined;
    const listener = BackHandler.addEventListener("hardwareBackPress", () => {
      setSelecting(false);
      return true;
    });
    return () => listener.remove();
  }, [selecting]);

  if (!text) {
    return (
      <View style={style}>
        {typeof children === "function" ? children(false) : children}
      </View>
    );
  }

  const copy = async () => {
    await Clipboard.setStringAsync(text);
    setCopied(true);
  };

  const showActions = () => {
    bubbleRef.current?.measureInWindow((x, y, width, height) => {
      setMenuAnchor({ x, y, width, height });
    });
  };

  const content = typeof children === "function"
    ? children(selecting)
    : children;

  return (
    <>
      {selecting ? (
        <View ref={bubbleRef} style={style}>
          <View
            accessibilityLiveRegion="polite"
            style={[
              styles.selectionToolbar,
              inverted && styles.selectionToolbarInverted,
            ]}
          >
            <View style={styles.selectionHint}>
              <TextSelect
                color={inverted ? colors.white : colors.accentDark}
                size={17}
              />
              <Text
                maxFontSizeMultiplier={1.25}
                style={[
                  styles.selectionHintText,
                  inverted && styles.selectionTextInverted,
                ]}
              >
                长按文字拖动选择
              </Text>
            </View>
            <Pressable
              accessibilityLabel="复制全文"
              onPress={() => void copy()}
              style={({ pressed }) => [
                styles.selectionAction,
                pressed && styles.selectionActionPressed,
              ]}
            >
              {copied ? (
                <Check color={inverted ? colors.white : colors.accentDark} size={18} />
              ) : (
                <Copy color={inverted ? colors.white : colors.accentDark} size={18} />
              )}
            </Pressable>
            <Pressable
              accessibilityLabel="完成选择"
              onPress={() => setSelecting(false)}
              style={({ pressed }) => [
                styles.selectionAction,
                pressed && styles.selectionActionPressed,
              ]}
            >
              <X color={inverted ? colors.white : colors.ink} size={19} />
            </Pressable>
          </View>
          {content}
        </View>
      ) : (
        <Pressable
          accessibilityHint="长按可复制或选择文本"
          delayLongPress={320}
          onLongPress={showActions}
          ref={bubbleRef}
          style={({ pressed }) => [style, pressed && styles.pressed]}
        >
          {content}
        </Pressable>
      )}
      <AnchoredActionMenu
        actions={[
          {
            icon: Copy,
            label: "复制",
            onPress: () => void copy(),
          },
          {
            icon: TextSelect,
            label: "选择文本",
            onPress: () => {
              setCopied(false);
              setSelecting(true);
            },
          },
        ]}
        anchor={menuAnchor}
        onClose={() => setMenuAnchor(null)}
      />
    </>
  );
}

const styles = StyleSheet.create({
  pressed: { opacity: 0.82 },
  selectionToolbar: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
  },
  selectionToolbarInverted: { borderBottomColor: "rgba(255,255,255,0.24)" },
  selectionHint: {
    flex: 1,
    minWidth: 0,
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  selectionHintText: {
    flexShrink: 1,
    color: colors.accentDark,
    fontSize: 12,
    lineHeight: 17,
    fontWeight: "600",
  },
  selectionTextInverted: { color: colors.white },
  selectionAction: {
    width: 48,
    height: 48,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 24,
  },
  selectionActionPressed: { backgroundColor: colors.pressed },
});
