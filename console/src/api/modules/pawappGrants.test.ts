import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";
import { pawappGrantsApi } from "./pawappGrants";

describe("pawappGrantsApi", () => {
  beforeEach(() => vi.mocked(request).mockResolvedValue({ actions: [] }));

  it("loads the selected workspace grant catalog", async () => {
    const controller = new AbortController();

    await pawappGrantsApi.list("agent / one", controller.signal);

    expect(request).toHaveBeenCalledWith(
      "/pawapps/workspaces/agent%20%2F%20one/task-grants",
      { signal: controller.signal },
    );
  });

  it("updates one action with the expected policy revision", async () => {
    const body = {
      expected_revision: 4,
      enabled: true,
      input_values: { datasource_id: ["sales"] },
    };

    await pawappGrantsApi.update(
      "agent-1",
      "qwenpaw-data",
      "analyze records",
      body,
    );

    expect(request).toHaveBeenCalledWith(
      "/pawapps/workspaces/agent-1/task-grants/actions/qwenpaw-data/analyze%20records",
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    );
  });

  it("updates one capability bundle atomically", async () => {
    const body = { expected_revision: 4, enabled: true };

    await pawappGrantsApi.updateCapability(
      "agent-1",
      "qwenpaw-creator",
      "media_generation",
      body,
    );

    expect(request).toHaveBeenCalledWith(
      "/pawapps/workspaces/agent-1/task-grants/capabilities/qwenpaw-creator/media_generation",
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    );
  });
});
