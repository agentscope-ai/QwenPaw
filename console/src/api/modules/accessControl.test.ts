import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { accessControlApi } from "./accessControl";
import { request } from "../request";

describe("accessControlApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getAclAll calls GET /access-control", async () => {
    const data = { chan: { whitelist: {}, blacklist: {}, pending: [] } };
    vi.mocked(request).mockResolvedValue(data);
    const result = await accessControlApi.getAclAll();
    expect(request).toHaveBeenCalledWith("/access-control");
    expect(result).toEqual(data);
  });

  it("getAclChannel calls GET /access-control/:channel", async () => {
    await accessControlApi.getAclChannel("dingtalk");
    expect(request).toHaveBeenCalledWith("/access-control/dingtalk");
  });

  it("addAclWhitelist sends POST with entries body", async () => {
    const entries = [{ channel: "chan", user_id: "u1", remark: "r" }];
    await accessControlApi.addAclWhitelist(entries);
    expect(request).toHaveBeenCalledWith("/access-control/whitelist/add", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
  });

  it("removeAclWhitelist sends POST with entries body", async () => {
    const entries = [{ channel: "chan", user_id: "u1" }];
    await accessControlApi.removeAclWhitelist(entries);
    expect(request).toHaveBeenCalledWith("/access-control/whitelist/remove", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
  });

  it("addAclBlacklist sends POST with entries body", async () => {
    const entries = [{ channel: "chan", user_id: "u1" }];
    await accessControlApi.addAclBlacklist(entries);
    expect(request).toHaveBeenCalledWith("/access-control/blacklist/add", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
  });

  it("removeAclBlacklist sends POST with entries body", async () => {
    const entries = [{ channel: "chan", user_id: "u1" }];
    await accessControlApi.removeAclBlacklist(entries);
    expect(request).toHaveBeenCalledWith("/access-control/blacklist/remove", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
  });

  it("updateAclRemark sends POST with channel, user_id, remark", async () => {
    await accessControlApi.updateAclRemark("chan", "u1", "team lead");
    expect(request).toHaveBeenCalledWith("/access-control/remark", {
      method: "POST",
      body: JSON.stringify({
        channel: "chan",
        user_id: "u1",
        remark: "team lead",
      }),
    });
  });

  it("getAclAllPending calls GET /access-control/pending/all", async () => {
    await accessControlApi.getAclAllPending();
    expect(request).toHaveBeenCalledWith("/access-control/pending/all");
  });

  it("approveAclPending sends POST with entries body", async () => {
    const entries = [{ channel: "chan", user_id: "u1" }];
    await accessControlApi.approveAclPending(entries);
    expect(request).toHaveBeenCalledWith("/access-control/pending/approve", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
  });

  it("denyAclPending sends POST with entries body", async () => {
    const entries = [{ channel: "chan", user_id: "u1" }];
    await accessControlApi.denyAclPending(entries);
    expect(request).toHaveBeenCalledWith("/access-control/pending/deny", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
  });

  it("dismissAclPending sends POST with entries body", async () => {
    const entries = [{ channel: "chan", user_id: "u1" }];
    await accessControlApi.dismissAclPending(entries);
    expect(request).toHaveBeenCalledWith("/access-control/pending/dismiss", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
  });

  it("updatePendingRemark sends POST with channel, user_id, remark", async () => {
    await accessControlApi.updatePendingRemark("chan", "u1", "reviewing");
    expect(request).toHaveBeenCalledWith("/access-control/pending/remark", {
      method: "POST",
      body: JSON.stringify({
        channel: "chan",
        user_id: "u1",
        remark: "reviewing",
      }),
    });
  });

  it("updateUsername sends POST with channel, user_id, username", async () => {
    await accessControlApi.updateUsername("chan", "u1", "alice");
    expect(request).toHaveBeenCalledWith("/access-control/username", {
      method: "POST",
      body: JSON.stringify({
        channel: "chan",
        user_id: "u1",
        username: "alice",
      }),
    });
  });
});
