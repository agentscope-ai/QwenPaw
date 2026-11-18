// @vitest-environment jsdom
/**
 * Contract tests for SetTimezoneCard.
 *
 * This is the only card in the ToolCards set that uses the shell inlineResult
 * slot instead of an expandable body, so the contract worth pinning is which
 * statuses are allowed to surface a result inline. The card only inlines a
 * finished call that actually produced something; a still-running call, a
 * failed call, or a call whose result stringifies to nothing must pass null so
 * the shell does not render an empty inline strip.
 *
 * There was no test file for this card before this one.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ToolCallContent } from "../shared/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options ? `${key}[${JSON.stringify(options)}]` : key,
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    title,
    inlineResult,
  }: {
    title?: string;
    inlineResult?: string | null;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      <span data-testid="inline-result">{String(inlineResult)}</span>
    </div>
  ),
}));

vi.mock("../shared/utils", () => ({
  stringifyResult: (result: unknown) =>
    typeof result === "string" ? result : "",
}));

import SetTimezoneCard from "./SetTimezoneCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "tz-1",
  name: "set_user_timezone",
  status: "done",
  params: { timezone_name: "Asia/Shanghai" },
  result: "timezone updated",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;
const inlineText = () => screen.getByTestId("inline-result").textContent;

describe("SetTimezoneCard", () => {
  it("names the timezone in the title", () => {
    render(<SetTimezoneCard content={createContent()} />);

    expect(titleText()).toBe('tool.setTimezone[{"timezone":"Asia/Shanghai"}]');
  });

  it("passes an empty timezone through instead of dropping the title", () => {
    render(<SetTimezoneCard content={createContent({ params: {} })} />);

    expect(titleText()).toBe('tool.setTimezone[{"timezone":""}]');
  });

  it("passes an empty timezone through when the call carries no params", () => {
    render(<SetTimezoneCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe('tool.setTimezone[{"timezone":""}]');
  });

  it("shows the finished result inline", () => {
    render(<SetTimezoneCard content={createContent()} />);

    expect(inlineText()).toBe("timezone updated");
  });

  it("shows nothing inline while the call is still running", () => {
    render(<SetTimezoneCard content={createContent({ status: "calling" })} />);

    expect(inlineText()).toBe("null");
  });

  it("shows nothing inline when the call failed", () => {
    render(<SetTimezoneCard content={createContent({ status: "error" })} />);

    expect(inlineText()).toBe("null");
  });

  it("shows nothing inline when the finished call produced no text", () => {
    render(<SetTimezoneCard content={createContent({ result: "" })} />);

    expect(inlineText()).toBe("null");
  });

  it("shows nothing inline when the result is not text", () => {
    render(
      <SetTimezoneCard content={createContent({ result: { ok: true } })} />,
    );

    expect(inlineText()).toBe("null");
  });
});
