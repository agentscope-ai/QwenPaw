// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Form } from "antd";
import type { FormInstance } from "antd";
import { describe, expect, it, vi } from "vitest";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { RuleModal } from "./RuleModal";

describe("RuleModal Ant Select integration", () => {
  it("keeps selectors full-width and links mouse choices to the form", async () => {
    let form!: FormInstance;
    function Harness() {
      const [instance] = Form.useForm();
      form = instance;
      return (
        <RuleModal
          open
          editingRule={null}
          existingRuleIds={[]}
          onOk={vi.fn()}
          onCancel={vi.fn()}
          form={instance}
        />
      );
    }

    const { container } = render(<Harness />);
    const selectors = Array.from(
      container.ownerDocument.querySelectorAll<HTMLElement>(".ant-select"),
    );
    expect(selectors).toHaveLength(4);
    expect(selectors.every((selector) => selector.style.width === "100%")).toBe(
      true,
    );

    const comboboxes = screen.getAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    const toolOption = await waitFor(() => {
      const option = container.ownerDocument.querySelector<HTMLElement>(
        '.ant-select-item-option[title="execute_shell_command"]',
      );
      expect(option).toBeTruthy();
      return option!;
    });
    fireEvent.click(toolOption);
    expect(form.getFieldValue("tools")).toEqual(["execute_shell_command"]);

    fireEvent.keyDown(comboboxes[0], { key: "Escape" });
    fireEvent.mouseDown(comboboxes[2]);
    const severityOption = await waitFor(() => {
      const option = container.ownerDocument.querySelector<HTMLElement>(
        '.ant-select-item-option[title="MEDIUM"]',
      );
      expect(option).toBeTruthy();
      return option!;
    });
    fireEvent.click(severityOption);
    expect(form.getFieldValue("severity")).toBe("MEDIUM");
  });
});
