import { request } from "../../api/request";

export type FileReferenceSource = "temporary" | "personal_library" | "agent_profile" | "artifact";
export interface ChatFileReference { source: FileReferenceSource; id: string }
export interface ChatFileCandidate extends ChatFileReference { name: string; relative_path: string }
export const sourceLabels: Record<FileReferenceSource, string> = {
  temporary: "临时文件", personal_library: "个人资料库", agent_profile: "Agent资料", artifact: "产物",
};

export function listChatFileCandidates(conversationId?: string) {
  return request<ChatFileCandidate[]>(`/console/file-references${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`);
}

export function encodeFileMention(file: Pick<ChatFileCandidate, "source" | "id" | "name">): string {
  const name = file.name.replace(/\\/g, "\\\\").replace(/\]/g, "\\]");
  return `@[${name}](chat-file:${file.source}:${encodeURIComponent(file.id)})`;
}

export function rewriteFileMentions(input: Array<Record<string, unknown>>) {
  const references: ChatFileReference[] = [];
  let lastUser = -1;
  input.forEach((message, index) => { if (message.role === "user") lastUser = index; });
  const rewrite = (text: string) => text.replace(
    /@\[((?:\\.|[^\]])+)\]\(chat-file:(temporary|personal_library|agent_profile|artifact):([^\s)]+)\)/g,
    (_raw, label: string, source: FileReferenceSource, id: string) => {
      let decoded: string;
      try { decoded = decodeURIComponent(id); } catch { return _raw; }
      if (!references.some(file => file.source === source && file.id === decoded)) references.push({source, id: decoded});
      return `@${label.replace(/\\([\\\]])/g, "$1")}`;
    },
  );
  const rewritten = input.map((message, index) => {
    if (index !== lastUser) return message;
    const displayText = typeof message.content === "string" ? message.content :
      Array.isArray(message.content) ? message.content.filter(part => part?.type === "text").map(part => part.text || "").join("\n") : "";
    message = {...message, metadata: {...(message.metadata as Record<string, unknown> || {}), qwenpaw_display_text: displayText}};
    if (typeof message.content === "string") return {...message, content: rewrite(message.content)};
    if (!Array.isArray(message.content)) return message;
    return {...message, content: message.content.map(part =>
      part && part.type === "text" && typeof part.text === "string" ? {...part, text: rewrite(part.text)} : part)};
  });
  return {input: rewritten, references};
}
