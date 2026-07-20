import { describe, expect, it } from "vitest";
import {
  getQueueRequestId,
  shouldRestoreQueuedInputAfterError,
} from "../queueRequestLifecycle";

describe("queued request acceptance lifecycle", () => {
  it("reads the request id from either the queue field or biz params", () => {
    expect(getQueueRequestId({ qwenpaw_queue_request_id: "direct-id" })).toBe(
      "direct-id",
    );
    expect(
      getQueueRequestId({
        biz_params: { __qwenpaw_queue_request_id: "biz-id" },
      }),
    ).toBe("biz-id");
  });

  it("does not restore an accepted attachment-only input", () => {
    const data = {
      qwenpaw_queue_request_id: "accepted-file",
      query: "",
      attachments: [{ url: "/files/report.pdf" }],
    };

    expect(
      shouldRestoreQueuedInputAfterError(data, new Set(["accepted-file"])),
    ).toBe(false);
  });

  it("restores a request that failed before backend acceptance", () => {
    expect(
      shouldRestoreQueuedInputAfterError(
        { qwenpaw_queue_request_id: "pre-accept" },
        new Set(),
      ),
    ).toBe(true);
  });
});
