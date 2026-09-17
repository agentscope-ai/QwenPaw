import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";
import { channelBindingsApi } from "./channelBindings";

describe("channelBindingsApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(request).mockResolvedValue(undefined);
  });

  it("uses agent-scoped endpoints without accepting a user id", async () => {
    await channelBindingsApi.listUserChannelBindings("public agent");
    expect(request).toHaveBeenLastCalledWith(
      "/agents/public%20agent/channel-bindings",
    );

    await channelBindingsApi.updateUserChannelBinding(
      "public agent",
      "telegram",
      {
        display_name: "Mine",
        enabled: true,
        config: { bot_token: "secret" },
      },
    );
    expect(request).toHaveBeenLastCalledWith(
      "/agents/public%20agent/channel-bindings/telegram",
      {
        method: "PUT",
        body: JSON.stringify({
          display_name: "Mine",
          enabled: true,
          config: { bot_token: "secret" },
        }),
      },
    );

    await channelBindingsApi.deleteUserChannelBinding(
      "public agent",
      "telegram",
    );
    expect(request).toHaveBeenLastCalledWith(
      "/agents/public%20agent/channel-bindings/telegram",
      { method: "DELETE" },
    );

    await channelBindingsApi.checkUserChannelBindingConflict(
      "public agent",
      "telegram",
      { bot_token: "secret" },
    );
    expect(request).toHaveBeenLastCalledWith(
      "/agents/public%20agent/channel-bindings/telegram/conflict-check",
      {
        method: "POST",
        body: JSON.stringify({ config: { bot_token: "secret" } }),
      },
    );
  });
});
