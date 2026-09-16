import { useEffect } from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Form } from "@agentscope-ai/design";
import type { FormInstance } from "antd";
import type { CustomLoopModeConfig, LoopConfig } from "@/api/types";
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
  initialLoop,
  onForm,
}: {
  modes?: CustomLoopModeConfig[];
  initialLoop?: Partial<LoopConfig>;
  onForm?: (form: FormInstance) => void;
}) {
  const [form] = Form.useForm();
  useEffect(() => {
    onForm?.(form);
  }, [form, onForm]);

  return (
    <Form
      form={form}
      initialValues={{ loop: { ...initialLoop, custom_modes: modes } }}
    >
      <AgentLoopCard />
    </Form>
  );
}

describe("AgentLoopCard custom mode rendering", () => {
  it("preserves built-in and custom loop values across tab switches and collapse", async () => {
    let form: FormInstance | undefined;
    const mode = buildCustomLoopMode([], "Research", "research", "research", 1);
    const doomGateIndex = mode.gates.findIndex(
      (gate) => gate.type === "doom_loop",
    );
    const doomGate = mode.gates[doomGateIndex];
    if (!doomGate) throw new Error("Research mode must include doom-loop gate");
    doomGate.params.window_size = 7;
    doomGate.params.similarity_threshold = 0.75;

    renderWithProviders(
      <LoopForm
        modes={[mode]}
        initialLoop={{
          iteration: { enabled: true, max_iterations: 77 },
          goal: { max_iterations: 12, max_tokens: 34567 },
          mission: {
            max_iterations: 8,
            max_retries_per_story: 2,
            default_verification_instructions: "Check the rendered result",
            default_verify_command: "pytest -q",
          },
        }}
        onForm={(next) => (form = next)}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Goal" }));
    fireEvent.click(screen.getByRole("button", { name: /Goal turn limit/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Mission" }));
    fireEvent.click(
      screen.getByRole("button", { name: /Mission verification policy/ }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Research" }));
    fireEvent.click(
      within(screen.getByRole("tabpanel")).getByText("Repetition protection"),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Default" }));

    expect(form?.getFieldsValue(true).loop).toEqual({
      iteration: { enabled: true, max_iterations: 77 },
      goal: { max_iterations: 12, max_tokens: 34567 },
      mission: {
        max_iterations: 8,
        max_retries_per_story: 2,
        default_verification_instructions: "Check the rendered result",
        default_verify_command: "pytest -q",
      },
      custom_modes: [mode],
    });
  }, 15_000);

  it("keeps gate identity, parameters and order after deleting another gate", async () => {
    let form: FormInstance | undefined;
    const mode = buildCustomLoopMode([], "Research", "research", "research", 1);
    renderWithProviders(
      <LoopForm modes={[mode]} onForm={(next) => (form = next)} />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Research" }));
    const editor = within(screen.getByRole("tabpanel"));
    fireEvent.click(editor.getByText("Repetition protection"));
    const removeButtons = editor.getAllByLabelText("Remove gate");
    fireEvent.click(removeButtons[0]);

    const savedGates = form?.getFieldValue([
      "loop",
      "custom_modes",
      0,
      "gates",
    ]);
    expect(savedGates).toEqual(mode.gates.slice(1));
    expect(savedGates[2]).toMatchObject({
      id: mode.gates[3].id,
      type: "doom_loop",
      enabled: true,
      params: mode.gates[3].params,
    });
  }, 15_000);

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

  it("updates a per-tool call limit name", async () => {
    let form: FormInstance | undefined;
    const mode = buildCustomLoopMode([], "Research", "research", "research", 1);
    const budget = mode.gates.find((gate) => gate.type === "tool_call_budget");
    if (!budget) throw new Error("Research mode must include a tool budget");
    budget.params.per_tool = { "tool-name": 3 };

    renderWithProviders(
      <LoopForm modes={[mode]} onForm={(next) => (form = next)} />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Research" }));
    fireEvent.click(await screen.findByText("Tool-call budget"));
    const toolName = screen.getByLabelText("Tool name");
    fireEvent.change(toolName, { target: { value: "search" } });

    expect(toolName).toHaveValue("search");

    fireEvent.blur(toolName);

    expect(
      form?.getFieldValue([
        "loop",
        "custom_modes",
        0,
        "gates",
        2,
        "params",
        "per_tool",
      ]),
    ).toEqual({ search: 3 });
  }, 15_000);
});
