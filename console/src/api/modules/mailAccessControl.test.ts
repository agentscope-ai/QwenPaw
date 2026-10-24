import { beforeEach, describe, expect, it, vi } from "vitest";
import { mailAccessControlApi } from "./mailAccessControl";
import { request } from "../request";

vi.mock("../request", () => ({ request: vi.fn() }));

describe("mail processing safety API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists pauses without requiring sender access control", async () => {
    await mailAccessControlApi.getMailProcessingPauses();
    expect(request).toHaveBeenCalledWith(
      "/mail-access-control/processing-pauses",
    );
  });

  it("sends the exact displayed pause token to the selected agent", async () => {
    await mailAccessControlApi.resumeMailProcessing("agent name", "batch-1");
    expect(request).toHaveBeenCalledWith(
      "/mail-access-control/processing/agent%20name/resume",
      { method: "POST", body: JSON.stringify({ pause_id: "batch-1" }) },
    );
  });
});
