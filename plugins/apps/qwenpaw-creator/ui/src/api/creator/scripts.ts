import type { TimelineScriptImportResult } from "@/contracts/creator";
import { creatorRequest, newClientId } from "./client";

const scriptImportPath = (projectId: string, timelineId: string) =>
  `/projects/${encodeURIComponent(projectId)}/timelines/${encodeURIComponent(
    timelineId,
  )}/script-import`;

/**
 * 剧本直登：把用户写好的剧本正文（UTF-8 文本）直接登记为该集当前剧本版本。
 *
 * 服务端读取正文并落 `timeline_script` 版本，不创建 ProjectSource，因此不会
 * 唤醒素材理解链路；重复提交同一内容不会新增版本。
 *
 * `idempotencyKey` 只标识“本次导入请求”，与正文内容无关：每次重新选用
 * 旧稿都是一次新编辑（用新的键），而同一请求的网络重试复用同一个键即可被
 * 服务端识别并去重。不传则每次调用生成一个新键。
 */
export function importTimelineScript(
  projectId: string,
  timelineId: string,
  input: { file: File } | { content: string; name?: string },
  idempotencyKey: string = newClientId("script-import"),
): Promise<TimelineScriptImportResult> {
  const headers = { "Idempotency-Key": idempotencyKey };
  if ("file" in input) {
    const form = new FormData();
    form.append("file", input.file, input.file.name);
    return creatorRequest(scriptImportPath(projectId, timelineId), {
      method: "POST",
      headers,
      body: form,
    });
  }
  return creatorRequest(scriptImportPath(projectId, timelineId), {
    method: "POST",
    headers,
    body: JSON.stringify({
      content: input.content,
      name: input.name ?? "",
    }),
  });
}
