import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { message, Modal } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StorageReclaimNotice from "../StorageReclaimNotice";
import { confirmProjectReclaim } from "@/api/creator";

vi.mock("@/api/creator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/creator")>();
  return { ...actual, confirmProjectReclaim: vi.fn() };
});

const mockedReclaim = vi.mocked(confirmProjectReclaim);

describe("StorageReclaimNotice", () => {
  beforeEach(() => {
    mockedReclaim.mockReset();
    // antd caches its message holder node; emptying <body> would leave the
    // next message appended to a detached element. Imperative confirm modals
    // are portals outside the rendered tree, so cleanup cannot remove them.
    message.destroy();
    Modal.destroyAll();
    // destroyAll() unmounts instances but leaves closing portals in the DOM
    // until their animation ticks; a leftover OK button would swallow the
    // next case's click, so purge the nodes outright.
    document
      .querySelectorAll(".ant-modal-root, .ant-message")
      .forEach((node) => node.remove());
  });

  it("names the waiting bytes and offers the one press", () => {
    render(
      <StorageReclaimNotice
        projectId="project-a"
        projectName="被逐出宗门那天"
        pendingBytes={5 * 1024 * 1024 * 1024}
        onConfirmed={() => {}}
      />,
    );

    expect(
      document.querySelector("[data-storage-reclaim-notice]"),
    ).not.toBeNull();
    expect(
      screen.getByText("已有 5.0 GB 沉淀历史等待你确认"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "确认并释放" }),
    ).toBeInTheDocument();
  });

  it("records the confirmation and reports what the sweep freed", async () => {
    const result = {
      projectId: "project-a",
      historyKept: false,
      removedTransactions: 12,
      transactionBytes: 1024,
      releasedFiles: 3,
      releasedBytes: 2048,
      confirmedAt: "2026-11-03T00:00:00+00:00",
    };
    let finish!: (value: typeof result) => void;
    mockedReclaim.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const onConfirmed = vi.fn();
    const { container } = render(
      <StorageReclaimNotice
        projectId="project-a"
        projectName="被逐出宗门那天"
        pendingBytes={5 * 1024 * 1024 * 1024}
        onConfirmed={onConfirmed}
      />,
    );

    // Query inside the rendered notice: a modal portal left closing by an
    // earlier case repeats the same label in document order.
    fireEvent.click(
      container.querySelector("[data-storage-reclaim-notice] button")!,
    );
    // The newest modal root owns the OK button; a portal left closing by an
    // earlier case still repeats the label in role order.
    const okButton = await waitFor(() => {
      const modals = Array.from(document.querySelectorAll(".ant-modal"));
      expect(modals.length).toBeGreaterThan(0);
      const ok = (modals[modals.length - 1] as HTMLElement).querySelector(
        ".ant-btn-primary",
      ) as HTMLElement | null;
      expect(ok).not.toBeNull();
      return ok as HTMLElement;
    });
    fireEvent.click(okButton);

    await waitFor(() =>
      expect(mockedReclaim).toHaveBeenCalledWith("project-a"),
    );
    expect(onConfirmed).not.toHaveBeenCalled();
    expect(container.querySelector("[data-storage-reclaim-notice] button")).toBeDisabled();
    finish(result);
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText("已释放 3.0 KB 沉淀历史"),
    ).toBeInTheDocument();
  });

  it("leaves reclaim available when the request fails", async () => {
    mockedReclaim.mockRejectedValue(new Error("boom"));
    // The static antd holder races Modal.destroyAll() plus the now-immediate
    // modal close, so pin the call rather than the rendered bubble.
    const errorSpy = vi.spyOn(message, "error");
    const onConfirmed = vi.fn();
    const { container } = render(
      <StorageReclaimNotice
        projectId="project-a"
        projectName="被逐出宗门那天"
        pendingBytes={5 * 1024 * 1024 * 1024}
        onConfirmed={onConfirmed}
      />,
    );

    // Query inside the rendered notice: a modal portal left closing by an
    // earlier case repeats the same label in document order.
    fireEvent.click(
      container.querySelector("[data-storage-reclaim-notice] button")!,
    );
    // The newest modal root owns the OK button; a portal left closing by an
    // earlier case still repeats the label in role order.
    const okButton = await waitFor(() => {
      const modals = Array.from(document.querySelectorAll(".ant-modal"));
      expect(modals.length).toBeGreaterThan(0);
      const ok = (modals[modals.length - 1] as HTMLElement).querySelector(
        ".ant-btn-primary",
      ) as HTMLElement | null;
      expect(ok).not.toBeNull();
      return ok as HTMLElement;
    });
    fireEvent.click(okButton);

    await waitFor(() => expect(mockedReclaim).toHaveBeenCalled());
    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    expect(String(errorSpy.mock.calls[0][0])).toMatch(/无法释放沉淀历史/);
    await waitFor(() =>
      expect(
        document.querySelector("[data-storage-reclaim-notice]"),
      ).not.toBeNull(),
    );
    expect(onConfirmed).not.toHaveBeenCalled();
  });
});
