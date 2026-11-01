import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Form } from "antd";

vi.mock("@agentscope-ai/design", async () => {
  const antd = await import("antd");
  return { Form: antd.Form, Switch: antd.Switch, Collapse: antd.Collapse };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { DecisionCompactSettings } from "./DecisionCompactSettings";

describe("DecisionCompactSettings", () => {
  it("defaults off and saves enabled parameters under the context configuration", async () => {
    const saved = vi.fn();
    render(
      <Form onFinish={saved}>
        <DecisionCompactSettings />
        <button type="submit">Save</button>
      </Form>,
    );
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(screen.getAllByRole("spinbutton")[0]).toBeDisabled();
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(screen.getAllByRole("spinbutton")[0]).toBeEnabled(),
    );
    fireEvent.change(screen.getAllByRole("spinbutton")[0], {
      target: { value: "0.05" },
    });
    fireEvent.click(screen.getByText("agentConfig.decisionCompactAdvanced"));
    await waitFor(() =>
      expect(screen.getAllByRole("spinbutton")).toHaveLength(8),
    );
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    expect(
      saved.mock.calls[0][0].light_context_config.decision_compact_config,
    ).toEqual({
      enabled: true,
      drop_threshold: 0.05,
      preserve_recent_messages: 6,
      preview_chars: 300,
      total_timeout_seconds: 30,
      max_state_tokens: 25000,
      max_request_tokens: 30000,
      evidence_chars: 2000,
      max_concurrency: 4,
    });
  });
});
