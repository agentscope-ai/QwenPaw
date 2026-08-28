import { fetch as expoFetch } from "expo/fetch";
import type {
  MobilePushSubscriptionRequest,
  MobilePushSubscriptionResponse,
} from "@qwenpaw/api-contract";

import {
  SseParser,
  StreamEventClassifier,
  streamError,
  type StreamDelta,
} from "./sse";
import { requestWithPlatformGateway } from "./platformGateway";
import {
  requiresQwenPawCredentials,
  type QwenPawAuthStatus,
} from "./qwenPawAuthModel";
import { availableAgents } from "./compatibility";
import type {
  ActiveModelInfo,
  AgentSummary,
  ApprovalLevel,
  ChatGroup,
  ChatHistory,
  ChatSpec,
  Connection,
  ContentItem,
  LoopModeInfo,
  LoopStatus,
  ModelSlotOverride,
  PendingApproval,
  ProviderInfo,
  RunningConfig,
  UploadResult,
} from "./types";

export class QwenPawClient {
  constructor(
    private readonly connection: Connection,
    private readonly signal?: AbortSignal,
  ) {}

  async verify(): Promise<void> {
    if (!this.connection.token) {
      const status = await qwenPawAuthStatus(
        this.connection.baseUrl,
        this.connection.source,
        false,
        undefined,
        this.signal,
      );
      if (status && !requiresQwenPawCredentials(status)) return;
    }
    await this.request("/auth/verify");
  }

  async revokeToken(): Promise<void> {
    if (!this.connection.token) return;
    await this.request("/auth/revoke-token", {
      method: "POST",
      body: JSON.stringify({}),
    });
  }

  async listAgents(): Promise<AgentSummary[]> {
    const response = await this.request<{ agents: AgentSummary[] }>("/agents");
    return availableAgents(response.agents ?? []);
  }

  async listChats(archived = false): Promise<ChatSpec[]> {
    return this.request<ChatSpec[]>(`/chats?archived=${String(archived)}`);
  }

  async listChatGroups(): Promise<ChatGroup[]> {
    return this.request<ChatGroup[]>("/chats/groups");
  }

  async createChatGroup(name: string): Promise<ChatGroup> {
    return this.request<ChatGroup>("/chats/groups", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  async updateChatGroup(groupId: string, name: string): Promise<ChatGroup> {
    return this.request<ChatGroup>(
      `/chats/groups/${encodeURIComponent(groupId)}`,
      { method: "PUT", body: JSON.stringify({ name }) },
    );
  }

  async deleteChatGroup(groupId: string): Promise<void> {
    await this.request(`/chats/groups/${encodeURIComponent(groupId)}`, {
      method: "DELETE",
    });
  }

  async updateChat(
    chatId: string,
    update: { name?: string; pinned?: boolean; group_id?: string | null },
  ): Promise<ChatSpec> {
    return this.request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "PUT",
      body: JSON.stringify(update),
    });
  }

  async archiveChat(chatId: string): Promise<ChatSpec> {
    return this.request<ChatSpec>(
      `/chats/${encodeURIComponent(chatId)}/archive`,
      { method: "POST" },
    );
  }

  async unarchiveChat(chatId: string): Promise<ChatSpec> {
    return this.request<ChatSpec>(
      `/chats/${encodeURIComponent(chatId)}/unarchive`,
      { method: "POST" },
    );
  }

  async inspectModule(path: string): Promise<unknown> {
    return this.request(path);
  }

  async mutateModule<T = unknown>(
    path: string,
    method: "POST" | "PUT" | "PATCH" | "DELETE",
    body?: unknown,
  ): Promise<T> {
    return this.request<T>(path, {
      method,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  }

  async uploadModule<T = unknown>(
    path: string,
    files: {
      field: string;
      uri: string;
      name: string;
      mimeType?: string | null;
    }[],
  ): Promise<T> {
    const form = new FormData();
    files.forEach((file) => {
      form.append(file.field, {
        uri: file.uri,
        name: file.name,
        type: file.mimeType ?? "application/octet-stream",
      } as unknown as Blob);
    });
    return this.request<T>(path, { method: "POST", body: form });
  }

  async downloadModule(path: string): Promise<{
    bytes: Uint8Array;
    contentType: string;
  }> {
    const request = () =>
      fetch(this.url(path), {
        headers: this.headers(),
        credentials: "include",
      });
    const response = await requestWithPlatformGateway(
      this.connection.baseUrl,
      this.connection.source,
      request,
      false,
      this.connection.platformAccessPath,
    );
    if (!response.ok) throw await responseError(response);
    return {
      bytes: new Uint8Array(await response.arrayBuffer()),
      contentType:
        response.headers.get("content-type") || "application/octet-stream",
    };
  }

  async createBackup(
    body: Record<string, unknown>,
    onProgress?: (percent: number) => void,
  ): Promise<Record<string, unknown>> {
    const headers = this.headers();
    headers.set("Content-Type", "application/json");
    const request = () =>
      fetch(this.url("/backups/stream"), {
        method: "POST",
        body: JSON.stringify(body),
        headers,
        credentials: "include",
      });
    const response = await requestWithPlatformGateway(
      this.connection.baseUrl,
      this.connection.source,
      request,
      false,
      this.connection.platformAccessPath,
    );
    if (!response.ok || !response.body) throw await responseError(response);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    let backup: Record<string, unknown> | null = null;
    const consume = (event: { data: string }) => {
      const payload = JSON.parse(event.data) as Record<string, unknown>;
      if (typeof payload.percent === "number") onProgress?.(payload.percent);
      if (payload.type === "error") {
        throw new Error(String(payload.message || "创建备份失败"));
      }
      if (
        payload.type === "done" &&
        payload.meta &&
        typeof payload.meta === "object"
      ) {
        backup = payload.meta as Record<string, unknown>;
      }
    };
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true })).forEach(consume);
    }
    parser.finish().forEach(consume);
    if (!backup) throw new Error("QwenPaw 没有返回已完成的备份。");
    return backup;
  }

  async getRunningConfig(): Promise<RunningConfig> {
    return this.request<RunningConfig>("/workspace/running-config");
  }

  async listProviders(): Promise<ProviderInfo[]> {
    return this.request<ProviderInfo[]>("/models");
  }

  async getActiveModel(agentId: string): Promise<ActiveModelInfo> {
    const query = new URLSearchParams({
      scope: "effective",
      agent_id: agentId,
    });
    return this.request<ActiveModelInfo>(`/models/active?${query.toString()}`);
  }

  async setAgentActiveModel(
    agentId: string,
    model: ModelSlotOverride,
  ): Promise<ActiveModelInfo> {
    return this.request<ActiveModelInfo>("/models/active", {
      method: "PUT",
      body: JSON.stringify({
        ...model,
        scope: "agent",
        agent_id: agentId,
      }),
    });
  }

  async listLoopModes(): Promise<LoopModeInfo[]> {
    return this.request<LoopModeInfo[]>("/loops");
  }

  async getLoopStatus(chatId: string, sessionId: string): Promise<LoopStatus> {
    const query = new URLSearchParams({
      chat_id: chatId,
      session_id: sessionId,
    });
    return this.request<LoopStatus>(`/loops/status?${query.toString()}`);
  }

  async listApprovals(): Promise<PendingApproval[]> {
    const response = await this.request<{
      pending_approvals: PendingApproval[];
    }>("/console/push-messages");
    return response.pending_approvals;
  }

  async upsertMobilePushSubscription(
    payload: MobilePushSubscriptionRequest,
  ): Promise<MobilePushSubscriptionResponse> {
    return this.request<MobilePushSubscriptionResponse>(
      "/console/mobile-push/subscriptions",
      { method: "POST", body: JSON.stringify(payload) },
    );
  }

  async getMobilePushSubscription(
    installationId: string,
    workspaceKey: string,
  ): Promise<MobilePushSubscriptionResponse | null> {
    const query = new URLSearchParams({
      installation_id: installationId,
      workspace_key: workspaceKey,
    });
    return this.request<MobilePushSubscriptionResponse | null>(
      `/console/mobile-push/subscriptions/current?${query.toString()}`,
    );
  }

  async deleteMobilePushSubscription(
    installationId: string,
    workspaceKey: string,
  ): Promise<void> {
    const query = new URLSearchParams({
      installation_id: installationId,
      workspace_key: workspaceKey,
    });
    await this.request(
      `/console/mobile-push/subscriptions/current?${query.toString()}`,
      { method: "DELETE" },
    );
  }

  async approve(
    approval: PendingApproval,
    scope: "exact" | "similar" = "exact",
  ): Promise<void> {
    await this.request("/approval/approve", {
      method: "POST",
      body: JSON.stringify({
        request_id: approval.request_id,
        session_id: approval.root_session_id,
        user_id: "mobile",
        scope,
      }),
    });
  }

  async deny(approval: PendingApproval, reason = "User denied"): Promise<void> {
    await this.request("/approval/deny", {
      method: "POST",
      body: JSON.stringify({
        request_id: approval.request_id,
        session_id: approval.root_session_id,
        user_id: "mobile",
        reason,
      }),
    });
  }

  async getChat(chatId: string): Promise<ChatHistory> {
    return this.request<ChatHistory>(`/chats/${encodeURIComponent(chatId)}`);
  }

  async createChat(name = "New Chat"): Promise<ChatSpec> {
    const sessionId = `mobile:${createId()}`;
    return this.request<ChatSpec>("/chats", {
      method: "POST",
      body: JSON.stringify({
        name,
        session_id: sessionId,
        user_id: "mobile",
        channel: "console",
      }),
    });
  }

  async deleteChat(chatId: string): Promise<void> {
    await this.request(`/chats/${encodeURIComponent(chatId)}`, {
      method: "DELETE",
    });
  }

  async stopChat(chatId: string): Promise<void> {
    await this.request(
      `/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`,
      { method: "POST" },
    );
  }

  async upload(file: {
    uri: string;
    name: string;
    mimeType?: string | null;
  }): Promise<UploadResult> {
    const form = new FormData();
    form.append("file", {
      uri: file.uri,
      name: file.name,
      type: file.mimeType ?? "application/octet-stream",
    } as unknown as Blob);
    return this.request<UploadResult>("/console/upload", {
      method: "POST",
      body: form,
    });
  }

  async streamChat(options: {
    sessionId: string;
    text: string;
    attachments?: ContentItem[];
    approvalLevel?: ApprovalLevel;
    modelSlotOverride?: ModelSlotOverride | null;
    signal: AbortSignal;
    onDelta: (delta: StreamDelta) => void;
  }): Promise<void> {
    const request = () =>
      expoFetch(this.url("/console/chat"), {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          input: [
            {
              role: "user",
              content: [
                ...(options.text ? [{ type: "text", text: options.text }] : []),
                ...(options.attachments ?? []),
              ],
            },
          ],
          session_id: options.sessionId,
          user_id: "mobile",
          channel: "console",
          stream: true,
          ...(options.modelSlotOverride
            ? { model_slot_override: options.modelSlotOverride }
            : {}),
          ...(options.approvalLevel
            ? { request_context: { approval_level: options.approvalLevel } }
            : {}),
        }),
        credentials: "include",
        signal: options.signal,
      });
    const response = await requestWithPlatformGateway(
      this.connection.baseUrl,
      this.connection.source,
      request,
      false,
      this.connection.platformAccessPath,
    );
    if (!response.ok || !response.body) {
      throw await responseError(response);
    }
    await consumeChatStream(response, options.onDelta);
  }

  async reconnectChat(options: {
    sessionId: string;
    signal: AbortSignal;
    onDelta: (delta: StreamDelta) => void;
  }): Promise<void> {
    const request = () =>
      expoFetch(this.url("/console/chat"), {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          reconnect: true,
          session_id: options.sessionId,
          user_id: "mobile",
          channel: "console",
        }),
        credentials: "include",
        signal: options.signal,
      });
    const response = await requestWithPlatformGateway(
      this.connection.baseUrl,
      this.connection.source,
      request,
      false,
      this.connection.platformAccessPath,
    );
    if (!response.ok || !response.body) {
      throw await responseError(response);
    }
    await consumeChatStream(response, options.onDelta);
  }

  private async request<T = unknown>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const headers = this.headers(init.headers);
    if (init.body && !(init.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    const request = () =>
      fetch(this.url(path), {
        ...init,
        headers,
        credentials: "include",
        signal: init.signal ?? this.signal,
      });
    const response = await requestWithPlatformGateway(
      this.connection.baseUrl,
      this.connection.source,
      request,
      false,
      this.connection.platformAccessPath,
    );
    if (!response.ok) throw await responseError(response);
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  private headers(extra?: HeadersInit): Headers {
    const headers = new Headers(extra);
    if (this.connection.token) {
      headers.set("Authorization", `Bearer ${this.connection.token}`);
    }
    headers.set("X-Agent-Id", this.connection.agentId || "default");
    return headers;
  }

  private url(path: string): string {
    return `${this.connection.baseUrl}/api${path}`;
  }
}

export async function loginQwenPaw(
  baseUrl: string,
  username: string,
  password: string,
  source: Connection["source"] = "private",
  platformAccessPath?: string,
  signal?: AbortSignal,
): Promise<Connection> {
  const status = await qwenPawAuthStatus(
    baseUrl,
    source,
    true,
    platformAccessPath,
    signal,
  );
  if (status && !requiresQwenPawCredentials(status)) {
    return {
      baseUrl,
      token: "",
      username: "",
      agentId: "default",
      source,
      platformAccessPath,
    };
  }
  if (
    status &&
    requiresQwenPawCredentials(status) &&
    (!username.trim() || !password)
  ) {
    throw new QwenPawCredentialsRequiredError();
  }
  const request = () =>
    fetch(`${baseUrl}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, expires_in: 0 }),
      credentials: "include",
      signal,
    });
  const response = await requestWithPlatformGateway(
    baseUrl,
    source,
    request,
    false,
    platformAccessPath,
  );
  if (!response.ok) throw await responseError(response);
  const data = (await response.json()) as { token: string; username: string };
  return {
    baseUrl,
    token: data.token,
    username: data.username,
    agentId: "default",
    source,
    platformAccessPath,
  };
}

export class QwenPawCredentialsRequiredError extends Error {
  constructor() {
    super("检测到 QwenPaw 独立认证状态，需要额外处理。");
    this.name = "QwenPawCredentialsRequiredError";
  }
}

async function qwenPawAuthStatus(
  baseUrl: string,
  source: Connection["source"],
  forceGateway = false,
  platformAccessPath?: string,
  signal?: AbortSignal,
): Promise<QwenPawAuthStatus | null> {
  const request = () =>
    fetch(`${baseUrl}/api/auth/status`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "include",
      signal,
    });
  const response = await requestWithPlatformGateway(
    baseUrl,
    source,
    request,
    forceGateway && source === "platform",
    platformAccessPath,
  );
  if (!response.ok) {
    await response.body?.cancel().catch(() => undefined);
    return null;
  }
  return response.json() as Promise<QwenPawAuthStatus>;
}

export async function redeemPairing(
  baseUrl: string,
  ticket: string,
): Promise<Connection> {
  const response = await fetch(`${baseUrl}/api/auth/pairing/redeem`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket }),
  });
  if (!response.ok) throw await responseError(response);
  const data = (await response.json()) as { token: string; username: string };
  return {
    baseUrl,
    token: data.token,
    username: data.username,
    agentId: "default",
    source: "private",
  };
}

export function mediaSource(
  connection: Connection,
  rawUrl: string,
): { uri: string; headers?: Record<string, string> } {
  if (
    rawUrl.startsWith("http://") ||
    rawUrl.startsWith("https://") ||
    rawUrl.startsWith("data:")
  )
    return { uri: rawUrl };
  const path = rawUrl.startsWith("file://") ? rawUrl.slice(7) : rawUrl;
  const previewPath = path.startsWith("/") ? path : `/${path}`;
  const headers: Record<string, string> = {
    "X-Agent-Id": connection.agentId || "default",
  };
  if (connection.token) headers.Authorization = `Bearer ${connection.token}`;
  return {
    uri: encodeURI(`${connection.baseUrl}/api/files/preview${previewPath}`),
    headers,
  };
}

async function consumeChatStream(
  response: Response,
  onDelta: (delta: StreamDelta) => void,
): Promise<void> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  const classifier = new StreamEventClassifier();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      const failure = streamError(event);
      if (failure) throw new Error(failure);
      const delta = classifier.consume(event);
      if (delta) onDelta(delta);
    }
  }
  for (const event of parser.finish()) {
    const failure = streamError(event);
    if (failure) throw new Error(failure);
    const delta = classifier.consume(event);
    if (delta) onDelta(delta);
  }
}

async function responseError(response: Response): Promise<Error> {
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = (await response.json()) as {
      detail?: string;
      message?: string;
    };
    message = body.detail || body.message || message;
  } catch {
    // Keep the HTTP status when the response is not JSON.
  }
  return new Error(message);
}

function createId(): string {
  return `${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}
