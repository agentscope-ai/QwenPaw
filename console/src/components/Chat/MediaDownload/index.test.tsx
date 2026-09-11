// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { downloadFileFromUrl, messageError } = vi.hoisted(() => ({
  downloadFileFromUrl: vi.fn(),
  messageError: vi.fn(),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: messageError } }),
}));

vi.mock("../../../api/authHeaders", () => ({
  buildAuthHeaders: () => ({ Authorization: "Bearer token" }),
}));

vi.mock("../../../utils/downloadFileFromUrl", () => ({
  DownloadCancelledError: class DownloadCancelledError extends Error {},
  downloadFileFromUrl,
}));

vi.mock("@agentscope-ai/chat/lib/DefaultCards/Audios", () => ({
  default: () => (
    <div data-testid="audio-card">
      <div className="spark-media-player-controller">
        <button type="button" data-testid="play-button">
          play
        </button>
        <button type="button" data-testid="volume-button">
          volume
        </button>
        <span>00:00</span>
        <div className="spark-media-progress-container" />
        <span>00:00</span>
      </div>
    </div>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { AudioDownload, DownloadableAudios } from ".";
import { DownloadCancelledError } from "../../../utils/downloadFileFromUrl";
import { mediaFilenameFromUrl } from "./utils";
import styles from "./index.module.less";

describe("mediaFilenameFromUrl", () => {
  it("extracts and decodes the filename without query parameters", () => {
    expect(
      mediaFilenameFromUrl(
        "/api/files/preview/recording%20one.mp3?token=test",
        "audio",
      ),
    ).toBe("recording one.mp3");
  });

  it("uses the fallback for inline media URLs", () => {
    expect(mediaFilenameFromUrl("data:audio/mp3;base64,abc", "audio.mp3")).toBe(
      "audio.mp3",
    );
  });
});

describe("AudioDownload", () => {
  beforeEach(() => {
    downloadFileFromUrl.mockReset();
    downloadFileFromUrl.mockResolvedValue(undefined);
    messageError.mockReset();
  });

  it("downloads with an inferred filename and auth headers", async () => {
    render(
      <AudioDownload url="/api/files/preview/recording.mp3">
        <div>audio</div>
      </AudioDownload>,
    );

    fireEvent.click(screen.getByRole("button", { name: "common.download" }));

    await waitFor(() => {
      expect(downloadFileFromUrl).toHaveBeenCalledWith(
        "/api/files/preview/recording.mp3",
        "recording.mp3",
        {
          headers: { Authorization: "Bearer token" },
          errorMessage: "files.downloadFailed",
        },
      );
    });
  });

  it("does not report a cancelled native save dialog as an error", async () => {
    downloadFileFromUrl.mockRejectedValue(new DownloadCancelledError());
    render(
      <AudioDownload url="/api/files/preview/recording.mp3">
        <div>audio</div>
      </AudioDownload>,
    );

    fireEvent.click(screen.getByRole("button", { name: "common.download" }));

    await waitFor(() => {
      expect(downloadFileFromUrl).toHaveBeenCalledOnce();
    });
    expect(messageError).not.toHaveBeenCalled();
  });

  it("does not send console auth headers to external media URLs", async () => {
    render(
      <AudioDownload url="https://cdn.example.com/recording.mp3">
        <div>audio</div>
      </AudioDownload>,
    );

    fireEvent.click(screen.getByRole("button", { name: "common.download" }));

    await waitFor(() => {
      expect(downloadFileFromUrl).toHaveBeenCalledWith(
        "https://cdn.example.com/recording.mp3",
        "recording.mp3",
        {
          headers: {},
          errorMessage: "files.downloadFailed",
        },
      );
    });
  });

  it("puts the audio download action inside the player controls", () => {
    render(<DownloadableAudios data={[{ src: "/recording.mp3" }]} />);

    const controller = document.querySelector(".spark-media-player-controller");
    const downloadButton = screen.getByRole("button", {
      name: "common.download",
    });

    expect(controller).toContainElement(downloadButton);
    expect(downloadButton).toHaveClass(styles.downloadButton);
    expect(downloadButton.parentElement?.previousElementSibling).toBe(
      screen.getByTestId("play-button"),
    );
    expect(downloadButton.parentElement?.nextElementSibling).toBe(
      screen.getByTestId("volume-button"),
    );
  });
});
