import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SnapTrend } from "./SnapTrend";

const chart = vi.hoisted(() => ({ emit: vi.fn(), on: vi.fn() }));
vi.mock("@ant-design/plots", () => ({
  Line: ({ onReady }: { onReady: (chart: unknown) => void }) => {
    onReady(chart);
    return <div data-testid="plot" />;
  },
}));
vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <b>{value}</b>,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: { language: "en" } }),
}));
const data = [
  { date: "2026-09-20", model: "Qwen", value: 120 },
  { date: "2026-09-22", model: "Qwen", value: 360 },
];

describe("SnapTrend", () => {
  it("links discrete keyboard-accessible selection to the chart and number", () => {
    render(<SnapTrend config={{ data, colorField: "model" }} label="Date" />);
    expect(screen.getByText("360")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByRole("slider")).toHaveAttribute(
      "aria-valuetext",
      "2026-09-20",
    );
    expect(chart.emit).toHaveBeenCalledWith("tooltip:show", {
      data: { data: { x: "2026-09-20" } },
    });
  });

  it("snaps mouse movement to the same point as the numeric readout", () => {
    render(
      <SnapTrend config={{ data, colorField: "model" }} label="Date" compact />,
    );
    const plot = screen.getByTestId("plot").parentElement!;
    const event = new Event("pointermove", { bubbles: true });
    Object.assign(event, { pointerType: "mouse", clientX: 44 });
    fireEvent(plot, event);
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByRole("slider")).toHaveAttribute(
      "aria-valuetext",
      "2026-09-20",
    );
  });

  it("returns to a scrubbed date after native chart hover changes selection", () => {
    render(<SnapTrend config={{ data, colorField: "model" }} label="Date" />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
    const listener = chart.on.mock.calls[chart.on.mock.calls.length - 1][1];
    act(() => listener({ data: { title: "2026-09-22" } }));
    expect(screen.getByText("360")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
    expect(screen.getByText("120")).toBeInTheDocument();
  });

  it("resolves selection against refreshed data without inventing a missing date", () => {
    const { rerender } = render(
      <SnapTrend config={{ data, colorField: "model" }} label="Date" />,
    );
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
    rerender(
      <SnapTrend
        config={{ data: [data[1]], colorField: "model" }}
        label="Date"
      />,
    );
    expect(screen.getByText("360")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-09-20")).not.toBeInTheDocument();
  });

  it("does not present missing values as zero", () => {
    render(
      <SnapTrend
        config={{ data: [{ ...data[0], value: null }], colorField: "model" }}
        label="Date"
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});
