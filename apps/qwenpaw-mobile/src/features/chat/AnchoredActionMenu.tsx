import type { LucideIcon } from "lucide-react-native";
import { useEffect, useState } from "react";
import {
  AccessibilityInfo,
  Keyboard,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors, radius } from "../../theme/tokens";
import {
  type AnchorRect,
  placeAnchoredMenu,
} from "./anchoredMenuModel";

export type { AnchorRect } from "./anchoredMenuModel";

export interface AnchoredMenuAction {
  accessibilityHint?: string;
  icon: LucideIcon;
  label: string;
  onPress: () => void;
  tone?: "default" | "danger";
}

const ACTION_WIDTH = 82;
const ACTIONS_HEIGHT = 76;
const TITLE_HEIGHT = 39;
const MENU_HORIZONTAL_PADDING = 6;

export function AnchoredActionMenu({
  actions,
  anchor,
  onClose,
  title,
}: {
  actions: AnchoredMenuAction[];
  anchor: AnchorRect | null;
  onClose: () => void;
  title?: string;
}) {
  const insets = useSafeAreaInsets();
  const { height, width } = useWindowDimensions();
  const [keyboardTop, setKeyboardTop] = useState<number | null>(null);
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    void AccessibilityInfo.isReduceMotionEnabled().then(setReduceMotion);
    const motion = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      setReduceMotion,
    );
    const shown = Keyboard.addListener("keyboardDidShow", (event) => {
      setKeyboardTop(event.endCoordinates.screenY);
    });
    const hidden = Keyboard.addListener("keyboardDidHide", () => {
      setKeyboardTop(null);
    });
    return () => {
      motion.remove();
      shown.remove();
      hidden.remove();
    };
  }, []);

  if (!anchor) return null;

  const menuWidth = Math.min(
    actions.length * ACTION_WIDTH + MENU_HORIZONTAL_PADDING * 2,
    width - 24,
  );
  const menuHeight = ACTIONS_HEIGHT + (title ? TITLE_HEIGHT : 0);
  const viewportHeight = keyboardTop === null
    ? height
    : Math.min(height, keyboardTop);
  const placement = placeAnchoredMenu({
    anchor,
    bottomInset: insets.bottom,
    gap: 10,
    margin: 12,
    menuHeight,
    menuWidth,
    topInset: insets.top,
    viewportHeight,
    viewportWidth: width,
  });

  return (
    <Modal
      animationType={reduceMotion ? "none" : "fade"}
      navigationBarTranslucent
      onRequestClose={onClose}
      statusBarTranslucent
      transparent
      visible
    >
      <View
        accessibilityViewIsModal
        style={styles.root}
      >
        <Pressable
          accessibilityLabel="关闭操作菜单"
          onPress={onClose}
          style={StyleSheet.absoluteFill}
        />
        <View
          style={[
            styles.positioner,
            {
              left: placement.left,
              top: placement.top,
              width: menuWidth,
              height: menuHeight,
            },
          ]}
        >
          <View
            pointerEvents="none"
            style={[
              styles.arrow,
              placement.above ? styles.arrowBelow : styles.arrowAbove,
              { left: placement.arrowLeft },
            ]}
          />
          <View style={[styles.menu, { height: menuHeight }]}>
            {title ? (
              <Text
                maxFontSizeMultiplier={1.2}
                numberOfLines={1}
                style={styles.title}
              >
                {title}
              </Text>
            ) : null}
            <View style={styles.actionRow}>
              {actions.map((action) => {
                const Icon = action.icon;
                const danger = action.tone === "danger";
                return (
                  <Pressable
                    accessibilityHint={action.accessibilityHint}
                    accessibilityRole="button"
                    key={action.label}
                    onPress={() => {
                      onClose();
                      action.onPress();
                    }}
                    style={({ pressed }) => [
                      styles.action,
                      pressed && styles.actionPressed,
                    ]}
                  >
                    <Icon
                      accessibilityElementsHidden
                      color={danger ? colors.danger : colors.ink}
                      importantForAccessibility="no-hide-descendants"
                      size={22}
                      strokeWidth={1.8}
                    />
                    <Text
                      maxFontSizeMultiplier={1.25}
                      numberOfLines={1}
                      style={[styles.label, danger && styles.dangerLabel]}
                    >
                      {action.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  positioner: {
    position: "absolute",
  },
  menu: {
    zIndex: 2,
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceStrong,
    shadowColor: colors.black,
    shadowOffset: { width: 0, height: 7 },
    shadowOpacity: 0.2,
    shadowRadius: 18,
    elevation: 10,
  },
  title: {
    height: TITLE_HEIGHT,
    paddingHorizontal: 13,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
    color: colors.muted,
    fontSize: 12,
    lineHeight: TITLE_HEIGHT,
    fontWeight: "600",
  },
  actionRow: {
    height: ACTIONS_HEIGHT,
    flexDirection: "row",
    paddingHorizontal: MENU_HORIZONTAL_PADDING,
  },
  arrow: {
    position: "absolute",
    zIndex: 1,
    width: 12,
    height: 12,
    transform: [{ rotate: "45deg" }],
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: colors.surfaceStrong,
  },
  arrowAbove: { top: -5 },
  arrowBelow: { bottom: -5 },
  action: {
    minWidth: ACTION_WIDTH,
    minHeight: 48,
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    borderRadius: 9,
  },
  actionPressed: { backgroundColor: colors.pressed },
  label: {
    color: colors.ink,
    fontSize: 13,
    lineHeight: 18,
    fontWeight: "500",
  },
  dangerLabel: { color: colors.danger },
});
