import { Modal } from "antd";
import i18n from "../i18n";

/** Retry a busy operation only after explicit consent to interrupt its tasks. */
export async function requestWithPluginBusyConfirmation(
  request: (interruptTasks: boolean) => Promise<Response>,
  action: "update" | "uninstall",
): Promise<Response> {
  const response = await request(false);
  if (response.status !== 409) return response;
  const payload = await response
    .clone()
    .json()
    .catch(() => null);
  if (
    payload?.detail?.code !== "plugin_busy" ||
    payload.detail.can_interrupt !== true
  ) {
    return response;
  }
  const confirmed = await new Promise<boolean>((resolve) => {
    Modal.confirm({
      title: i18n.t("pluginManager.busyTitle"),
      content: i18n.t(`pluginManager.busy.${action}.warning`),
      okText: i18n.t(`pluginManager.busy.${action}.confirm`),
      cancelText: i18n.t(`pluginManager.busy.${action}.cancel`),
      okType: "danger",
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
      afterClose: () => resolve(false),
    });
  });
  return confirmed ? request(true) : response;
}
