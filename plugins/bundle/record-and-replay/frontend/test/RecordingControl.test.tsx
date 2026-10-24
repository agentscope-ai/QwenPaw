import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { render as renderWithProviders } from "@testing-library/react";
import { DesktopRecordingControl } from "../src/RecordingControl";

vi.mock("../src/recording.module.less?inline", () => ({ default: "" }));

const recordingMocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  start: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  stop: vi.fn(),
  requestPermission: vi.fn(),
  reviewRecording: vi.fn(),
  prepareLearn: vi.fn(),
  generateDraft: vi.fn(),
  recoverDraft: vi.fn(),
  materializeSkill: vi.fn(),
}));

vi.mock("../src/api", () => ({
  createRecordingApi: () => recordingMocks,
}));

vi.mock("../src/locale", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../src/host", async () => ({
  host: {
    React: await import("react"),
    antd: await import("antd"),
    antdIcons: await import("@ant-design/icons"),
    useSelectedAgent: () => ({ id: "default" }),
  },
}));

const status = (state: "idle" | "recording" | "paused") => ({
  api_schema_version: 1 as const,
  available: true,
  input_monitoring: "granted" as const,
  accessibility: "granted" as const,
  state,
  recording:
    state === "idle"
      ? null
      : {
          recording_id: "recording-1",
          agent_id: "default",
          state,
          created_at: "2026-09-02T00:00:00Z",
          updated_at: "2026-09-02T00:00:00Z",
          completed_at: null,
          event_count: 0,
          dropped_event_count: 0,
          failure_code: null,
        },
  last_recording: null,
});

describe("DesktopRecordingControl", () => {
  afterEach(() => vi.restoreAllMocks());
  beforeEach(() => {
    for (const mock of Object.values(recordingMocks)) mock.mockReset();
    recordingMocks.getStatus.mockResolvedValue(status("idle"));
    recordingMocks.recoverDraft.mockResolvedValue(null);
  });

  it("starts through the product API and renders the active controls", async () => {
    recordingMocks.start.mockResolvedValue(status("recording"));
    renderWithProviders(<DesktopRecordingControl />);

    const start = await screen.findByRole("button", {
      name: "desktop.recording.start",
    });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);

    await screen.findByRole("status");
    expect(recordingMocks.start).toHaveBeenCalledOnce();
    expect(
      screen.getByRole("button", { name: "desktop.recording.pause" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "desktop.recording.stop" }),
    ).toBeEnabled();
  });

  it("ignores a pre-start status response arriving after start", async () => {
    let poll = () => {};
    vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
      if (delay === 2000) poll = callback as () => void;
      return 1;
    });
    let resolvePoll!: (value: unknown) => void;
    recordingMocks.getStatus.mockResolvedValueOnce(status("idle"));
    recordingMocks.getStatus.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePoll = resolve;
        }),
    );
    recordingMocks.start.mockResolvedValue(status("recording"));
    renderWithProviders(<DesktopRecordingControl />);
    const start = await screen.findByRole("button", {
      name: "desktop.recording.start",
    });
    await waitFor(() => expect(start).toBeEnabled());
    act(() => poll());
    expect(recordingMocks.getStatus).toHaveBeenCalledTimes(2);
    fireEvent.click(start);
    await screen.findByRole("status");
    await act(async () => resolvePoll(status("idle")));
    expect(
      screen.getByRole("button", { name: "desktop.recording.stop" }),
    ).toBeEnabled();
  });

  it("does not start after its Agent surface is unmounted during permission request", async () => {
    let grant!: (value: unknown) => void;
    recordingMocks.getStatus.mockResolvedValue({
      ...status("idle"),
      input_monitoring: "required",
    });
    recordingMocks.requestPermission.mockImplementation(
      () =>
        new Promise((resolve) => {
          grant = resolve;
        }),
    );
    const mounted = renderWithProviders(<DesktopRecordingControl />);
    const authorize = await screen.findByRole("button", {
      name: "desktop.recording.authorize",
    });
    fireEvent.click(authorize);
    await waitFor(() =>
      expect(recordingMocks.requestPermission).toHaveBeenCalledOnce(),
    );
    mounted.unmount();
    await act(async () => grant(status("idle")));
    expect(recordingMocks.start).not.toHaveBeenCalled();
  });

  it("never recovers another Agent's completed draft", async () => {
    recordingMocks.getStatus.mockResolvedValue({
      ...status("idle"),
      last_recording: {
        ...status("recording").recording,
        state: "completed",
        agent_id: "another-agent",
        event_count: 10,
      },
    });
    renderWithProviders(<DesktopRecordingControl />);
    const start = await screen.findByRole("button", {
      name: "desktop.recording.start",
    });
    await waitFor(() => expect(start).toBeEnabled());
    expect(recordingMocks.recoverDraft).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("resumes a paused recording without creating a second session", async () => {
    recordingMocks.getStatus.mockResolvedValue(status("paused"));
    recordingMocks.resume.mockResolvedValue(status("recording"));
    renderWithProviders(<DesktopRecordingControl />);

    const resume = await screen.findByRole("button", {
      name: "desktop.recording.resume",
    });
    fireEvent.click(resume);

    await waitFor(() => expect(recordingMocks.resume).toHaveBeenCalledOnce());
    expect(recordingMocks.start).not.toHaveBeenCalled();
  });

  it("shows a failed recording without active controls and permits a fresh start", async () => {
    recordingMocks.getStatus.mockResolvedValue({
      ...status("idle"),
      state: "failed",
      last_recording: {
        ...status("recording").recording,
        state: "failed",
        failure_code: "event_stream_capture_failed",
      },
    });
    recordingMocks.start.mockResolvedValue(status("recording"));
    renderWithProviders(<DesktopRecordingControl />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "desktop.recording.errors.generic",
    );
    expect(
      screen.queryByRole("button", { name: "desktop.recording.stop" }),
    ).toBeNull();
    expect(recordingMocks.recoverDraft).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "desktop.recording.start" }),
    );
    await screen.findByRole("button", { name: "desktop.recording.stop" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("requests host permission before the first recording", async () => {
    const required = {
      ...status("idle"),
      input_monitoring: "required" as const,
    };
    recordingMocks.getStatus.mockResolvedValue(required);
    recordingMocks.requestPermission.mockResolvedValue(status("idle"));
    recordingMocks.start.mockResolvedValue(status("recording"));
    renderWithProviders(<DesktopRecordingControl />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "desktop.recording.authorize",
      }),
    );

    await waitFor(() =>
      expect(recordingMocks.requestPermission).toHaveBeenCalledOnce(),
    );
    expect(recordingMocks.start).toHaveBeenCalledOnce();
  });

  it("degrades explicitly when accessibility remains unavailable", async () => {
    const required = {
      ...status("idle"),
      accessibility: "required" as const,
    };
    recordingMocks.getStatus.mockResolvedValue(required);
    recordingMocks.requestPermission.mockResolvedValue(required);
    recordingMocks.start.mockResolvedValue(status("recording"));
    renderWithProviders(<DesktopRecordingControl />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "desktop.recording.authorize",
      }),
    );

    await waitFor(() =>
      expect(recordingMocks.requestPermission).toHaveBeenCalledOnce(),
    );
    expect(recordingMocks.start).toHaveBeenCalledOnce();
  });

  it.each(["learn_model_unavailable", "learn_provider_unavailable"])(
    "explains how to recover from %s without sending evidence",
    async (code) => {
      recordingMocks.getStatus.mockResolvedValue(status("recording"));
      recordingMocks.stop.mockResolvedValue({
        ...status("idle"),
        last_recording: {
          ...status("recording").recording,
          state: "completed",
          event_count: 1,
        },
      });
      recordingMocks.reviewRecording.mockResolvedValue({
        recording_id: "recording-1",
        persisted_event_count: 1,
        dropped_event_count: 0,
        events: [
          {
            evidence_id: "event-1",
            source_sequences: [1],
            type: "activate",
            locator: { app_name: "Calculator", role: "AXButton", name: "7" },
            action: { button: "left" },
            redacted: false,
          },
        ],
      });
      recordingMocks.prepareLearn.mockRejectedValue(new Error(code));
      renderWithProviders(<DesktopRecordingControl />);
      fireEvent.click(
        await screen.findByRole("button", { name: "desktop.recording.stop" }),
      );
      const goal = await screen.findByRole("textbox", {
        name: "desktop.recording.learn.goal",
      });
      fireEvent.change(goal, { target: { value: "A simple calculation" } });
      const prepare = screen.getByRole("button", {
        name: "desktop.recording.learn.intentAction",
      });
      await waitFor(() => expect(prepare).toBeEnabled());
      fireEvent.click(prepare);
      await screen.findByText("desktop.recording.learn.modelUnavailable");
      expect(recordingMocks.generateDraft).not.toHaveBeenCalled();
      expect(recordingMocks.materializeSkill).not.toHaveBeenCalled();
      expect(
        screen.getByRole("textbox", { name: "desktop.recording.learn.goal" }),
      ).toHaveValue("A simple calculation");
    },
  );

  it("reviews consent and materializes a Skill after stopping", async () => {
    const stopped = {
      ...status("idle"),
      last_recording: {
        recording_id: "recording-1",
        agent_id: "default",
        state: "completed" as const,
        created_at: "2026-09-02T00:00:00Z",
        updated_at: "2026-09-02T00:01:00Z",
        completed_at: "2026-09-02T00:01:00Z",
        event_count: 12,
        dropped_event_count: 0,
        failure_code: null,
      },
    };
    const preview = {
      api_schema_version: 1 as const,
      recording_id: "recording-1",
      consent_token: "consent-1",
      expires_at: "2026-09-02T00:11:00Z",
      model_target: {
        provider_id: "provider-a",
        model: "model-a",
        is_local: false,
      },
      external_transfer: true,
      persisted_event_count: 12,
      selected_event_count: 12,
      evidence_event_count: 3,
      dropped_event_count: 0,
      redacted_event_count: 2,
      field_scope: ["event.type", "target.identifier"],
    };
    const review = {
      api_schema_version: 1 as const,
      recording_id: "recording-1",
      persisted_event_count: 12,
      dropped_event_count: 0,
      events: [
        {
          evidence_id: "event-0001",
          source_sequences: [1, 2],
          type: "activate" as const,
          locator: {
            bundle_id: "com.apple.calculator",
            app_name: "Calculator",
            window_role: "AXWindow",
            role: "AXButton",
            subrole: null,
            identifier: "Nine",
            name: "9",
          },
          action: { button: "left" },
          redacted: false,
        },
      ],
    };
    const draft = {
      api_schema_version: 1 as const,
      draft_id: "draft-1",
      recording_id: "recording-1",
      name: "calculator-workflow",
      description: "Use Calculator for a reusable workflow.",
      content:
        "---\nname: calculator-workflow\ndescription: Use Calculator\n---\n\n# Workflow",
      inputs: [],
      steps: [],
      source_sequences: [1, 2],
      ignored_source_sequences: [3],
      ambiguities: [],
      assumptions: [],
      needs_confirmation: false,
    };
    recordingMocks.getStatus.mockResolvedValue(status("recording"));
    recordingMocks.stop.mockResolvedValue(stopped);
    recordingMocks.reviewRecording.mockResolvedValue(review);
    recordingMocks.prepareLearn.mockResolvedValue(preview);
    recordingMocks.generateDraft.mockResolvedValue(draft);
    recordingMocks.materializeSkill.mockResolvedValue({
      api_schema_version: 1,
      created: true,
      name: draft.name,
      enabled: true,
      reload_scheduled: true,
    });
    renderWithProviders(<DesktopRecordingControl />);

    fireEvent.click(
      await screen.findByRole("button", { name: "desktop.recording.stop" }),
    );
    await screen.findByText("desktop.recording.learn.intentTitle");
    await waitFor(() =>
      expect(recordingMocks.reviewRecording).toHaveBeenCalledWith(
        "recording-1",
      ),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "desktop.recording.learn.goal" }),
      { target: { value: "Calculate a reusable value" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "desktop.recording.learn.intentAction",
      }),
    );
    await waitFor(() =>
      expect(recordingMocks.prepareLearn).toHaveBeenCalledWith({
        recording_id: "recording-1",
        goal: "Calculate a reusable value",
        confirmed_context: "",
        selected_sequences: [1, 2],
      }),
    );

    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "desktop.recording.learn.consent",
      }),
    );
    const generateButton = screen.getByRole("button", {
      name: /desktop\.recording\.learn\.consentAction/,
    });
    await waitFor(() => expect(generateButton).toBeEnabled());
    fireEvent.click(generateButton);
    await waitFor(() =>
      expect(recordingMocks.generateDraft).toHaveBeenCalledWith("consent-1"),
    );

    const createButton = await screen.findByRole("button", {
      name: /desktop\.recording\.learn\.draftAction/,
    });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);
    await waitFor(() =>
      expect(recordingMocks.materializeSkill).toHaveBeenCalledWith({
        draft_id: "draft-1",
        name: "calculator-workflow",
        content: draft.content,
      }),
    );
  });

  it("recovers an unexpired generated draft after a UI remount", async () => {
    const completed = {
      ...status("idle"),
      last_recording: {
        recording_id: "recording-1",
        agent_id: "default",
        state: "completed" as const,
        created_at: "2026-09-02T00:00:00Z",
        updated_at: "2026-09-02T00:01:00Z",
        completed_at: "2026-09-02T00:01:00Z",
        event_count: 1,
        dropped_event_count: 0,
        failure_code: null,
      },
    };
    const draft = {
      api_schema_version: 1 as const,
      draft_id: "draft-1",
      recording_id: "recording-1",
      name: "click-nine",
      description: "Click nine in Calculator.",
      content:
        "---\nname: click-nine\ndescription: Click nine\n---\n\n# Workflow",
      inputs: [],
      steps: [],
      source_sequences: [3],
      ignored_source_sequences: [],
      ambiguities: [],
      assumptions: [],
      needs_confirmation: false,
    };
    recordingMocks.getStatus.mockResolvedValue(completed);
    recordingMocks.recoverDraft.mockResolvedValue(draft);

    renderWithProviders(<DesktopRecordingControl />);

    await screen.findByText("desktop.recording.learn.draftTitle");
    expect(recordingMocks.recoverDraft).toHaveBeenCalledWith("recording-1");
    expect(
      screen.getByRole("textbox", {
        name: "desktop.recording.learn.skillName",
      }),
    ).toHaveValue("click-nine");
  });
});
