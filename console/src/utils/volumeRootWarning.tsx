import { Modal } from "@agentscope-ai/design";
import type { TFunction } from "i18next";

interface ConfirmVolumeRootOptions {
  /** The directory the user picked, which is a volume root. */
  path: string;
  t: TFunction;
}

/**
 * Warns that the picked project directory is a volume root.
 *
 * The sandbox cannot grant access there: the ACE it writes is
 * inheritable and a volume root has no parent, so the write would
 * re-propagate across the whole volume and can leave the drive
 * inaccessible. The backend therefore runs such a session without the
 * sandbox (see #7943). This is a warning, not a hard block: the command
 * still has to run.
 *
 * @returns true when the user chooses to continue anyway.
 */
export function confirmVolumeRootProjectDir({
  path,
  t,
}: ConfirmVolumeRootOptions): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    let settled = false;

    const settle = (value: boolean): void => {
      if (settled) return;
      settled = true;
      resolve(value);
    };

    Modal.confirm({
      title: t("projectDirectory.volumeRootWarningTitle"),
      content: t("projectDirectory.volumeRootWarningMessage", { path }),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      onOk: () => settle(true),
      onCancel: () => settle(false),
      afterClose: () => settle(false),
    });
  });
}
