// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

const shellState = vi.hoisted(() => ({
  renderBody: undefined as undefined | (() => React.ReactNode),
}));
const stringifyResult = vi.hoisted(() => vi.fn(() => "large output"));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({ renderBody }: { renderBody?: () => React.ReactNode }) => {
    shellState.renderBody = renderBody;
    return <div data-testid="shell" />;
  },
  DefaultBlock: () => <div data-testid="output" />,
}));

vi.mock("../shared/utils", () => ({ stringifyResult }));

import GenericToolCard from "./GenericToolCard";

describe("GenericToolCard", () => {
  it("defers result serialization until the body opens", () => {
    render(
      <GenericToolCard
        content={{
          type: "tool_call",
          id: "call-1",
          name: "large_tool",
          params: {},
          result: { output: "large" },
          status: "done",
        }}
      />,
    );

    expect(stringifyResult).not.toHaveBeenCalled();
    shellState.renderBody?.();
    expect(stringifyResult).toHaveBeenCalledTimes(1);
  });
});
