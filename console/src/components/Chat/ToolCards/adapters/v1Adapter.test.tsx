import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToolResponseStatusContext } from "../shared/ToolResponseContext";
import { adaptCardForV1 } from "./v1Adapter";

vi.mock("../cards/GenericToolCard", () => ({ default: () => null }));

const Card = adaptCardForV1(({ content, isStreaming }) => (
  <span data-testid="status">
    {content.status}:{String(isStreaming)}
  </span>
));
const call = {
  data: {
    name: "read_file",
    call_id: "profile-call",
    arguments: '{"file_path":"PROFILE.md"}',
  },
};

describe("tool response lifecycle", () => {
  it("stops missing-result history without reporting success and keeps live calls running", () => {
    const view = (status: string) => (
      <ToolResponseStatusContext.Provider value={status}>
        <Card data={{ status: "completed", content: [call] }} />
      </ToolResponseStatusContext.Provider>
    );
    const { rerender } = render(view("in_progress"));
    expect(screen.getByTestId("status")).toHaveTextContent("calling:true");
    for (const status of ["completed", "canceled", "cancelled", "failed"]) {
      rerender(view(status));
      expect(screen.getByTestId("status")).toHaveTextContent(
        "incomplete:false",
      );
    }
  });

  it.each(["rejected", "failed", "canceled", "cancelled"])(
    "honors explicit %s even without a result",
    (status) => {
      render(<Card data={{ status, content: [call] }} />);
      expect(screen.getByTestId("status")).toHaveTextContent("error:false");
    },
  );

  it.each(["denied", "interrupted", "error"])(
    "preserves an explicit %s result after the response completes",
    (state) => {
      render(
        <ToolResponseStatusContext.Provider value="completed">
          <Card
            data={{
              status: "completed",
              content: [
                call,
                { data: { state, output: "Tool did not execute" } },
              ],
            }}
          />
        </ToolResponseStatusContext.Provider>,
      );
      expect(screen.getByTestId("status")).toHaveTextContent("error:false");
    },
  );

  it("keeps successful results complete while another tool runs", () => {
    render(
      <ToolResponseStatusContext.Provider value="in_progress">
        <Card
          data={{
            status: "completed",
            content: [call, { data: { state: "success", output: "" } }],
          }}
        />
      </ToolResponseStatusContext.Provider>,
    );
    expect(screen.getByTestId("status")).toHaveTextContent("done:false");
  });
});
