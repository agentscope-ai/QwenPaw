// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WhisperSpeechButton from "./index";

const getUserMedia = vi.hoisted(() => vi.fn());

vi.mock("@agentscope-ai/design", () => ({
  IconButton: ({
    icon,
    ...props
  }: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: ReactNode }) => (
    <button {...props}>{icon}</button>
  ),
}));

vi.mock("antd", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => children,
  message: { error: vi.fn(), warning: vi.fn() },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "chat.speech.startRecording": "Start voice recording",
        "chat.speech.stopRecording": "Stop recording",
        "chat.speech.transcribing": "Transcribing",
      })[key] ?? key,
  }),
}));

vi.mock("@/api/modules/agent", () => ({
  agentApi: { transcribeAudio: vi.fn() },
  TranscriptionError: class TranscriptionError extends Error {},
}));

vi.mock("@/stores/uploadLimitStore", () => ({
  useUploadLimitStore: { getState: () => ({ uploadMaxSizeMb: null }) },
}));

class MediaRecorderMock {
  static isTypeSupported = () => true;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  start() {}

  stop() {}
}

describe("WhisperSpeechButton", () => {
  beforeEach(() => {
    getUserMedia.mockReset();
    getUserMedia.mockResolvedValue({ getTracks: () => [] });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    vi.stubGlobal("MediaRecorder", MediaRecorderMock);
  });

  it("uses localized action names for idle and recording states", async () => {
    render(<WhisperSpeechButton onTranscription={vi.fn()} />);
    const start = screen.getByRole("button", {
      name: "Start voice recording",
    });

    fireEvent.click(start);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Stop recording" }),
      ).toBeTruthy(),
    );
  });
});
