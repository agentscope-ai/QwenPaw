// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { MailProcessingPauses } from "./MailProcessingPauses";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  resume: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("../../../api/modules/mailAccessControl", () => ({
  mailAccessControlApi: {
    getMailProcessingPauses: (...args: unknown[]) => mocks.list(...args),
    resumeMailProcessing: (...args: unknown[]) => mocks.resume(...args),
  },
}));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: mocks.success, error: mocks.error },
  }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: unknown) =>
      params ? `${key}:${JSON.stringify(params)}` : key,
  }),
}));

const batch = {
  agent_id: "acl-disabled-agent",
  pause_id: "batch-1",
  reason: "batch",
  count: 1033,
};

describe("MailProcessingPauses", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue([batch]);
    mocks.resume.mockResolvedValue({ status: "ok" });
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows live pauses without inbox events or ACL, and cancel keeps paused", async () => {
    renderWithProviders(<MailProcessingPauses />);
    const review = await screen.findByRole("button", {
      name: "inbox.mailProcessingReview",
    });
    expect(
      screen.getByText(/inbox.mailProcessingReason_batch.*1033/),
    ).toBeTruthy();
    expect(mocks.resume).not.toHaveBeenCalled();
    fireEvent.click(review);
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(/inbox.mailProcessingBatchConfirm.*1033/),
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "inbox.mailProcessingKeepPaused",
      }),
    );
    expect(mocks.resume).not.toHaveBeenCalled();
    expect(
      screen.getByText(/inbox.mailProcessingReason_batch.*1033/),
    ).toBeTruthy();
  });

  it("confirms the displayed batch once, disabling duplicate submits", async () => {
    let finish: (() => void) | undefined;
    mocks.resume.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    renderWithProviders(<MailProcessingPauses />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "inbox.mailProcessingReview",
      }),
    );
    const confirm = within(screen.getByRole("dialog")).getByRole("button", {
      name: /inbox.mailProcessingConfirmBatch.*1033/,
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(mocks.resume).toHaveBeenCalledExactlyOnceWith(
      "acl-disabled-agent",
      "batch-1",
    );
    mocks.list.mockResolvedValue([]);
    finish?.();
    await waitFor(() => expect(mocks.success).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText(/inbox.mailProcessingReason_batch/)).toBeNull(),
    );
  });

  it("refreshes a stale confirmation without automatically releasing the new pause", async () => {
    mocks.resume.mockRejectedValue(new Error("409 stale pause"));
    renderWithProviders(<MailProcessingPauses />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "inbox.mailProcessingReview",
      }),
    );
    mocks.list.mockResolvedValue([
      { ...batch, pause_id: "batch-2", count: 80 },
    ]);
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: /inbox.mailProcessingConfirmBatch/,
      }),
    );
    await waitFor(() =>
      expect(mocks.error).toHaveBeenCalledWith(
        "inbox.mailProcessingResumeFailed",
      ),
    );
    await screen.findByText(/inbox.mailProcessingReason_batch.*80/);
    expect(mocks.resume).toHaveBeenCalledExactlyOnceWith(
      "acl-disabled-agent",
      "batch-1",
    );
  });

  it("requires an explicit resume after repeated failures", async () => {
    mocks.list.mockResolvedValue([{ ...batch, reason: "failures", count: 3 }]);
    renderWithProviders(<MailProcessingPauses />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "inbox.mailProcessingReview",
      }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(/inbox.mailProcessingResumeConfirm/),
    ).toBeTruthy();
    expect(
      within(dialog).getByRole("button", {
        name: /inbox.mailProcessingConfirmResume/,
      }),
    ).toBeTruthy();
    expect(mocks.resume).not.toHaveBeenCalled();
  });

  it("makes polling failure observable and refreshes without resuming", async () => {
    mocks.list.mockRejectedValueOnce(new Error("offline"));
    renderWithProviders(<MailProcessingPauses />);
    const retry = await screen.findByRole("button", { name: "common.retry" });
    expect(screen.getByText("inbox.mailProcessingLoadFailed")).toBeTruthy();
    fireEvent.click(retry);
    await screen.findByText(/inbox.mailProcessingReason_batch.*1033/);
    expect(mocks.resume).not.toHaveBeenCalled();
  });

  it("stops polling while hidden and refreshes when visible again", async () => {
    vi.useFakeTimers();
    const visibility = vi.spyOn(document, "visibilityState", "get");
    visibility.mockReturnValue("visible");
    await act(async () => {
      renderWithProviders(<MailProcessingPauses />);
    });
    expect(mocks.list).toHaveBeenCalledTimes(1);
    visibility.mockReturnValue("hidden");
    await act(async () => vi.advanceTimersByTimeAsync(18000));
    expect(mocks.list).toHaveBeenCalledTimes(1);
    visibility.mockReturnValue("visible");
    await act(async () => {
      window.dispatchEvent(new Event("visibilitychange"));
    });
    expect(mocks.list).toHaveBeenCalledTimes(2);
    expect(mocks.resume).not.toHaveBeenCalled();
  });
});
