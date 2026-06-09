import { App } from "antd";

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
  return { message, modal, notification };
}
