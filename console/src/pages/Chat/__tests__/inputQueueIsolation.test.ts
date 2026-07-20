import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import api, { type ChatSpec } from "../../../api";
import {
  buildAgentScopedQueueSessionId,
  getQueueAgentId,
  stripQueueAgentPrefix,
} from "../chatSessionIds";
import {
  clearStoredInputQueue,
  hasStoredInputQueueItems,
  migrateInputQueueStorage,
} from "../inputQueueStorage";
import sessionApi from "../sessionApi";

const INPUT_QUEUE_PREFIX = "agentscope-runtime-webui-input-queue";
const MUTATION_LOCK_PREFIX = "agentscope-runtime-webui-input-queue-mutate";

interface StoredItem {
  id: string;
  data: Record<string, unknown>;
  status?: "pending" | "failed";
  retryCount?: number;
  errorMessage?: string;
  createdAt?: number;
}

interface StoredQueueState {
  items: StoredItem[];
  paused?: boolean;
  ownerTabId?: string;
  ownerUpdatedAt?: number;
  command?: unknown;
  updatedAt?: number;
}

function getStorageKey(queueSessionId: string) {
  return `${INPUT_QUEUE_PREFIX}:${queueSessionId}`;
}

function writeQueue(queueSessionId: string, state: StoredQueueState) {
  localStorage.setItem(getStorageKey(queueSessionId), JSON.stringify(state));
}

function readQueue(queueSessionId: string): StoredQueueState | null {
  const raw = localStorage.getItem(getStorageKey(queueSessionId));
  return raw ? (JSON.parse(raw) as StoredQueueState) : null;
}

function installWebLockMock() {
  const previousDescriptor = Object.getOwnPropertyDescriptor(
    navigator,
    "locks",
  );
  const tails = new Map<string, Promise<void>>();
  const locks = {
    async request<T>(
      name: string,
      _options: { mode: "exclusive" },
      callback: () => T | Promise<T>,
    ) {
      const previous = tails.get(name) ?? Promise.resolve();
      let release!: () => void;
      const current = new Promise<void>((resolve) => {
        release = resolve;
      });
      tails.set(
        name,
        previous.then(() => current),
      );
      await previous;
      try {
        return await callback();
      } finally {
        release();
        if (tails.get(name) === current) tails.delete(name);
      }
    },
  };
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: locks,
  });
  return {
    locks,
    restore() {
      if (previousDescriptor) {
        Object.defineProperty(navigator, "locks", previousDescriptor);
      } else {
        Reflect.deleteProperty(navigator, "locks");
      }
    },
  };
}

function buildChat(id: string, sessionId: string): ChatSpec {
  return {
    id,
    session_id: sessionId,
    user_id: "default",
    channel: "console",
    created_at: "2026-07-17T00:00:00Z",
    updated_at: "2026-07-17T00:00:00Z",
    status: "idle",
  };
}

describe("input queue Agent scope", () => {
  beforeEach(() => localStorage.clear());

  it("keeps identical chat ids isolated by Agent", () => {
    const aScope = buildAgentScopedQueueSessionId("chat-1", "agent-a");
    const bScope = buildAgentScopedQueueSessionId("chat-1", "agent-b");
    expect(aScope).toBe("agent-a::chat-1");
    expect(bScope).toBe("agent-b::chat-1");
    expect(getQueueAgentId(aScope)).toBe("agent-a");
    expect(stripQueueAgentPrefix(aScope)).toBe("chat-1");

    writeQueue(aScope, {
      items: [{ id: "qa", data: { query: "for A" } }],
    });
    writeQueue(bScope, {
      items: [{ id: "qb", data: { query: "for B" } }],
    });
    clearStoredInputQueue(bScope);

    expect(hasStoredInputQueueItems(aScope)).toBe(true);
    expect(readQueue(aScope)?.items[0].data.query).toBe("for A");
    expect(readQueue(bScope)).toBeNull();
  });
});

describe("temporary session queue migration", () => {
  beforeEach(() => localStorage.clear());

  it("preserves FIFO payloads and keeps the destination copy authoritative", async () => {
    const fromScope = buildAgentScopedQueueSessionId("temp", "agent-a");
    const toScope = buildAgentScopedQueueSessionId("real", "agent-a");
    writeQueue(fromScope, {
      items: [
        {
          id: "shared",
          data: { query: "old text" },
          status: "pending",
          createdAt: 1,
        },
        {
          id: "source-only",
          data: {
            query: "with file",
            attachments: [{ url: "/files/a.png", name: "a.png" }],
          },
          createdAt: 2,
        },
      ],
      ownerTabId: "source-tab",
    });
    writeQueue(toScope, {
      items: [
        {
          id: "shared",
          data: { query: "edited text" },
          status: "failed",
          retryCount: 2,
          errorMessage: "network down",
          createdAt: 1,
        },
        {
          id: "target-only",
          data: { query: "target" },
          createdAt: 3,
        },
      ],
      paused: true,
      ownerTabId: "target-tab",
    });

    await migrateInputQueueStorage(fromScope, toScope);

    expect(readQueue(fromScope)).toBeNull();
    const migrated = readQueue(toScope);
    expect(migrated?.items.map((item) => item.id)).toEqual([
      "shared",
      "source-only",
      "target-only",
    ]);
    expect(migrated?.items[0]).toMatchObject({
      data: { query: "edited text" },
      status: "failed",
      retryCount: 2,
      errorMessage: "network down",
    });
    expect(migrated?.items[1].data.attachments).toEqual([
      { url: "/files/a.png", name: "a.png" },
    ]);
    expect(migrated?.paused).toBe(true);
    expect(migrated?.ownerTabId).toBe("target-tab");
  });

  it("serializes migration with SDK queue mutations so neither side loses data", async () => {
    const { locks, restore } = installWebLockMock();
    const fromScope = buildAgentScopedQueueSessionId("temp-race", "agent-a");
    const toScope = buildAgentScopedQueueSessionId("real-race", "agent-a");
    writeQueue(fromScope, {
      items: [{ id: "from", data: { query: "from" } }],
    });

    let releaseTarget!: () => void;
    let targetLocked!: () => void;
    const targetIsLocked = new Promise<void>((resolve) => {
      targetLocked = resolve;
    });
    const targetCanFinish = new Promise<void>((resolve) => {
      releaseTarget = resolve;
    });
    const targetMutation = locks.request(
      `${MUTATION_LOCK_PREFIX}:${toScope}`,
      { mode: "exclusive" },
      async () => {
        targetLocked();
        await targetCanFinish;
        writeQueue(toScope, {
          items: [{ id: "concurrent", data: { query: "concurrent" } }],
        });
      },
    );

    await targetIsLocked;
    const migration = migrateInputQueueStorage(fromScope, toScope);
    await Promise.resolve();
    releaseTarget();
    await Promise.all([targetMutation, migration]);
    restore();

    expect(readQueue(toScope)?.items.map((item) => item.id)).toEqual([
      "from",
      "concurrent",
    ]);
  });

  it("is idempotent and no-ops for an empty or identical source", async () => {
    const scope = buildAgentScopedQueueSessionId("same", "agent-a");
    writeQueue(scope, { items: [{ id: "one", data: { query: "one" } }] });

    await migrateInputQueueStorage(scope, scope);
    await migrateInputQueueStorage("missing", scope);
    await migrateInputQueueStorage("missing", scope);

    expect(readQueue(scope)?.items.map((item) => item.id)).toEqual(["one"]);
  });
});

describe("session id resolution across Agent switches", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.restoreAllMocks();
    sessionApi.setActiveAgent(`cleanup-${Date.now()}-${Math.random()}`);
  });

  afterEach(() => {
    sessionApi.onSessionIdResolved = null;
    vi.useRealTimers();
  });

  function mockListChatsForAgent(chatsByAgent: Record<string, ChatSpec[]>) {
    vi.spyOn(api, "listChats").mockImplementation(
      (_params?: { archived?: boolean }, options?: { agentId?: string }) =>
        Promise.resolve(
          options?.agentId ? chatsByAgent[options.agentId] ?? [] : [],
        ),
    );
  }

  it.each([
    ["switch after trigger", true],
    ["switch before trigger", false],
  ])(
    "resolves the owning Agent when users %s",
    async (_label, triggerFirst) => {
      const tempId = `1737000010-${String(triggerFirst)}`;
      const realId = `agent-a-real-${String(triggerFirst)}`;
      const resolved: Array<{
        tempId: string;
        realId: string;
        agentId?: string;
      }> = [];
      sessionApi.setActiveAgent("agent-a");
      sessionApi.onSessionIdResolved = (temp, real, agent) => {
        resolved.push({ tempId: temp, realId: real, agentId: agent });
      };
      mockListChatsForAgent({
        "agent-a": [buildChat(realId, tempId)],
        "agent-b": [],
      });

      if (triggerFirst) sessionApi.triggerResolve(tempId, "agent-a");
      sessionApi.setActiveAgent("agent-b");
      if (!triggerFirst) sessionApi.triggerResolve(tempId, "agent-a");
      await vi.runAllTimersAsync();

      expect(resolved).toContainEqual({
        tempId,
        realId,
        agentId: "agent-a",
      });
    },
  );

  it("does not notify until the owning Agent returns a matching chat", async () => {
    const tempId = "1737000012-empty";
    const resolved = vi.fn();
    sessionApi.setActiveAgent("agent-a");
    sessionApi.onSessionIdResolved = resolved;
    mockListChatsForAgent({ "agent-a": [] });

    sessionApi.triggerResolve(tempId, "agent-a");
    await vi.runAllTimersAsync();

    expect(resolved).not.toHaveBeenCalled();
  });
});
