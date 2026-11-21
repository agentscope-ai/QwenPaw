import { getApiUrl } from "./config";
import { request, type RequestOptions } from "./request";
import {
  withAgentRequestContext,
  type AgentRequestContext,
} from "./modules/agentRequestContext";

const FILE_API =
  /^\/api\/(?:agents\/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\/)?(?:files\/preview\/|console\/(?:artifacts\/[^/]+\/download|attachments\/[^/]+(?:\/download)?|personal-library\/documents\/[^/]+\/download)(?:$|\?)|workspace\/file-download(?:$|\?))/;

/** Only trusted file API origins receive the current account's credentials. */
export function protectedFileApiPath(rawUrl: string): string | null {
  try {
    const base = new URL(getApiUrl("/"), window.location.href);
    const url = new URL(rawUrl, window.location.href);
    if (url.origin !== base.origin && url.origin !== window.location.origin)
      return null;
    if (!FILE_API.test(url.pathname + url.search)) return null;
    // Historical URLs can contain an expired token. The request layer always
    // supplies the current token and handles refresh without changing identity.
    url.searchParams.delete("token");
    return url.pathname.slice("/api".length) + url.search;
  } catch {
    return null;
  }
}

export async function readFileResponse<T>(
  url: string,
  context: AgentRequestContext | undefined,
  readResponse: (response: Response) => Promise<T>,
  options: RequestOptions = {},
): Promise<T> {
  const path = protectedFileApiPath(url);
  if (path) {
    // An explicit historical Agent URL carries its own scope. A later menu
    // selection must not add a conflicting X-Agent-Id to that request.
    const scopedAgent = path.match(
      /^\/agents\/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\//,
    )?.[1];
    const fileContext = scopedAgent
      ? { ...context, agentId: scopedAgent }
      : context;
    return request<T>(path, {
      ...withAgentRequestContext(options, fileContext),
      readResponse,
    });
  }
  const external = new URL(url, window.location.href);
  if (!["https:", "http:", "blob:", "data:"].includes(external.protocol))
    throw new Error("文件链接无效，请从当前对话重新打开");
  // External media never receives Authorization or account/agent headers.
  const response = await fetch(url, {
    signal: options.signal,
    credentials: "omit",
  });
  if (!response.ok) throw new Error("文件加载失败，请确认文件仍可访问");
  return readResponse(response);
}
