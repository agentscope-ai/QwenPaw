import { act, renderHook, waitFor, cleanup } from "@testing-library/react";
import { App } from "antd";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useSkills } from "./useSkills";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import { invalidateSkillCache } from "@/api/modules/skill";
import "@/i18n";

beforeEach(() => {
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "actor", platform_role: "member" } as never,
  });
  useAgentStore.setState({ selectedAgent: "a", agents: [] });
  invalidateSkillCache();
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response("[]", { headers: { "Content-Type": "application/json" } }),
      ),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <App>{children}</App>
);

it("fails closed when the selected Agent or authenticated identity is unknown", async () => {
  const { result } = renderHook(useSkills, { wrapper });
  expect(result.current.readOnly).toBe(true);
  act(() =>
    useAgentStore.setState({
      agents: [
        { id: "a", enabled: true, access_role: "owner", can_edit: true },
      ] as never,
    }),
  );
  await waitFor(() => expect(result.current.readOnly).toBe(false));
  act(() => useAuthStore.setState({ phase: "loading" }));
  expect(result.current.readOnly).toBe(true);
});

it.each(["owner", "collaborator", "user"])(
  "derives %s write permission from the real Agent store",
  async (role) => {
    useAgentStore.setState({
      agents: [
        {
          id: "a",
          enabled: true,
          access_role: role,
          can_edit: role !== "user",
        },
      ] as never,
    });
    const { result } = renderHook(useSkills, { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.readOnly).toBe(role === "user");
  },
);
