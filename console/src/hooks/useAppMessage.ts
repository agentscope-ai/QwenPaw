import { App } from "antd";
import { useMemo } from "react";
import { interactionErrorText } from "../utils/interactionText";

function localizeErrorContent(value: unknown): unknown {
  if (typeof value === "string") return interactionErrorText(value);
  if (value && typeof value === "object" && "content" in value) {
    return { ...value, content: localizeErrorContent(value.content) };
  }
  return value;
}

function localizeErrorConfig<
  T extends { message?: unknown; description?: unknown },
>(value: T): T {
  return {
    ...value,
    message:
      typeof value.message === "string"
        ? interactionErrorText(value.message)
        : value.message,
    description:
      typeof value.description === "string"
        ? interactionErrorText(value.description)
        : value.description,
  };
}

/**
 * Hook to get message instance from Ant Design's App component.
 * Use this instead of the static message import to ensure
 * message notifications work correctly with ConfigProvider's prefixCls.
 *
 * Usage:
 * const { message } = useAppMessage();
 * message.success('Success!');
 */
export function useAppMessage() {
  const { message, modal, notification } = App.useApp();
  return useMemo(
    () => ({
      message: {
        ...message,
        error: ((content: unknown, ...args: unknown[]) => {
          const localized = localizeErrorContent(content);
          return (message.error as (...args: unknown[]) => unknown)(
            localized,
            ...args,
          );
        }) as typeof message.error,
      },
      modal,
      notification: {
        ...notification,
        error: ((config: Parameters<typeof notification.error>[0]) =>
          notification.error(
            localizeErrorConfig(config),
          )) as typeof notification.error,
      },
    }),
    [message, modal, notification],
  );
}
