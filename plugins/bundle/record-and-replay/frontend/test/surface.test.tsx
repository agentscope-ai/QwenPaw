import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RecordingSurface } from "../src/surface";

const mocks = vi.hoisted(() => ({ get: vi.fn(), set: vi.fn() }));
vi.mock("../src/api", () => ({ recordingFeatureApi: mocks }));
vi.mock("../src/RecordingControl", () => ({
  DesktopRecordingControl: () => "record-controls",
}));
vi.mock("../src/locale", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../src/host", async () => ({
  host: { React: await import("react"), antd: await import("antd") },
}));

describe("optional Record surface", () => {
  afterEach(() => vi.restoreAllMocks());
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.set.mockReset();
    mocks.get.mockResolvedValue({
      enabled: true,
      supported_platform: true,
      capture_mode: "events-only",
    });
  });
  it("hides capture when disabled, without changing any feature", async () => {
    mocks.get.mockResolvedValue({ enabled: false, supported_platform: true });
    render(<RecordingSurface page />);
    expect(await screen.findByRole("switch")).not.toBeChecked();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(screen.queryByText("record-controls")).toBeNull();
    expect(mocks.set).not.toHaveBeenCalled();
  });
  it("turns off only through its feature endpoint", async () => {
    mocks.set.mockResolvedValue({ enabled: false, supported_platform: true });
    render(<RecordingSurface page />);
    await screen.findByText("record-controls");
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(screen.queryByText("record-controls")).toBeNull(),
    );
    expect(mocks.set).toHaveBeenCalledWith(false);
  });
  it("does not stop recording merely because its UI unmounts", async () => {
    const mounted = render(<RecordingSurface />);
    await screen.findByText("record-controls");
    mounted.unmount();
    expect(mocks.set).not.toHaveBeenCalled();
  });
  it("does not let an old poll undo a completed feature change", async () => {
    let poll = () => {};
    vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
      if (delay === 2000) poll = callback as () => void;
      return 1;
    });
    let resolvePoll!: (value: unknown) => void;
    mocks.get.mockResolvedValueOnce({
      enabled: true,
      supported_platform: true,
    });
    mocks.get.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePoll = resolve;
        }),
    );
    mocks.set.mockResolvedValue({ enabled: false, supported_platform: true });
    render(<RecordingSurface page />);
    await screen.findByText("record-controls");
    act(() => poll());
    expect(mocks.get).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(screen.queryByText("record-controls")).toBeNull(),
    );
    await act(async () =>
      resolvePoll({ enabled: true, supported_platform: true }),
    );
    expect(screen.getByRole("switch")).not.toBeChecked();
    expect(screen.queryByText("record-controls")).toBeNull();
  });
  it("offers no capture controls on an unsupported platform", async () => {
    mocks.get.mockResolvedValue({ enabled: true, supported_platform: false });
    render(<RecordingSurface page />);
    await screen.findByText("feature.platform");
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.queryByText("record-controls")).toBeNull();
  });
});
