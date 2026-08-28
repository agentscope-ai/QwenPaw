import { CircleAlert } from "lucide-react-native";
import { useEffect, useState } from "react";
import type { AlertButton, AlertOptions } from "react-native";
import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { colors, radius, spacing } from "../theme/tokens";
import { MobileBottomSheet } from "./MobileBottomSheet";

interface MobileAlertRequest {
  buttons: AlertButton[];
  id: number;
  message?: string;
  title: string;
}

type Listener = (request: MobileAlertRequest | null) => void;

let currentRequest: MobileAlertRequest | null = null;
let listener: Listener | null = null;
let requestId = 0;

function clearCurrentRequest() {
  currentRequest = null;
}

export const MobileAlert = {
  alert(
    title: string,
    message?: string,
    buttons?: AlertButton[],
    _options?: AlertOptions,
  ) {
    currentRequest = {
      buttons: buttons?.length ? buttons : [{ text: "知道了" }],
      id: requestId += 1,
      message,
      title,
    };
    listener?.(currentRequest);
  },
};

export function MobileAlertHost() {
  const [request, setRequest] = useState<MobileAlertRequest | null>(
    currentRequest,
  );

  useEffect(() => {
    listener = setRequest;
    return () => {
      listener = null;
    };
  }, []);

  const close = (invokeCancel: boolean) => {
    const cancel = invokeCancel
      ? request?.buttons.find((button) => button.style === "cancel")
      : undefined;
    clearCurrentRequest();
    setRequest(null);
    cancel?.onPress?.();
  };
  const buttons = request
    ? [
        ...request.buttons.filter((button) => button.style !== "cancel"),
        ...request.buttons.filter((button) => button.style === "cancel"),
      ]
    : [];

  return (
    <MobileBottomSheet
      onClose={() => close(true)}
      subtitle={request?.message}
      title={request?.title ?? ""}
      visible={Boolean(request)}
    >
      {request ? (
        <ScrollView
          contentContainerStyle={styles.actions}
          showsVerticalScrollIndicator={false}
          style={styles.scroll}
        >
          {buttons.map((button, index) => {
            const danger = button.style === "destructive";
            const cancel = button.style === "cancel";
            return (
              <Pressable
                accessibilityRole="button"
                key={`${request.id}-${button.text ?? index}`}
                onPress={() => {
                  close(false);
                  button.onPress?.();
                }}
                style={({ pressed }) => [
                  styles.action,
                  cancel && styles.cancel,
                  pressed && styles.pressed,
                ]}
              >
                {danger ? <CircleAlert color={colors.danger} size={19} /> : null}
                <Text
                  maxFontSizeMultiplier={1.35}
                  style={[
                    styles.label,
                    danger && styles.dangerLabel,
                    cancel && styles.cancelLabel,
                  ]}
                >
                  {button.text ?? "确定"}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : null}
    </MobileBottomSheet>
  );
}

const styles = StyleSheet.create({
  actions: { gap: spacing.xs },
  scroll: { maxHeight: 460 },
  action: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  cancel: { marginTop: spacing.xs, backgroundColor: colors.surfaceSoft },
  pressed: { backgroundColor: colors.pressed },
  label: { color: colors.ink, fontSize: 15, fontWeight: "600" },
  dangerLabel: { color: colors.danger },
  cancelLabel: { color: colors.muted },
});
