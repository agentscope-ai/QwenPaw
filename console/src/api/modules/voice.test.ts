import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { voiceApi, transcriptionErrorKey, TranscriptionError } from "./voice";
import { captureVoiceScope } from "../voiceScope";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
const response = (data: unknown) =>
  new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
beforeEach(() => {
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "a", platform_role: "member" } as never,
  });
  useAgentStore.setState({
    selectedAgent: "agent-a",
    agents: [{ id: "agent-a", enabled: true, access_role: "user" }] as never,
  });
});
afterEach(() => vi.unstubAllGlobals());
it("reads only safe status for a member", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      response({ enabled: true, available: true, reason: null }),
    );
  vi.stubGlobal("fetch", fetch);
  expect(await voiceApi.status(captureVoiceScope())).toEqual({
    enabled: true,
    available: true,
    reason: null,
  });
  expect(fetch.mock.calls[0][0]).toContain("/workspace/transcription-status");
  expect(() => voiceApi.getSettings(captureVoiceScope())).toThrow(
    TranscriptionError,
  );
  expect(() =>
    voiceApi.test(new File(["x"], "x.wav"), captureVoiceScope()),
  ).toThrow(TranscriptionError);
  expect(fetch).toHaveBeenCalledOnce();
});
it.each(["owner", "collaborator", "user"])(
  "allows %s consumption and omits an uncreated conversation",
  async (access_role) => {
    useAgentStore.setState({
      agents: [{ id: "agent-a", enabled: true, access_role }] as never,
    });
    const fetch = vi.fn().mockResolvedValue(response({ text: "draft" }));
    vi.stubGlobal("fetch", fetch);
    await voiceApi.transcribe(
      new Blob(["x"], { type: "audio/webm;codecs=opus" }),
      captureVoiceScope(),
    );
    const form = fetch.mock.calls[0][1].body;
    expect(form.get("file").name).toBe("recording.webm");
    expect(form.has("conversation_id")).toBe(false);
  },
);
it("forbids historical Agent consumption and expired scopes", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const scope = captureVoiceScope();
  useAgentStore.setState({
    agents: [
      {
        id: "agent-a",
        enabled: true,
        access_role: "user",
        historical_read_only: true,
      },
    ] as never,
  });
  expect(() => voiceApi.status(captureVoiceScope())).toThrow(
    TranscriptionError,
  );
  await expect(
    voiceApi.transcribe(new File(["x"], "x.wav"), scope),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(fetch).not.toHaveBeenCalled();
});
it.each([
  ["TRANSCRIPTION_NOT_READY", "chat.speech.notReady"],
  ["TRANSCRIPTION_BUSY", "chat.speech.busy"],
  ["EMPTY_TRANSCRIPT", "chat.speech.emptyText"],
  ["UPSTREAM_TIMEOUT", "chat.speech.transcriptionTimeout"],
])(
  "maps the frozen backend error %s without showing upstream details",
  (code, key) => {
    expect(
      transcriptionErrorKey(new TranscriptionError(503, "private", code)),
    ).toBe(key);
  },
);
