import { App } from "antd";

/**
 * Hook to get message instance from Ant Design's App component.
 * Use this instead of the static message import to ensure
 * message notifications work correctly with ConfigProvider's prefixCls.
 *
 * When this bundle runs inside the QwenPaw host, antd is bundled separately
 * from the host's App provider — prefer `window.QwenPaw.host.antd` so toasts
 * actually render (same approach as datapaw/ui task-graph patches).
 *
 * Usage:
 * const { message } = useAppMessage();
 * message.success('Success!');
 */
export function useAppMessage() {
  const appApis = App.useApp();
  const hostAntd =
    typeof window !== "undefined"
      ? (window as Window & { QwenPaw?: { host?: { antd?: {
            message?: typeof appApis.message;
            Modal?: typeof appApis.modal;
            notification?: typeof appApis.notification;
          } } } }).QwenPaw?.host?.antd
      : undefined;

  if (hostAntd?.message) {
    return {
      message: hostAntd.message,
      modal: hostAntd.Modal ?? appApis.modal,
      notification: hostAntd.notification ?? appApis.notification,
    };
  }

  return appApis;
}
