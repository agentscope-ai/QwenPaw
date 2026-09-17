import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/modules/auth", () => ({
  authApi: {
    getStatus: vi.fn(),
    refresh: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    getMe: vi.fn(),
    updatePreferences: vi.fn(),
    listSessions: vi.fn(),
    revokeAllSessions: vi.fn(),
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
    verify: vi.fn(),
  },
}));

import { authApi } from "../api/modules/auth";
import { getApiToken } from "../api/config";
import { useAgentStore } from "./agentStore";
import { useAuthStore } from "./authStore";
import { useBackgroundTasksStore } from "./backgroundTasksStore";
import { useSessionListStore } from "./sessionListStore";
import {
  useCodingTabsStore,
  AGENT_FILES_TABS_STORAGE_KEY,
  SESSION_FILES_TABS_STORAGE_KEY,
} from "./codingTabsStore";
import { useCodeFileCacheStore } from "./codeFileCacheStore";
import { useFilesSurfaceStore } from "./filesSurfaceStore";
import { useProjectDirectoryStore } from "./projectDirectoryStore";

const user = {
  id: "user-1",
  username: "admin",
  platform_role: "admin" as const,
  status: "active" as const,
};

const loginResponse = {
  token: "memory-access",
  username: "admin",
  user,
  session: { id: "session-1", client_info: {} },
  access_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
};

describe("authStore multi-user lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.getState().reset();
  });

  it("restores a multi-user login through the HttpOnly refresh cookie", async () => {
    vi.mocked(authApi.getStatus).mockResolvedValue({
      enabled: true,
      has_users: true,
      mode: "multi_user",
    });
    vi.mocked(authApi.refresh).mockResolvedValue(loginResponse);
    vi.mocked(authApi.getMe).mockResolvedValue({
      user,
      preferences: { language: "zh-CN", timezone: "Asia/Shanghai" },
    });

    await useAuthStore.getState().bootstrap();

    expect(useAuthStore.getState().phase).toBe("authenticated");
    expect(useAuthStore.getState().user).toEqual(user);
    expect(getApiToken()).toBe("memory-access");
    expect(localStorage.getItem("qwenpaw_auth_token")).toBeNull();
  });

  it("keeps a newly logged-in access token out of localStorage", async () => {
    vi.mocked(authApi.login).mockResolvedValue(loginResponse);
    vi.mocked(authApi.getMe).mockResolvedValue({
      user,
      preferences: { language: "en", timezone: "UTC" },
    });
    useAuthStore.setState({ mode: "multi_user", authEnabled: true });

    await useAuthStore.getState().login("admin", "correct");

    expect(getApiToken()).toBe("memory-access");
    expect(localStorage.getItem("qwenpaw_auth_token")).toBeNull();
    expect(useAuthStore.getState().preferences?.timezone).toBe("UTC");
  });

  it("clears identity-scoped caches when a different user logs in", async () => {
    localStorage.setItem("qwenpaw_authenticated_user_id", "user-0");
    localStorage.setItem("qwenpaw-agent-storage", "old-agent");
    localStorage.setItem("qwenpaw-last-used-agent", "old-agent-id");
    localStorage.setItem("qwenpaw_chat_input_draft_old", "old-draft");
    localStorage.setItem("qwenpaw:message-queue:old", "old-queue");
    localStorage.setItem("approval_level-old", "AUTO");
    localStorage.setItem(
      "qwenpaw:message-queue:user:user-0:private-chat",
      "old-user-queue",
    );
    localStorage.setItem(
      "qwenpaw:message-queue:user:user-2:private-chat",
      "other-user-queue",
    );
    useAgentStore.setState({
      selectedAgent: "private-agent",
      agents: [],
      lastChatIdByAgent: { "private-agent": "private-chat" },
    });
    vi.mocked(authApi.login).mockResolvedValue(loginResponse);
    vi.mocked(authApi.getMe).mockResolvedValue({
      user,
      preferences: { language: "en", timezone: "UTC" },
    });
    useAuthStore.setState({ mode: "multi_user", authEnabled: true });

    await useAuthStore.getState().login("admin", "correct");

    expect(localStorage.getItem("qwenpaw_authenticated_user_id")).toBe(
      "user-1",
    );
    expect(localStorage.getItem("qwenpaw-agent-storage")).toBeNull();
    expect(localStorage.getItem("qwenpaw-last-used-agent")).toBeNull();
    expect(localStorage.getItem("qwenpaw_chat_input_draft_old")).toBeNull();
    expect(localStorage.getItem("qwenpaw:message-queue:old")).toBeNull();
    expect(localStorage.getItem("approval_level-old")).toBeNull();
    expect(
      localStorage.getItem("qwenpaw:message-queue:user:user-0:private-chat"),
    ).toBeNull();
    expect(
      localStorage.getItem("qwenpaw:message-queue:user:user-2:private-chat"),
    ).toBe("other-user-queue");
    expect(useAgentStore.getState().selectedAgent).toBe("default");
    expect(useAgentStore.getState().lastChatIdByAgent).toEqual({});
  });

  it("logs out the current device and clears in-memory identity", async () => {
    vi.mocked(authApi.logout).mockResolvedValue({ revoked: true });
    useAuthStore.setState({
      mode: "multi_user",
      authEnabled: true,
      phase: "authenticated",
      user,
      accessToken: "memory-access",
    });
    useSessionListStore.setState({
      sessions: [{ id: "private-chat" } as never],
      lastUpdated: 1,
    });
    useBackgroundTasksStore.setState({
      tasks: [
        {
          toolCallId: "private-task",
          toolName: "read_file",
          sessionId: "private-chat",
          startTime: 1,
          endTime: null,
          status: "running",
          liveOutput: "private-output",
          result: null,
          hintVisible: false,
        },
      ],
    });

    await useAuthStore.getState().logout();

    expect(authApi.logout).toHaveBeenCalledOnce();
    expect(useAuthStore.getState().phase).toBe("anonymous");
    expect(useAuthStore.getState().user).toBeNull();
    expect(getApiToken()).toBe("");
    expect(useSessionListStore.getState().sessions).toEqual([]);
    expect(useBackgroundTasksStore.getState().tasks).toEqual([]);
  });

  it("updates the in-memory user after saving profile fields", async () => {
    const updated = { ...user, username: "alice", display_name: "Alice Chen" };
    vi.mocked(authApi.updateProfile).mockResolvedValue({ user: updated });
    useAuthStore.setState({ user, phase: "authenticated" });

    await useAuthStore.getState().updateProfile({
      username: "alice",
      display_name: "Alice Chen",
      email: "alice@example.com",
      phone: "",
      department: "研发部",
      job_title: "平台工程师",
      remark: "",
    });

    expect(useAuthStore.getState().user).toEqual(updated);
  });

  it("clears the identity after changing the password", async () => {
    vi.mocked(authApi.changePassword).mockResolvedValue({
      revoked_sessions: 2,
    });
    useAuthStore.setState({
      user,
      phase: "authenticated",
      accessToken: "token",
    });

    await useAuthStore
      .getState()
      .changePassword("OldPass!2026", "NewPass!2026");

    expect(useAuthStore.getState().phase).toBe("anonymous");
    expect(useAuthStore.getState().user).toBeNull();
    expect(getApiToken()).toBe("");
  });

  it.each(["logout", "login"])(
    "clears private file workbench data on %s",
    async (action) => {
      localStorage.setItem("qwenpaw_authenticated_user_id", "previous-user");
      useAuthStore.setState({ mode: "multi_user", authEnabled: true });
      const scope = "agent:shared-agent";
      useCodingTabsStore.getState().openTab(scope, {
        path: "daily::private.md",
        content: "private content",
        dirty: true,
        source: "daily",
      });
      useCodingTabsStore.getState().setDiff(scope, "daily::private.md", {
        original: "private original",
        modified: "private content",
      });
      useCodeFileCacheStore.getState().set("private.md", "private cache", null);
      useFilesSurfaceStore
        .getState()
        .dispatchSession("session:shared-agent:session", {
          type: "OPEN_WORKSPACE",
          target: { source: "workspace", path: "private.md" },
          trigger: null,
        });
      useProjectDirectoryStore
        .getState()
        .setProjectDir("shared-agent", "/private/project");
      sessionStorage.setItem(
        "qwenpaw-session-project-dir:shared-agent:new",
        "/private/project",
      );
      expect(localStorage.getItem(AGENT_FILES_TABS_STORAGE_KEY)).toContain(
        "private original",
      );

      if (action === "logout") {
        vi.mocked(authApi.logout).mockResolvedValue({ revoked: true });
        await useAuthStore.getState().logout();
      } else {
        vi.mocked(authApi.login).mockResolvedValue(loginResponse);
        vi.mocked(authApi.getMe).mockResolvedValue({
          user,
          preferences: { language: "en", timezone: "UTC" },
        });
        await useAuthStore.getState().login("admin", "correct");
      }

      expect(useCodingTabsStore.getState().tabsByAgent).toEqual({});
      expect(useCodingTabsStore.getState().diffsByAgent).toEqual({});
      expect(useCodingTabsStore.getState().activeTabByAgent).toEqual({});
      expect(localStorage.getItem(AGENT_FILES_TABS_STORAGE_KEY)).toBeNull();
      expect(localStorage.getItem(SESSION_FILES_TABS_STORAGE_KEY)).toBeNull();
      expect(useCodeFileCacheStore.getState().entries.size).toBe(0);
      expect(useFilesSurfaceStore.getState().sessionDrawers).toEqual({});
      expect(useProjectDirectoryStore.getState().projectDirByAgent).toEqual({});
      expect(
        sessionStorage.getItem("qwenpaw-session-project-dir:shared-agent:new"),
      ).toBeNull();
    },
  );
});
