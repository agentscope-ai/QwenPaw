/**
 * useSessions.archive.test.ts - archive family coverage for
 * pages/Control/Sessions/useSessions.ts.
 *
 * Division of labour with the existing useSessions.test.ts (left byte-for-byte
 * untouched): that file covers initial loading, listChats wiring, and the
 * update / delete / batchDelete triplets. This file covers the four archive
 * capabilities it does not reach at all - archiveSession, unarchiveSession,
 * batchArchiveSessions, batchUnarchiveSessions - plus the two fetch paths that
 * the existing cases never drive: listChats rejecting, and listChats resolving
 * to a falsy payload.
 *
 * Assertions stay on observable behaviour: the returned boolean, the session
 * list the caller sees afterwards, which toast is raised, and which i18n key
 * (with which fallback) is asked for. The batch capabilities re-fetch after
 * the backend call, so their assertions pin that second listChats round trip
 * rather than a locally patched list.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import { useSessions } from "./useSessions";

const mockMessage = { success: vi.fn(), error: vi.fn() };
const tSpy = vi.fn((key: string) => key);

vi.mock("../../../api", () => ({
  default: {
    updateSession: vi.fn(),
    deleteSession: vi.fn(),
    batchDeleteSessions: vi.fn(),
  },
}));
vi.mock("../../../api/modules/chat", () => ({
  chatApi: {
    listChats: vi.fn(),
    archiveChat: vi.fn(),
    unarchiveChat: vi.fn(),
    batchArchiveChats: vi.fn(),
    batchUnarchiveChats: vi.fn(),
  },
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: vi.fn(() => ({ selectedAgent: "agent-1" })),
}));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: vi.fn(() => ({ message: mockMessage })),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tSpy }),
}));

import { chatApi } from "../../../api/modules/chat";

const mockedListChats = chatApi.listChats as ReturnType<typeof vi.fn>;
const mockedArchiveChat = chatApi.archiveChat as ReturnType<typeof vi.fn>;
const mockedUnarchiveChat = chatApi.unarchiveChat as ReturnType<typeof vi.fn>;
const mockedBatchArchive = chatApi.batchArchiveChats as ReturnType<
  typeof vi.fn
>;
const mockedBatchUnarchive = chatApi.batchUnarchiveChats as ReturnType<
  typeof vi.fn
>;

type Row = { id: string; name: string; archived?: boolean };

const seed: Row[] = [
  { id: "s1", name: "First", archived: false },
  { id: "s2", name: "Second", archived: false },
  { id: "s3", name: "Old", archived: true },
];

/** Render the hook and wait for the initial catalogue to arrive. */
async function renderLoaded(rows: Row[] = seed) {
  mockedListChats.mockResolvedValue(rows);
  const view = renderHook(() => useSessions());
  await waitFor(() => expect(view.result.current.loading).toBe(false));
  return view;
}

let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.clearAllMocks();
  tSpy.mockImplementation((key: string) => key);
  mockedListChats.mockResolvedValue(seed);
  consoleErrorSpy = vi
    .spyOn(console, "error")
    .mockImplementation(() => undefined);
});

afterEach(() => {
  consoleErrorSpy.mockRestore();
});

describe("useSessions fetchSessions resilience", () => {
  it("reports the failure and stops loading when listChats rejects", async () => {
    mockedListChats.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useSessions());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Failed to load sessions:",
      expect.any(Error),
    );
    // The catalogue stays empty instead of holding a stale value.
    expect(result.current.sessions).toEqual([]);
    expect(result.current.activeCount).toBe(0);
    expect(result.current.archivedCount).toBe(0);
  });

  it("keeps the previous catalogue when listChats resolves to null", async () => {
    const { result } = await renderLoaded();
    expect(result.current.activeCount).toBe(2);

    mockedListChats.mockResolvedValue(null);
    await act(async () => {
      await result.current.batchArchiveSessions(["s1"]);
    });

    // A falsy payload must not wipe the list the user is looking at.
    expect(result.current.sessions.map((s) => s.id)).toEqual(["s1", "s2"]);
  });
});

describe("useSessions archiveSession", () => {
  it("swaps in the archived row returned by the backend", async () => {
    const { result } = await renderLoaded();
    mockedArchiveChat.mockResolvedValue({
      id: "s1",
      name: "First",
      archived: true,
    });

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.archiveSession("s1");
    });

    expect(returned).toBe(true);
    expect(mockedArchiveChat).toHaveBeenCalledWith("s1");
    // The active tab only lists unarchived rows, so the archived one leaves it
    // and shows up in the archived tab carrying the backend's own row.
    expect(result.current.sessions).toEqual([
      { id: "s2", name: "Second", archived: false },
    ]);
    expect(result.current.activeCount).toBe(1);
    expect(result.current.archivedCount).toBe(2);
    act(() => result.current.setActiveTab("archived"));
    expect(result.current.sessions).toEqual([
      { id: "s1", name: "First", archived: true },
      { id: "s3", name: "Old", archived: true },
    ]);
    expect(mockMessage.success).toHaveBeenCalledWith(
      "sessions.archive.successHint",
    );
    expect(mockMessage.error).not.toHaveBeenCalled();
  });

  it("leaves the catalogue untouched and raises an error toast on failure", async () => {
    const { result } = await renderLoaded();
    mockedArchiveChat.mockRejectedValue(new Error("archive failed"));

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.archiveSession("s1");
    });

    expect(returned).toBe(false);
    expect(result.current.sessions).toEqual([
      { id: "s1", name: "First", archived: false },
      { id: "s2", name: "Second", archived: false },
    ]);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Failed to archive session:",
      expect.any(Error),
    );
    // The failure toast asks for the key together with its English fallback.
    expect(tSpy).toHaveBeenCalledWith(
      "sessions.archive.failed",
      "Failed to archive",
    );
    expect(mockMessage.error).toHaveBeenCalledWith("sessions.archive.failed");
    expect(mockMessage.success).not.toHaveBeenCalled();
  });

  it("does not disturb rows other than the one being archived", async () => {
    const { result } = await renderLoaded();
    mockedArchiveChat.mockResolvedValue({
      id: "s2",
      name: "Second",
      archived: true,
    });

    await act(async () => {
      await result.current.archiveSession("s2");
    });

    expect(result.current.sessions[0]).toEqual(seed[0]);
  });
});

describe("useSessions unarchiveSession", () => {
  it("moves a row back into the active tab", async () => {
    const { result } = await renderLoaded();
    act(() => result.current.setActiveTab("archived"));
    expect(result.current.sessions.map((s) => s.id)).toEqual(["s3"]);

    mockedUnarchiveChat.mockResolvedValue({
      id: "s3",
      name: "Old",
      archived: false,
    });

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.unarchiveSession("s3");
    });

    expect(returned).toBe(true);
    expect(mockedUnarchiveChat).toHaveBeenCalledWith("s3");
    expect(result.current.sessions).toEqual([]);
    expect(result.current.activeCount).toBe(3);
    expect(tSpy).toHaveBeenCalledWith(
      "sessions.archive.unarchiveSuccess",
      "Chat unarchived",
    );
    expect(mockMessage.success).toHaveBeenCalledWith(
      "sessions.archive.unarchiveSuccess",
    );
  });

  it("keeps the row archived and raises an error toast on failure", async () => {
    const { result } = await renderLoaded();
    act(() => result.current.setActiveTab("archived"));
    mockedUnarchiveChat.mockRejectedValue(new Error("nope"));

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.unarchiveSession("s3");
    });

    expect(returned).toBe(false);
    expect(result.current.sessions.map((s) => s.id)).toEqual(["s3"]);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Failed to unarchive session:",
      expect.any(Error),
    );
    expect(tSpy).toHaveBeenCalledWith(
      "sessions.archive.unarchiveFailed",
      "Failed to unarchive",
    );
    expect(mockMessage.error).toHaveBeenCalledWith(
      "sessions.archive.unarchiveFailed",
    );
  });
});

describe("useSessions batchArchiveSessions", () => {
  it("re-reads the catalogue and counts the archived rows in the toast", async () => {
    const { result } = await renderLoaded();
    mockedBatchArchive.mockResolvedValue(undefined);
    const refetched: Row[] = [
      { id: "s1", name: "First", archived: true },
      { id: "s2", name: "Second", archived: true },
      { id: "s3", name: "Old", archived: true },
    ];
    // The initial load already happened, so this value serves the re-fetch.
    mockedListChats.mockResolvedValue(refetched);

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.batchArchiveSessions(["s1", "s2"]);
    });

    expect(returned).toBe(true);
    expect(mockedBatchArchive).toHaveBeenCalledWith(["s1", "s2"]);
    // The batch path re-fetches instead of patching rows locally.
    expect(mockedListChats).toHaveBeenCalledTimes(2);
    expect(result.current.sessions).toEqual([]);
    expect(result.current.archivedCount).toBe(3);
    expect(tSpy).toHaveBeenCalledWith("sessions.archive.batchSuccess", {
      count: 2,
      defaultValue: "{{count}} chats archived",
    });
    expect(mockMessage.success).toHaveBeenCalledWith(
      "sessions.archive.batchSuccess",
    );
  });

  it("leaves the catalogue as fetched and raises an error toast on failure", async () => {
    const { result } = await renderLoaded();
    mockedBatchArchive.mockRejectedValue(new Error("batch failed"));

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.batchArchiveSessions(["s1", "s2"]);
    });

    expect(returned).toBe(false);
    expect(mockedListChats).toHaveBeenCalledTimes(1);
    expect(result.current.sessions.map((s) => s.id)).toEqual(["s1", "s2"]);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Failed to batch archive sessions:",
      expect.any(Error),
    );
    expect(tSpy).toHaveBeenCalledWith(
      "sessions.archive.batchFailed",
      "Failed to batch archive",
    );
    expect(mockMessage.error).toHaveBeenCalledWith(
      "sessions.archive.batchFailed",
    );
  });

  it("reports a count of zero when asked to archive an empty selection", async () => {
    const { result } = await renderLoaded();
    mockedBatchArchive.mockResolvedValue(undefined);

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.batchArchiveSessions([]);
    });

    expect(returned).toBe(true);
    expect(mockedBatchArchive).toHaveBeenCalledWith([]);
    expect(tSpy).toHaveBeenCalledWith("sessions.archive.batchSuccess", {
      count: 0,
      defaultValue: "{{count}} chats archived",
    });
  });
});

describe("useSessions batchUnarchiveSessions", () => {
  it("re-reads the catalogue and counts the restored rows in the toast", async () => {
    const { result } = await renderLoaded();
    act(() => result.current.setActiveTab("archived"));
    mockedBatchUnarchive.mockResolvedValue(undefined);
    const refetched: Row[] = [
      { id: "s1", name: "First", archived: false },
      { id: "s2", name: "Second", archived: false },
      { id: "s3", name: "Old", archived: false },
    ];
    // The initial load already happened, so this value serves the re-fetch.
    mockedListChats.mockResolvedValue(refetched);

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.batchUnarchiveSessions(["s3"]);
    });

    expect(returned).toBe(true);
    expect(mockedBatchUnarchive).toHaveBeenCalledWith(["s3"]);
    expect(mockedListChats).toHaveBeenCalledTimes(2);
    // The caller is still on the archived tab, which the re-fetch emptied.
    expect(result.current.sessions).toEqual([]);
    expect(result.current.archivedCount).toBe(0);
    expect(result.current.activeCount).toBe(3);
    act(() => result.current.setActiveTab("active"));
    expect(result.current.sessions.map((s) => s.id)).toEqual([
      "s1",
      "s2",
      "s3",
    ]);
    expect(tSpy).toHaveBeenCalledWith(
      "sessions.archive.batchUnarchiveSuccess",
      {
        count: 1,
        defaultValue: "{{count}} chats unarchived",
      },
    );
    expect(mockMessage.success).toHaveBeenCalledWith(
      "sessions.archive.batchUnarchiveSuccess",
    );
  });

  it("raises an error toast and skips the re-read on failure", async () => {
    const { result } = await renderLoaded();
    act(() => result.current.setActiveTab("archived"));
    mockedBatchUnarchive.mockRejectedValue(new Error("batch failed"));

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.batchUnarchiveSessions(["s3"]);
    });

    expect(returned).toBe(false);
    expect(mockedListChats).toHaveBeenCalledTimes(1);
    expect(result.current.sessions.map((s) => s.id)).toEqual(["s3"]);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Failed to batch unarchive sessions:",
      expect.any(Error),
    );
    expect(tSpy).toHaveBeenCalledWith(
      "sessions.archive.batchUnarchiveFailed",
      "Failed to batch unarchive",
    );
    expect(mockMessage.error).toHaveBeenCalledWith(
      "sessions.archive.batchUnarchiveFailed",
    );
  });

  it("reports a count of zero when asked to restore an empty selection", async () => {
    const { result } = await renderLoaded();
    mockedBatchUnarchive.mockResolvedValue(undefined);

    let returned: boolean | undefined;
    await act(async () => {
      returned = await result.current.batchUnarchiveSessions([]);
    });

    expect(returned).toBe(true);
    expect(tSpy).toHaveBeenCalledWith(
      "sessions.archive.batchUnarchiveSuccess",
      {
        count: 0,
        defaultValue: "{{count}} chats unarchived",
      },
    );
  });
});
