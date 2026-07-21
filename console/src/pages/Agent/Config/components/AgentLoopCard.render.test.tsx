import { useEffect } from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Form } from "@agentscope-ai/design";
import type { FormInstance } from "antd";
import type { CustomLoopModeConfig } from "@/api/types";
import { renderWithProviders } from "@/test/common_setup";
import { AgentLoopCard } from "./AgentLoopCard";

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
  it("shows a newly created template and its preset gates immediately", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(<LoopForm onForm={(next) => (form = next)} />);

    fireEvent.click(screen.getByLabelText("Create custom loop mode"));
    fireEvent.click(screen.getByRole("button", { name: "OK" }));

    expect(
      await screen.findByRole("tab", { name: "New Loop Mode" }),
    ).toHaveAttribute("aria-selected", "true");
    const editor = within(screen.getByRole("tabpanel"));
    expect(editor.getByText("Iteration limit")).toBeInTheDocument();
    expect(editor.getByText("Token budget")).toBeInTheDocument();
    expect(editor.getByText("Repetition protection")).toBeInTheDocument();
    expect(
      editor.getByText("Qualitative completion check"),
    ).toBeInTheDocument();
    expect(
      editor.queryByText("Available to this agent"),
    ).not.toBeInTheDocument();
    expect(form?.getFieldValue(["loop", "custom_modes", 0, "enabled"])).toBe(
      true,
    );
  }, 15_000);

  it("opens Gate choices from the plus button and enables a blank mode", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(<LoopForm onForm={(next) => (form = next)} />);

    fireEvent.click(screen.getByLabelText("Create custom loop mode"));
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(await screen.findByText("Blank pipeline"));
    fireEvent.click(screen.getByRole("button", { name: "OK" }));

    const editor = within(await screen.findByRole("tabpanel"));
    expect(form?.getFieldValue(["loop", "custom_modes", 0, "enabled"])).toBe(
      false,
    );

    fireEvent.click(editor.getByRole("button", { name: "Add gate" }));
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Iteration limit" }),
    );

    expect(editor.getByText("Iteration limit")).toBeInTheDocument();
    expect(form?.getFieldValue(["loop", "custom_modes", 0, "enabled"])).toBe(
      true,
    );
  }, 15_000);

  it("renders Mission defaults as three separate gates", async () => {
    renderWithProviders(<LoopForm />);

    fireEvent.click(screen.getByRole("tab", { name: "Mission" }));

    const mission = within(screen.getByRole("tabpanel"));
    expect(
      mission.getByRole("button", { name: /Mission iteration limit/ }),
    ).toBeInTheDocument();
    expect(
      mission.getByRole("button", { name: /Worker attempts/ }),
    ).toBeInTheDocument();
    const verificationGate = mission.getByRole("button", {
      name: /Mission verification policy/,
    });
    expect(verificationGate).toBeInTheDocument();
    expect(
      mission.queryByText("Verification guidance (optional)"),
    ).not.toBeInTheDocument();

    fireEvent.click(verificationGate);

    expect(
      mission.getByText("Verification guidance (optional)"),
    ).toBeInTheDocument();
    expect(
      mission.getByText("Default test command (optional)"),
    ).toBeInTheDocument();
  }, 15_000);
});
