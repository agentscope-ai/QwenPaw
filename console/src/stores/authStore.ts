import { create } from "zustand";
import {
  authApi,
  type AuthMode,
  type AuthSession,
  type AuthUser,
  type UserProfileInput,
} from "../api/modules/auth";
import { setApiAuthMode } from "../api/config";
import { adoptAccessSession, clearAccessSession } from "../api/authSession";
import { useAgentStore } from "./agentStore";
import { useMessageQueueStore } from "./messageQueueStore";
import { useBackgroundTasksStore } from "./backgroundTasksStore";
import { useSessionListStore } from "./sessionListStore";
import sessionApi from "../pages/Chat/sessionApi";
import { AUTHENTICATED_USER_ID_KEY } from "./identityStorage";
import {
  useCodingTabsStore,
  AGENT_FILES_TABS_STORAGE_KEY,
  SESSION_FILES_TABS_STORAGE_KEY,
} from "./codingTabsStore";
import { useCodeFileCacheStore } from "./codeFileCacheStore";
import { useFilesSurfaceStore } from "./filesSurfaceStore";
import { useProjectDirectoryStore } from "./projectDirectoryStore";

type AuthPhase = "loading" | "authenticated" | "anonymous" | "disabled";

interface AuthState {
  phase: AuthPhase;
  authEnabled: boolean;
  mode: AuthMode;
  user: AuthUser | null;
  preferences: { language: string; timezone: string } | null;
  sessions: AuthSession[];
  accessToken: string;
  bootstrap: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  loadSessions: () => Promise<void>;
  revokeAllSessions: () => Promise<void>;
  updatePreferences: (language: string, timezone: string) => Promise<void>;
  updateProfile: (profile: UserProfileInput) => Promise<void>;
  changePassword: (
    currentPassword: string,
    newPassword: string,
  ) => Promise<void>;
  reset: () => void;
}

const initialState = {
  phase: "loading" as AuthPhase,
  authEnabled: false,
  mode: "legacy" as AuthMode,
  user: null,
  preferences: null,
  sessions: [],
  accessToken: "",
};

const USER_SCOPED_STORAGE_KEYS = new Set([
  "qwenpaw-agent-storage",
  "qwenpaw-last-used-agent",
  AGENT_FILES_TABS_STORAGE_KEY,
  SESSION_FILES_TABS_STORAGE_KEY,
]);
const USER_SCOPED_STORAGE_PREFIXES = [
  "qwenpaw_chat_input_draft",
  "qwenpaw:message-queue:",
  "approval_level-",
  "qwenpaw-session-project-dir:",
];

function belongsToStorageUser(key: string, userId: string): boolean {
  const marker = `:user:${userId}`;
  const markerIndex = key.indexOf(marker);
  if (markerIndex < 0) return false;
  const markerEnd = markerIndex + marker.length;
  return markerEnd === key.length || key[markerEnd] === ":";
}

function clearUserScopedStorage(
  storage: Storage,
  currentUserId?: string,
): void {
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (
      key &&
      (USER_SCOPED_STORAGE_KEYS.has(key) ||
        (USER_SCOPED_STORAGE_PREFIXES.some((prefix) =>
          key.startsWith(prefix),
        ) &&
          !key.includes(":user:")) ||
        (currentUserId ? belongsToStorageUser(key, currentUserId) : false))
    ) {
      keys.push(key);
    }
  }
  keys.forEach((key) => storage.removeItem(key));
}

function resetUserScopedClientState(nextUserId?: string): void {
  const currentUserId =
    localStorage.getItem(AUTHENTICATED_USER_ID_KEY) || undefined;
  useAgentStore.getState().resetIdentityState();
  useMessageQueueStore.setState({
    queues: {},
    runStates: {},
    currentSendingId: null,
    lastMigratedTo: null,
  });
  useSessionListStore.setState({ sessions: [], lastUpdated: Date.now() });
  useBackgroundTasksStore.setState({ tasks: [] });
  useCodingTabsStore.setState({
    tabsByAgent: {},
    activeTabByAgent: {},
    diffsByAgent: {},
  });
  useCodeFileCacheStore.getState().clear();
  useFilesSurfaceStore.setState({ sessionDrawers: {} });
  useProjectDirectoryStore.setState({ projectDirByAgent: {} });
  sessionApi.resetIdentityState();
  delete (window as unknown as { currentSessionId?: string }).currentSessionId;
  clearUserScopedStorage(localStorage, currentUserId);
  clearUserScopedStorage(sessionStorage, currentUserId);
  if (nextUserId) {
    localStorage.setItem(AUTHENTICATED_USER_ID_KEY, nextUserId);
  } else {
    localStorage.removeItem(AUTHENTICATED_USER_ID_KEY);
  }
}

function adoptAuthenticatedUser(userId: string): void {
  const previousUserId = localStorage.getItem(AUTHENTICATED_USER_ID_KEY);
  if (previousUserId !== userId) {
    resetUserScopedClientState(userId);
  }
}

async function loadIdentity() {
  return authApi.getMe();
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  ...initialState,

  bootstrap: async () => {
    set({ phase: "loading" });
    try {
      const status = await authApi.getStatus();
      const mode: AuthMode = status.mode ?? "legacy";
      setApiAuthMode(mode);
      set({ authEnabled: status.enabled, mode });
      if (!status.enabled) {
        set({ phase: "disabled" });
        return;
      }
      if (mode === "multi_user") {
        const response = await authApi.refresh();
        adoptAccessSession(response);
        const identity = await loadIdentity();
        adoptAuthenticatedUser(identity.user.id);
        set({
          phase: "authenticated",
          user: identity.user,
          preferences: identity.preferences,
          accessToken: response.token,
        });
        return;
      }
      await authApi.verify();
      set({ phase: "authenticated" });
    } catch {
      clearAccessSession();
      set({
        phase: "anonymous",
        user: null,
        preferences: null,
        sessions: [],
        accessToken: "",
      });
    }
  },

  login: async (username, password) => {
    const response = await authApi.login(username, password);
    setApiAuthMode(get().mode);
    adoptAccessSession(response);
    if (get().mode === "multi_user") {
      const identity = await loadIdentity();
      adoptAuthenticatedUser(identity.user.id);
      set({
        phase: "authenticated",
        user: identity.user,
        preferences: identity.preferences,
        accessToken: response.token,
      });
    } else {
      set({ phase: "authenticated", accessToken: response.token });
    }
  },

  register: async (username, password) => {
    const response = await authApi.register(username, password);
    setApiAuthMode(get().mode);
    adoptAccessSession(response);
    const identity = get().mode === "multi_user" ? await loadIdentity() : null;
    if (identity) adoptAuthenticatedUser(identity.user.id);
    set({
      phase: "authenticated",
      user: identity?.user ?? null,
      preferences: identity?.preferences ?? null,
      accessToken: response.token,
    });
  },

  logout: async () => {
    if (get().mode === "multi_user") {
      await authApi.logout();
    }
    clearAccessSession();
    resetUserScopedClientState();
    set({
      phase: "anonymous",
      user: null,
      preferences: null,
      sessions: [],
      accessToken: "",
    });
  },

  loadSessions: async () => set({ sessions: await authApi.listSessions() }),

  revokeAllSessions: async () => {
    await authApi.revokeAllSessions();
    clearAccessSession();
    resetUserScopedClientState();
    set({
      phase: "anonymous",
      user: null,
      preferences: null,
      sessions: [],
      accessToken: "",
    });
  },

  updatePreferences: async (language, timezone) => {
    const preferences = await authApi.updatePreferences(language, timezone);
    set({ preferences });
  },

  updateProfile: async (profile) => {
    const response = await authApi.updateProfile(profile);
    set({ user: response.user });
  },

  changePassword: async (currentPassword, newPassword) => {
    await authApi.changePassword(currentPassword, newPassword);
    clearAccessSession();
    resetUserScopedClientState();
    set({
      phase: "anonymous",
      user: null,
      preferences: null,
      sessions: [],
      accessToken: "",
    });
  },

  reset: () => {
    clearAccessSession();
    resetUserScopedClientState();
    setApiAuthMode("legacy");
    set(initialState);
  },
}));
