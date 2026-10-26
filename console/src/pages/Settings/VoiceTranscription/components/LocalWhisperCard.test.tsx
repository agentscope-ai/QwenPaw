import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { LocalWhisperStatus } from "../useVoiceTranscription";
import { LocalWhisperCard } from "./LocalWhisperCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const ready: LocalWhisperStatus = {
  available: true,
  plugin_installed: true,
  plugin_enabled: true,
  plugin_status: "active",
  state: "ready",
  whisper_installed: true,
  ffmpeg_installed: true,
};

function Location() {
  const location = useLocation();
  return (
    <output>
      {location.pathname}
      {location.search}
    </output>
  );
}

function show(status: Partial<LocalWhisperStatus> = {}) {
  const onInstall = vi.fn(),
    onEnable = vi.fn();
  render(
    <MemoryRouter>
      <LocalWhisperCard
        status={{ ...ready, ...status }}
        onInstall={onInstall}
        onEnable={onEnable}
      />
      <Location />
    </MemoryRouter>,
  );
  return { onInstall, onEnable };
}

describe("Local Whisper plugin and dependency status", () => {
  it("offers installation even when dependencies remain after uninstall", () => {
    const { onInstall } = show({
      available: false,
      plugin_installed: false,
      plugin_enabled: false,
      plugin_status: "missing",
      state: "missing",
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "localWhisperState_missing",
    );
    expect(
      screen.getAllByText(
        "voiceTranscription.localWhisperDependency_installed",
      ),
    ).toHaveLength(2);
    expect(screen.getByRole("alert")).not.toHaveClass("ant-alert-success");
    fireEvent.click(
      screen.getByRole("button", {
        name: "voiceTranscription.localWhisperInstall",
      }),
    );
    expect(onInstall).toHaveBeenCalledOnce();
  });

  it("enables a disabled plugin without reinstalling it", () => {
    const { onEnable, onInstall } = show({
      available: false,
      plugin_enabled: false,
      plugin_status: "inactive",
      state: "disabled",
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "voiceTranscription.localWhisperEnable",
      }),
    );
    expect(onEnable).toHaveBeenCalledOnce();
    expect(onInstall).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", {
        name: "voiceTranscription.localWhisperInstall",
      }),
    ).toBeNull();
  });

  it("shows missing ffmpeg without offering to reinstall the plugin", () => {
    show({
      available: false,
      state: "missing_dependencies",
      ffmpeg_installed: false,
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "localWhisperState_missing_dependencies",
    );
    expect(
      screen.getByText("voiceTranscription.localWhisperPlugin_active"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "voiceTranscription.localWhisperFfmpegHelp",
      }),
    ).toHaveAttribute("href", "https://ffmpeg.org/download.html");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });

  it("offers dependency repair when Python dependencies are missing", () => {
    const { onInstall } = show({
      available: false,
      state: "missing_dependencies",
      whisper_installed: false,
    });
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(onInstall).toHaveBeenCalledOnce();
  });

  it("links to existing plugin management and labels lazy model loading", () => {
    show();
    expect(screen.getByRole("alert")).toHaveClass("ant-alert-success");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "localWhisperModelHint",
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "voiceTranscription.localWhisperManage",
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("/market?tab=plugins");
  });
});
