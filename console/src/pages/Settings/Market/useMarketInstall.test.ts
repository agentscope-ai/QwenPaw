// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketResult } from "../../../api/modules/market";

const hoisted = vi.hoisted(() => ({
  api: {
    startHubSkillInstall: vi.fn(),
    getHubSkillInstallStatus: vi.fn(),
    cancelHubSkillInstall: vi.fn(),
    importPoolSkillFromHub: vi.fn(),
  },
  invalidateSkillCache: vi.fn(),
}));

vi.mock("../../../api", () => ({
  default: hoisted.api,
}));
vi.mock("../../../api/modules/skill", () => ({
  invalidateSkillCache: hoisted.invalidateSkillCache,
}));

import { useMarketInstall } from "./useMarketInstall";

const marketResult: MarketResult = {
  source: "qwenpaw",
  slug: "market-skill",
  name: "Market Skill",
  description: "Test skill",
  source_url: "https://example.com/market-skill.zip",
  version: "1.0.0",
  author: "QwenPaw",
  icon_url: null,
  stats: null,
};

describe("useMarketInstall", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("notifies the host after a workspace install completes", async () => {
    const onSuccess = vi.fn();
    hoisted.api.startHubSkillInstall.mockResolvedValue({ task_id: "task-1" });
    hoisted.api.getHubSkillInstallStatus.mockResolvedValue({
      status: "completed",
      result: { installed: true, name: "market-skill" },
    });
    const { result } = renderHook(() =>
      useMarketInstall({ selectedAgent: "agent-1", onSuccess }),
    );

    act(() => result.current.enqueue([marketResult], "workspace"));

    await waitFor(() =>
      expect(result.current.queue[0]?.status).toBe("completed"),
    );
    expect(hoisted.invalidateSkillCache).toHaveBeenCalledWith({
      agentId: "agent-1",
      workspaces: true,
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("notifies the host after a skill pool import completes", async () => {
    const onSuccess = vi.fn();
    hoisted.api.importPoolSkillFromHub.mockResolvedValue({
      installed: true,
      name: "market-skill",
    });
    const { result } = renderHook(() =>
      useMarketInstall({ selectedAgent: "agent-1", onSuccess }),
    );

    act(() => result.current.enqueue([marketResult], "pool"));

    await waitFor(() =>
      expect(result.current.queue[0]?.status).toBe("completed"),
    );
    expect(hoisted.invalidateSkillCache).toHaveBeenCalledWith({ pool: true });
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("does not notify the host when an install fails", async () => {
    const onSuccess = vi.fn();
    hoisted.api.importPoolSkillFromHub.mockRejectedValue(new Error("failed"));
    const { result } = renderHook(() =>
      useMarketInstall({ selectedAgent: "agent-1", onSuccess }),
    );

    act(() => result.current.enqueue([marketResult], "pool"));

    await waitFor(() => expect(result.current.queue[0]?.status).toBe("failed"));
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("does not notify the host when an install is cancelled", async () => {
    const onSuccess = vi.fn();
    hoisted.api.startHubSkillInstall.mockResolvedValue({ task_id: "task-1" });
    hoisted.api.getHubSkillInstallStatus.mockResolvedValue({
      status: "cancelled",
    });
    const { result } = renderHook(() =>
      useMarketInstall({ selectedAgent: "agent-1", onSuccess }),
    );

    act(() => result.current.enqueue([marketResult], "workspace"));

    await waitFor(() =>
      expect(result.current.queue[0]?.status).toBe("cancelled"),
    );
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
