import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  acceptFileBaselineAlert,
  markFileBaselineInboxReadByAlertId,
  restoreFileBaselineAlert,
  FILE_BASELINE_CONFIRM_ACCEPT,
  FILE_BASELINE_CONFIRM_RESTORE,
} from "./alertActions";
import { INBOX_CHANGED_EVENT } from "@extension/shared/inbox/inboxEvents";

const mockRestore = vi.fn();
const mockAccept = vi.fn();
const mockGetInboxEvents = vi.fn();
const mockMarkInboxRead = vi.fn();

vi.mock("@/api", () => ({
  default: {
    restoreFileBaselineProtectionAlert: (...args: unknown[]) => mockRestore(...args),
    acceptFileBaselineProtectionAlert: (...args: unknown[]) => mockAccept(...args),
    getInboxEvents: (...args: unknown[]) => mockGetInboxEvents(...args),
    markInboxRead: (...args: unknown[]) => mockMarkInboxRead(...args),
  },
}));

describe("personaAlertActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRestore.mockResolvedValue({ confirmed: true });
    mockAccept.mockResolvedValue({ confirmed: true });
    mockMarkInboxRead.mockResolvedValue({ updated: 1 });
  });

  it("restoreFileBaselineAlert marks inbox read and dispatches inbox changed", async () => {
    const listener = vi.fn();
    window.addEventListener(INBOX_CHANGED_EVENT, listener);

    const ok = await restoreFileBaselineAlert("alert-1", "evt-1");

    expect(ok).toBe(true);
    expect(mockRestore).toHaveBeenCalledWith("alert-1", FILE_BASELINE_CONFIRM_RESTORE);
    expect(mockMarkInboxRead).toHaveBeenCalledWith({ event_ids: ["evt-1"] });
    expect(listener).toHaveBeenCalled();

    window.removeEventListener(INBOX_CHANGED_EVENT, listener);
  });

  it("acceptFileBaselineAlert resolves unread inbox event by alert id", async () => {
    mockGetInboxEvents.mockResolvedValue({
      events: [
        {
          id: "evt-2",
          source_id: "alert-2",
          event_type: "file_baseline_drift",
          read: false,
        },
      ],
    });

    const ok = await acceptFileBaselineAlert("alert-2");

    expect(ok).toBe(true);
    expect(mockAccept).toHaveBeenCalledWith("alert-2", FILE_BASELINE_CONFIRM_ACCEPT);
    expect(mockMarkInboxRead).toHaveBeenCalledWith({ event_ids: ["evt-2"] });
  });

  it("markFileBaselineInboxReadByAlertId no-ops when no matching event", async () => {
    mockGetInboxEvents.mockResolvedValue({ events: [] });
    await markFileBaselineInboxReadByAlertId("missing");
    expect(mockMarkInboxRead).not.toHaveBeenCalled();
  });
});
