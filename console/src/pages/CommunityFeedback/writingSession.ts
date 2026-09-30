import { getApiUrl } from "@/api/config";
import type { DiagnosticEvidence } from "@/api/modules/communityReport";
import type { DraftContent } from "./postDrafts";
import type { ReportImage } from "./useReportScreenshots";

export interface AssistantSession {
  language: "auto" | "zh" | "en";
  writingStyle: "auto" | "concise" | "detailed";
  history: { role: "user" | "assistant"; content: string }[];
  result: string;
  writingAgent?: string;
  agent?: string;
  session: string;
  minutes: number;
  evidence: DiagnosticEvidence[];
  warnings: string[];
  publicImages: Record<string, string>;
  insertedImages: Record<string, string>;
}
export interface WritingSession extends DraftContent {
  id?: string;
  draftId?: string;
  initialType: "question" | "discussion";
  general: boolean;
  assisting: boolean;
  assistInitialized: boolean;
  assistWidth: number;
  mobilePane: string;
  preview: boolean;
  addingResources: boolean;
  images: ReportImage[];
  assistant?: AssistantSession;
}

// Window-lifetime state shared by web and desktop routes. Never persist private
// writing conversations, screenshots or logs to localStorage or Platform drafts.
const sessions = new Map<string, WritingSession>();
export function writingSessionKey(account: string, identity: string) {
  return JSON.stringify([getApiUrl("/community"), account, identity]);
}
export function getWritingSession(key: string) {
  return sessions.get(key);
}
export function saveWritingSession(key: string, value: WritingSession) {
  sessions.delete(key);
  sessions.set(key, value);
  if (sessions.size > 10) sessions.delete(sessions.keys().next().value!);
}
export function removeWritingSession(key: string) {
  sessions.delete(key);
}
export function clearWritingSessions() {
  sessions.clear();
}
export function latestWritingSession(account: string) {
  const prefix =
    JSON.stringify([getApiUrl("/community"), account]).slice(0, -1) + ",";
  return [...sessions.entries()]
    .reverse()
    .find(
      ([key, value]) =>
        key.startsWith(prefix) &&
        value.general &&
        (value.title ||
          value.content ||
          value.instructions ||
          value.assistant?.history.length ||
          value.images.length),
    )?.[1];
}

export function removeWritingDraftSessions(account: string, id: string) {
  const prefix =
    JSON.stringify([getApiUrl("/community"), account]).slice(0, -1) + ",";
  for (const [key, value] of sessions) {
    if (key.startsWith(prefix) && value.id === id) sessions.delete(key);
  }
}
