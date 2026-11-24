/**
 * mailAccessControl.ts - request contract layer for the mail ACL surface.
 *
 * Sibling coverage note: ./mailAccessControl.test.ts already pins the two
 * processing-safety endpoints (getMailProcessingPauses and
 * resumeMailProcessing, including a percent-encoded agent id). This file
 * deliberately covers the thirteen wrappers that file leaves out, so the two
 * do not duplicate each other:
 *   - reads: getMailAclAll / getMailAgents / getMailPendingAll /
 *     getMailPendingCount
 *   - the three-entry pending decisions: approveMailPending /
 *     denyMailPending / dismissMailPending
 *   - remark writes: updateMailPendingRemark / updateMailRemark
 *   - list membership: addMailWhitelist / removeMailWhitelist /
 *     addMailBlacklist / removeMailBlacklist
 *
 * Three contract details are pinned here because nothing else would catch a
 * silent change:
 *   - every pending decision and every list mutation wraps its argument in an
 *     { entries } envelope rather than posting the array bare, so the array is
 *     always at body.entries.
 *   - approveMailPending and denyMailPending accept an optional per-entry
 *     remark, while dismissMailPending entries carry no remark field at all.
 *     JSON.stringify drops an absent key but keeps an explicit undefined one,
 *     so the two shapes are asserted separately.
 *   - the read-only wrappers call request with exactly one argument.
 *
 * Assertions are on path / method / body - the frontend contract - never on
 * backend behaviour.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { mailAccessControlApi } from "./mailAccessControl";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";

/** Every stub resolves to this, so each case also pins value pass-through. */
const SENTINEL = { __passthrough: true } as never;

function stubRequest(): void {
  vi.mocked(request).mockResolvedValue(SENTINEL);
}

/** Pull the serialised body out of the single recorded request call. */
function sentBody(): unknown {
  const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
  return JSON.parse(opts.body ?? "null");
}

afterEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockReset();
});

describe("mailAccessControlApi reads", () => {
  it("reads the whole ACL map from the resource root", async () => {
    stubRequest();

    const out = await mailAccessControlApi.getMailAclAll();

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mail-access-control");
    expect(out).toBe(SENTINEL);
  });

  it("reads the agent id list from the agents path", async () => {
    stubRequest();

    const out = await mailAccessControlApi.getMailAgents();

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mail-access-control/agents");
    expect(out).toBe(SENTINEL);
  });

  it("reads every pending entry regardless of agent", async () => {
    stubRequest();

    const out = await mailAccessControlApi.getMailPendingAll();

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mail-access-control/pending/all");
    expect(out).toBe(SENTINEL);
  });

  it("reads the pending badge count from its own path", async () => {
    stubRequest();

    const out = await mailAccessControlApi.getMailPendingCount();

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mail-access-control/pending/count");
    expect(out).toBe(SENTINEL);
  });

  it("keeps the pending list and pending count paths distinct", async () => {
    stubRequest();

    await mailAccessControlApi.getMailPendingAll();
    await mailAccessControlApi.getMailPendingCount();

    expect(vi.mocked(request).mock.calls.map((c) => c[0])).toEqual([
      "/mail-access-control/pending/all",
      "/mail-access-control/pending/count",
    ]);
  });
});

describe("mailAccessControlApi pending decisions", () => {
  it("approves nothing with an empty entries envelope", async () => {
    stubRequest();

    const out = await mailAccessControlApi.approveMailPending([]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(
      "/mail-access-control/pending/approve",
      {
        method: "POST",
        body: '{"entries":[]}',
      },
    );
    expect(out).toBe(SENTINEL);
  });

  it("approves a single entry wrapped in the entries envelope", async () => {
    stubRequest();

    await mailAccessControlApi.approveMailPending([
      { agent_id: "qpqat-envoy", address: "alice@example.com" },
    ]);

    expect(sentBody()).toEqual({
      entries: [{ agent_id: "qpqat-envoy", address: "alice@example.com" }],
    });
  });

  it("approves two entries in call order", async () => {
    stubRequest();

    const entries = [
      { agent_id: "a", address: "one@example.com", remark: "first" },
      { agent_id: "b", address: "two@example.com", remark: "second" },
    ];
    await mailAccessControlApi.approveMailPending(entries);

    expect(sentBody()).toEqual({ entries });
  });

  it("keeps an approve remark when the caller supplies one", async () => {
    stubRequest();

    await mailAccessControlApi.approveMailPending([
      { agent_id: "a", address: "x@example.com", remark: "trusted vendor" },
    ]);

    expect(sentBody()).toEqual({
      entries: [
        { agent_id: "a", address: "x@example.com", remark: "trusted vendor" },
      ],
    });
  });

  it("omits the approve remark key entirely when it is not supplied", async () => {
    stubRequest();

    await mailAccessControlApi.approveMailPending([
      { agent_id: "a", address: "x@example.com" },
    ]);

    const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
    expect(opts.body).toBe(
      '{"entries":[{"agent_id":"a","address":"x@example.com"}]}',
    );
    expect(
      Object.keys((sentBody() as { entries: object[] }).entries[0]),
    ).toEqual(["agent_id", "address"]);
  });

  it("preserves an explicitly empty approve remark instead of dropping it", async () => {
    stubRequest();

    await mailAccessControlApi.approveMailPending([
      { agent_id: "a", address: "x@example.com", remark: "" },
    ]);

    const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
    expect(opts.body).toContain('"remark":""');
  });

  it("denies nothing with an empty entries envelope", async () => {
    stubRequest();

    const out = await mailAccessControlApi.denyMailPending([]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mail-access-control/pending/deny", {
      method: "POST",
      body: '{"entries":[]}',
    });
    expect(out).toBe(SENTINEL);
  });

  it("denies a single entry with an optional remark", async () => {
    stubRequest();

    await mailAccessControlApi.denyMailPending([
      { agent_id: "a", address: "spam@example.com", remark: "phishing" },
    ]);

    expect(sentBody()).toEqual({
      entries: [
        { agent_id: "a", address: "spam@example.com", remark: "phishing" },
      ],
    });
  });

  it("denies two entries in call order", async () => {
    stubRequest();

    const entries = [
      { agent_id: "a", address: "one@example.com" },
      { agent_id: "b", address: "two@example.com", remark: "blocked" },
    ];
    await mailAccessControlApi.denyMailPending(entries);

    expect(sentBody()).toEqual({ entries });
  });

  it("posts approve and deny to different paths", async () => {
    stubRequest();

    await mailAccessControlApi.approveMailPending([
      { agent_id: "a", address: "x@example.com" },
    ]);
    await mailAccessControlApi.denyMailPending([
      { agent_id: "a", address: "x@example.com" },
    ]);

    expect(vi.mocked(request).mock.calls.map((c) => c[0])).toEqual([
      "/mail-access-control/pending/approve",
      "/mail-access-control/pending/deny",
    ]);
  });

  it("dismisses nothing with an empty entries envelope", async () => {
    stubRequest();

    const out = await mailAccessControlApi.dismissMailPending([]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(
      "/mail-access-control/pending/dismiss",
      { method: "POST", body: '{"entries":[]}' },
    );
    expect(out).toBe(SENTINEL);
  });

  it("dismisses a single entry using the remark-free entry shape", async () => {
    stubRequest();

    await mailAccessControlApi.dismissMailPending([
      { agent_id: "a", address: "later@example.com" },
    ]);

    const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
    expect(opts.body).toBe(
      '{"entries":[{"agent_id":"a","address":"later@example.com"}]}',
    );
  });

  it("dismisses two entries in call order", async () => {
    stubRequest();

    const entries = [
      { agent_id: "a", address: "one@example.com" },
      { agent_id: "b", address: "two@example.com" },
    ];
    await mailAccessControlApi.dismissMailPending(entries);

    expect(sentBody()).toEqual({ entries });
  });

  it("keeps all three decision verbs and paths apart", async () => {
    stubRequest();

    await mailAccessControlApi.approveMailPending([]);
    await mailAccessControlApi.denyMailPending([]);
    await mailAccessControlApi.dismissMailPending([]);

    const calls = vi.mocked(request).mock.calls;
    expect(calls.map((c) => c[0])).toEqual([
      "/mail-access-control/pending/approve",
      "/mail-access-control/pending/deny",
      "/mail-access-control/pending/dismiss",
    ]);
    for (const c of calls) {
      expect((c[1] as { method?: string }).method).toBe("POST");
    }
  });
});

describe("mailAccessControlApi remark writes", () => {
  it("writes a pending remark as three flat body fields", async () => {
    stubRequest();

    const out = await mailAccessControlApi.updateMailPendingRemark(
      "qpqat-envoy",
      "alice@example.com",
      "approved offline",
    );

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(
      "/mail-access-control/pending/remark",
      {
        method: "POST",
        body: JSON.stringify({
          agent_id: "qpqat-envoy",
          address: "alice@example.com",
          remark: "approved offline",
        }),
      },
    );
    expect(out).toBe(SENTINEL);
  });

  it("does not wrap a pending remark in the entries envelope", async () => {
    stubRequest();

    await mailAccessControlApi.updateMailPendingRemark(
      "a",
      "x@example.com",
      "r",
    );

    expect(Object.keys(sentBody() as object)).toEqual([
      "agent_id",
      "address",
      "remark",
    ]);
  });

  it("writes an ACL remark to the non-pending remark path", async () => {
    stubRequest();

    const out = await mailAccessControlApi.updateMailRemark(
      "qpqat-envoy",
      "alice@example.com",
      "long term contact",
    );

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mail-access-control/remark", {
      method: "POST",
      body: JSON.stringify({
        agent_id: "qpqat-envoy",
        address: "alice@example.com",
        remark: "long term contact",
      }),
    });
    expect(out).toBe(SENTINEL);
  });

  it("keeps the pending remark path distinct from the ACL remark path", async () => {
    stubRequest();

    await mailAccessControlApi.updateMailPendingRemark(
      "a",
      "x@example.com",
      "r",
    );
    await mailAccessControlApi.updateMailRemark("a", "x@example.com", "r");

    expect(vi.mocked(request).mock.calls.map((c) => c[0])).toEqual([
      "/mail-access-control/pending/remark",
      "/mail-access-control/remark",
    ]);
  });

  it("passes a non-ASCII remark through as UTF-8 JSON", async () => {
    stubRequest();

    await mailAccessControlApi.updateMailRemark("a", "x@example.com", "分组 a");

    expect(sentBody()).toEqual({
      agent_id: "a",
      address: "x@example.com",
      remark: "分组 a",
    });
  });

  it("passes an empty remark through rather than dropping it", async () => {
    stubRequest();

    await mailAccessControlApi.updateMailRemark("a", "x@example.com", "");

    const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
    expect(opts.body).toContain('"remark":""');
  });
});

describe("mailAccessControlApi list membership", () => {
  it("adds to the whitelist with an entries envelope and no body remark", async () => {
    stubRequest();

    const out = await mailAccessControlApi.addMailWhitelist([
      { agent_id: "a", address: "ok@example.com" },
    ]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mail-access-control/whitelist/add", {
      method: "POST",
      body: '{"entries":[{"agent_id":"a","address":"ok@example.com"}]}',
    });
    expect(out).toBe(SENTINEL);
  });

  it("keeps optional display_name and remark on a whitelist add", async () => {
    stubRequest();

    await mailAccessControlApi.addMailWhitelist([
      {
        agent_id: "a",
        address: "ok@example.com",
        remark: "partner",
        display_name: "Partner Co",
      },
    ]);

    expect(sentBody()).toEqual({
      entries: [
        {
          agent_id: "a",
          address: "ok@example.com",
          remark: "partner",
          display_name: "Partner Co",
        },
      ],
    });
  });

  it("adds two whitelist entries in call order", async () => {
    stubRequest();

    const entries = [
      { agent_id: "a", address: "one@example.com" },
      { agent_id: "b", address: "two@example.com", display_name: "Two" },
    ];
    await mailAccessControlApi.addMailWhitelist(entries);

    expect(sentBody()).toEqual({ entries });
  });

  it("removes from the whitelist using the remark-free entry shape", async () => {
    stubRequest();

    const out = await mailAccessControlApi.removeMailWhitelist([
      { agent_id: "a", address: "ok@example.com" },
    ]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(
      "/mail-access-control/whitelist/remove",
      {
        method: "POST",
        body: '{"entries":[{"agent_id":"a","address":"ok@example.com"}]}',
      },
    );
    expect(out).toBe(SENTINEL);
  });

  it("removes nothing from the whitelist with an empty envelope", async () => {
    stubRequest();

    await mailAccessControlApi.removeMailWhitelist([]);

    const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
    expect(opts.body).toBe('{"entries":[]}');
  });

  it("adds to the blacklist on its own path", async () => {
    stubRequest();

    const out = await mailAccessControlApi.addMailBlacklist([
      { agent_id: "a", address: "bad@example.com", remark: "abuse" },
    ]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mail-access-control/blacklist/add", {
      method: "POST",
      body: JSON.stringify({
        entries: [
          { agent_id: "a", address: "bad@example.com", remark: "abuse" },
        ],
      }),
    });
    expect(out).toBe(SENTINEL);
  });

  it("removes from the blacklist on its own path", async () => {
    stubRequest();

    const out = await mailAccessControlApi.removeMailBlacklist([
      { agent_id: "a", address: "bad@example.com" },
    ]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(
      "/mail-access-control/blacklist/remove",
      {
        method: "POST",
        body: '{"entries":[{"agent_id":"a","address":"bad@example.com"}]}',
      },
    );
    expect(out).toBe(SENTINEL);
  });

  it("keeps the four list paths pairwise distinct", async () => {
    stubRequest();

    await mailAccessControlApi.addMailWhitelist([]);
    await mailAccessControlApi.removeMailWhitelist([]);
    await mailAccessControlApi.addMailBlacklist([]);
    await mailAccessControlApi.removeMailBlacklist([]);

    expect(vi.mocked(request).mock.calls.map((c) => c[0])).toEqual([
      "/mail-access-control/whitelist/add",
      "/mail-access-control/whitelist/remove",
      "/mail-access-control/blacklist/add",
      "/mail-access-control/blacklist/remove",
    ]);
  });

  it("passes a non-ASCII address through the whitelist add untouched", async () => {
    stubRequest();

    await mailAccessControlApi.addMailWhitelist([
      { agent_id: "a", address: "用户@example.com", display_name: "用户 一" },
    ]);

    expect(sentBody()).toEqual({
      entries: [
        {
          agent_id: "a",
          address: "用户@example.com",
          display_name: "用户 一",
        },
      ],
    });
  });

  it("does not percent-encode addresses because they travel in the body", async () => {
    stubRequest();

    await mailAccessControlApi.addMailBlacklist([
      { agent_id: "a b", address: "a b+tag@example.com" },
    ]);

    const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
    expect(opts.body).toContain("a b+tag@example.com");
    expect(opts.body).not.toContain("%20");
    expect(opts.body).not.toContain("%2B");
  });
});
