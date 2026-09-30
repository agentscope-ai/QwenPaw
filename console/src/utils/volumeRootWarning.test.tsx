/**
 * confirmVolumeRootProjectDir warns that the picked project directory is
 * a volume root, where the sandbox cannot grant access without risking
 * the whole volume. It is a warning, not a hard block.
 */
import type { TFunction } from "i18next";
import { describe, it, expect, vi, beforeEach } from "vitest";

interface ConfirmOptions {
  title: string;
  content: unknown;
  okText: string;
  cancelText: string;
  onOk: () => void;
  onCancel: () => void;
  afterClose: () => void;
}

const confirmMock = vi.fn<(opts: ConfirmOptions) => void>();
vi.mock("@agentscope-ai/design", () => ({
  Modal: {
    confirm: (...args: [ConfirmOptions]) => confirmMock(...args),
  },
}));

import { confirmVolumeRootProjectDir } from "./volumeRootWarning";

const t = ((key: string, opts?: { path?: string }) =>
  opts?.path ? `${key}:${opts.path}` : key) as unknown as TFunction;

describe("confirmVolumeRootProjectDir", () => {
  beforeEach(() => {
    confirmMock.mockClear();
  });

  it("asks before continuing and resolves true on confirm", async () => {
    confirmMock.mockImplementation((opts) => {
      opts.onOk();
    });
    await expect(
      confirmVolumeRootProjectDir({ path: "C:\\", t }),
    ).resolves.toBe(true);
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(confirmMock.mock.calls[0][0].title).toBe(
      "projectDirectory.volumeRootWarningTitle",
    );
  });

  it("passes the picked path into the message", async () => {
    confirmMock.mockImplementation((opts) => {
      opts.onOk();
    });
    await confirmVolumeRootProjectDir({ path: "E:\\", t });
    expect(confirmMock.mock.calls[0][0].content).toBe(
      "projectDirectory.volumeRootWarningMessage:E:\\",
    );
  });

  it("resolves false when the user cancels", async () => {
    confirmMock.mockImplementation((opts) => {
      opts.onCancel();
    });
    await expect(
      confirmVolumeRootProjectDir({ path: "C:\\", t }),
    ).resolves.toBe(false);
  });

  it("resolves false when the modal closes without a decision", async () => {
    confirmMock.mockImplementation((opts) => {
      opts.afterClose();
    });
    await expect(
      confirmVolumeRootProjectDir({ path: "C:\\", t }),
    ).resolves.toBe(false);
  });

  it("settles only once even if cancel and afterClose both fire", async () => {
    confirmMock.mockImplementation((opts) => {
      opts.onCancel();
      opts.afterClose();
    });
    await expect(
      confirmVolumeRootProjectDir({ path: "C:\\", t }),
    ).resolves.toBe(false);
  });
});
