import { vi, describe, it, expect, beforeEach } from "vitest";

vi.mock("../api/modules/language", () => ({
  settingsApi: {
    getUploadLimit: vi.fn(),
  },
}));

import { useUploadLimitStore } from "./uploadLimitStore";
import { settingsApi } from "../api/modules/language";

const mockGetUploadLimit = settingsApi.getUploadLimit as ReturnType<
  typeof vi.fn
>;

describe("uploadLimitStore", () => {
  beforeEach(() => {
    useUploadLimitStore.setState({ uploadMaxSizeMb: null });
    vi.clearAllMocks();
  });

  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  it("initial uploadMaxSizeMb is null", () => {
    expect(useUploadLimitStore.getState().uploadMaxSizeMb).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // fetch() success cases
  // ---------------------------------------------------------------------------

  it("fetch() sets uploadMaxSizeMb to the returned value (100)", async () => {
    mockGetUploadLimit.mockResolvedValueOnce({ upload_max_size_mb: 100 });
    await useUploadLimitStore.getState().fetch();
    expect(useUploadLimitStore.getState().uploadMaxSizeMb).toBe(100);
  });

  it("fetch() sets uploadMaxSizeMb to null when API returns null (unlimited)", async () => {
    mockGetUploadLimit.mockResolvedValueOnce({ upload_max_size_mb: null });
    await useUploadLimitStore.getState().fetch();
    expect(useUploadLimitStore.getState().uploadMaxSizeMb).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // fetch() failure
  // ---------------------------------------------------------------------------

  it("fetch() swallows errors and uploadMaxSizeMb remains null", async () => {
    mockGetUploadLimit.mockRejectedValueOnce(new Error("Network error"));
    await useUploadLimitStore.getState().fetch();
    expect(useUploadLimitStore.getState().uploadMaxSizeMb).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // Multiple successive fetches
  // ---------------------------------------------------------------------------

  it("uploadMaxSizeMb updates correctly across multiple successive fetches", async () => {
    mockGetUploadLimit.mockResolvedValueOnce({ upload_max_size_mb: 50 });
    await useUploadLimitStore.getState().fetch();
    expect(useUploadLimitStore.getState().uploadMaxSizeMb).toBe(50);

    mockGetUploadLimit.mockResolvedValueOnce({ upload_max_size_mb: 200 });
    await useUploadLimitStore.getState().fetch();
    expect(useUploadLimitStore.getState().uploadMaxSizeMb).toBe(200);

    mockGetUploadLimit.mockResolvedValueOnce({ upload_max_size_mb: null });
    await useUploadLimitStore.getState().fetch();
    expect(useUploadLimitStore.getState().uploadMaxSizeMb).toBeNull();
  });
});
