import { useEffect } from "react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Form } from "@agentscope-ai/design";
import type { FormInstance } from "antd";
import type { CustomLoopModeConfig } from "@/api/types";
import { renderWithProviders } from "@/test/common_setup";
import { AgentLoopCard, buildCustomLoopMode } from "./AgentLoopCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

function LoopForm({
  modes = [],
  onForm,
}: {
  modes?: CustomLoopModeConfig[];
  onForm?: (form: FormInstance) => void;
}) {
  const [form] = Form.useForm();
  useEffect(() => {
    onForm?.(form);
  }, [form, onForm]);

  return (
    <Form form={form} initialValues={{ loop: { custom_modes: modes } }}>
      <AgentLoopCard />
    </Form>
  );
}

describe("AgentLoopCard custom mode rendering", () => {
  it("renders custom modes stored in unregistered form values", () => {
    const mode = buildCustomLoopMode([], "Research", "research", "research", 1);

    renderWithProviders(<LoopForm modes={[mode]} />);

    expect(screen.getByRole("tab", { name: "Research" })).toBeInTheDocument();
  });

  it("shows a newly created template and its preset gates immediately", async () => {
    const user = userEvent.setup();
    let form: FormInstance | undefined;
    renderWithProviders(<LoopForm onForm={(next) => (form = next)} />);

    await user.click(screen.getByLabelText("Create custom loop mode"));
    await user.click(screen.getByRole("button", { name: "OK" }));

    expect(screen.getByRole("tab", { name: "New Loop Mode" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const editor = within(screen.getByRole("tabpanel"));
    expect(editor.getByText("Iteration limit")).toBeInTheDocument();
    expect(editor.getByText("Token budget")).toBeInTheDocument();
    expect(editor.getByText("Repetition protection")).toBeInTheDocument();
    expect(editor.getByText("Qualitative rubric")).toBeInTheDocument();
    expect(
      editor.queryByText("Available to this agent"),
    ).not.toBeInTheDocument();
    expect(form?.getFieldValue(["loop", "custom_modes", 0, "enabled"])).toBe(
      true,
    );
  });

  it("opens Gate choices from the plus button and enables a blank mode", async () => {
    const user = userEvent.setup();
    let form: FormInstance | undefined;
    renderWithProviders(<LoopForm onForm={(next) => (form = next)} />);

    await user.click(screen.getByLabelText("Create custom loop mode"));
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByText("Blank pipeline"));
    await user.click(screen.getByRole("button", { name: "OK" }));

    const editor = within(screen.getByRole("tabpanel"));
    expect(form?.getFieldValue(["loop", "custom_modes", 0, "enabled"])).toBe(
      false,
    );

    await user.click(editor.getByRole("button", { name: "Add gate" }));
    await user.click(screen.getByRole("menuitem", { name: "Iteration limit" }));

    expect(editor.getByText("Iteration limit")).toBeInTheDocument();
    expect(form?.getFieldValue(["loop", "custom_modes", 0, "enabled"])).toBe(
      true,
    );
  });

  it("separates Mission verification guidance from its test command", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoopForm />);

    await user.click(screen.getByRole("tab", { name: "Mission" }));

    const mission = within(screen.getByRole("tabpanel"));
    expect(
      mission.getByText("Verification guidance (optional)"),
    ).toBeInTheDocument();
    expect(
      mission.getByText("Default test command (optional)"),
    ).toBeInTheDocument();
  });
});
