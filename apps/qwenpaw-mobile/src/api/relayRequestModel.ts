import type { RelayOperation } from "@qwenpaw/api-contract";

export interface RelayRequestMapping {
  operation: RelayOperation;
  payload: Record<string, unknown>;
}

export function mapHttpRequestToRelay(
  path: string,
  method: string,
  body: unknown,
  agentId: string,
): RelayRequestMapping | null {
  const normalizedMethod = method.toUpperCase();
  const url = new URL(path, "https://relay.invalid");
  const segments = url.pathname.split("/").filter(Boolean);
  const payload = objectBody(body);
  const common = { ...payload, agent_id: agentId };
  if (normalizedMethod === "GET" && url.pathname === "/agents") {
    return { operation: "agent.list", payload: common };
  }
  if (normalizedMethod === "GET" && url.pathname === "/chats") {
    return {
      operation: "session.list",
      payload: {
        ...common,
        archived: url.searchParams.get("archived") === "true",
      },
    };
  }
  if (url.pathname === "/chats/groups") {
    if (normalizedMethod === "GET") {
      return {
        operation: "session.list",
        payload: { ...common, resource: "groups" },
      };
    }
    if (normalizedMethod === "POST") {
      return {
        operation: "session.create",
        payload: { ...common, resource: "groups" },
      };
    }
  }
  if (segments[0] === "chats" && segments.length === 2) {
    const chatId = decodeURIComponent(segments[1]);
    if (normalizedMethod === "GET") {
      return {
        operation: "session.get",
        payload: { ...common, chat_id: chatId },
      };
    }
    if (normalizedMethod === "DELETE") {
      return {
        operation: "session.delete",
        payload: { ...common, chat_id: chatId },
      };
    }
    if (normalizedMethod === "PUT") {
      return {
        operation: "session.update",
        payload: { ...common, chat_id: chatId },
      };
    }
  }
  if (
    segments[0] === "chats" &&
    segments[1] === "groups" &&
    segments.length === 3
  ) {
    const groupId = decodeURIComponent(segments[2]);
    if (normalizedMethod === "PUT") {
      return {
        operation: "session.update",
        payload: { ...common, resource: "groups", target_group_id: groupId },
      };
    }
    if (normalizedMethod === "DELETE") {
      return {
        operation: "session.delete",
        payload: { ...common, resource: "groups", target_group_id: groupId },
      };
    }
  }
  if (normalizedMethod === "POST" && url.pathname === "/chats") {
    return { operation: "session.create", payload: common };
  }
  if (
    normalizedMethod === "POST" &&
    segments[0] === "chats" &&
    segments.length === 3 &&
    ["archive", "unarchive"].includes(segments[2])
  ) {
    return {
      operation: "session.archive",
      payload: {
        ...common,
        action: segments[2],
        chat_id: decodeURIComponent(segments[1]),
      },
    };
  }
  if (normalizedMethod === "POST" && url.pathname === "/console/chat/stop") {
    return {
      operation: "run.cancel",
      payload: { ...common, chat_id: url.searchParams.get("chat_id") ?? "" },
    };
  }
  if (
    normalizedMethod === "POST" &&
    ["/approval/approve", "/approval/deny"].includes(url.pathname)
  ) {
    return {
      operation: "approval.resolve",
      payload: {
        ...common,
        decision: url.pathname.endsWith("approve") ? "approve" : "deny",
      },
    };
  }
  return null;
}

function objectBody(value: unknown): Record<string, unknown> {
  if (typeof value !== "string" || !value) return {};
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}
