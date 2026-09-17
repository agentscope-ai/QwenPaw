import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";
import { sharedAppsApi } from "./sharedApps";

describe("sharedAppsApi", () => {
  beforeEach(() => vi.mocked(request).mockResolvedValue({}));
  afterEach(() => vi.clearAllMocks());

  it("creates an app from a server-known Agent id", async () => {
    await sharedAppsApi.create("owner agent");
    expect(request).toHaveBeenCalledWith("/shared-apps", {
      method: "POST",
      body: JSON.stringify({ agent_id: "owner agent" }),
    });
  });

  it("submits exactly the saved draft revision", async () => {
    await sharedAppsApi.submit("app/id", 3);
    expect(request).toHaveBeenCalledWith("/shared-apps/app%2Fid/submissions", {
      method: "POST",
      body: JSON.stringify({ draft_revision: 3 }),
    });
  });

  it("starts a private version-bound conversation", async () => {
    await sharedAppsApi.start("app/id");
    expect(request).toHaveBeenCalledWith(
      "/shared-app-catalog/app%2Fid/conversations",
      { method: "POST" },
    );
  });

  it("sends optimistic pointer state when rolling back", async () => {
    await sharedAppsApi.rollback("app", "old", "current");
    expect(request).toHaveBeenCalledWith("/admin/shared-apps/app/rollback", {
      method: "POST",
      body: JSON.stringify({
        publication_id: "old",
        expected_current_id: "current",
      }),
    });
  });
});
