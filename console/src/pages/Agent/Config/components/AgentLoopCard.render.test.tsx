import { ConfigAutoSaveContext } from "../configAutoSaveContext";
import { useEffect } from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Form } from "@agentscope-ai/design";
import type { FormInstance } from "antd";
import type { AgentsRunningConfig, CustomLoopModeConfig } from "@/api/types";
import { renderWithProviders } from "@/test/common_setup";
import { AgentLoopCard } from "./AgentLoopCard";
import { buildCustomLoopMode } from "./agentLoopHelpers";

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
  doomLoop,
  onForm,
  onEdit = () => {},
}: {
  onEdit?: () => void;
  modes?: CustomLoopModeConfig[];
  doomLoop?: AgentsRunningConfig["loop"]["doom_loop"];
  onForm?: (form: FormInstance) => void;
}) {
  const [form] = Form.useForm();
  useEffect(() => {
    onForm?.(form);
  }, [form, onForm]);

  return (
    <Form
      form={form}
      initialValues={{ loop: { custom_modes: modes, doom_loop: doomLoop } }}
      onValuesChange={onEdit}
    >
      <ConfigAutoSaveContext.Provider value={onEdit}>
        <AgentLoopCard />
      </ConfigAutoSaveContext.Provider>
    </Form>
  );
}

describe("AgentLoopCard custom mode rendering", () => {
  it.each(["built-in", "custom"])(
    "updates %s repetition thresholds and notifies autosave",
    async (kind) => {
      let form: FormInstance | undefined;
      const onEdit = vi.fn();
      const mode = buildCustomLoopMode([], "Safe", "safe", "safe", 1);
      const gateIndex = mode.gates.findIndex(
        (gate) => gate.type === "doom_loop",
      );
      const base =
        kind === "built-in"
          ? ["loop", "doom_loop"]
          : ["loop", "custom_modes", 0, "gates", gateIndex, "params"];
      renderWithProviders(
        <LoopForm
          modes={[mode]}
          doomLoop={{
            enabled: true,
            window_size: 3,
            similarity_threshold: 1,
            stages: [
              { after: 3, action: "modify_prompt", prompt: "Change strategy" },
              { after: 6, action: "stop", prompt: "Ask for help" },
            ],
          }}
          onEdit={onEdit}
          onForm={(next) => (form = next)}
        />,
      );
      if (kind === "custom") {
        fireEvent.click(screen.getByRole("tab", { name: "Safe" }));
      }
      const editor = within(screen.getByRole("tabpanel"));
      fireEvent.click(editor.getByText("Repetition protection"));
      const input = await editor.findByLabelText("After");
      const stepper = within(
        input.closest("[class*='stepper']")! as HTMLElement,
      );
      expect(input).toHaveValue("3");
      fireEvent.click(stepper.getByRole("button", { name: "common.increase" }));
      fireEvent.click(stepper.getByRole("button", { name: "common.increase" }));
      expect(input).toHaveValue("5");
      expect(form?.getFieldValue([...base, "stages", 0, "after"])).toBe(5);
      fireEvent.click(stepper.getByRole("button", { name: "common.decrease" }));
      expect(input).toHaveValue("4");
      fireEvent.change(input, { target: { value: "12" } });
      fireEvent.blur(input);
      expect(form?.getFieldValue([...base, "stages", 0, "after"])).toBe(12);
      expect(onEdit).toHaveBeenCalled();
    },
  );

  it("shows a newly created template and its preset gates immediately", async () => {
    let form: FormInstance | undefined;
    const onEdit = vi.fn();
    renderWithProviders(
      <LoopForm onEdit={onEdit} onForm={(next) => (form = next)} />,
    );

    fireEvent.click(screen.getByLabelText("Create custom loop mode"));
    fireEvent.click(screen.getByRole("button", { name: "OK" }));

    expect(
      await screen.findByRole("tab", { name: "New Loop Mode" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(onEdit).toHaveBeenCalled();
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
    onEdit.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
    expect(onEdit).toHaveBeenCalledOnce();
    onEdit.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onEdit).toHaveBeenCalledOnce();
  }, 15_000);

  it("opens Gate choices from the plus button and enables a blank mode", async () => {
    let form: FormInstance | undefined;
    const onEdit = vi.fn();
    renderWithProviders(
      <LoopForm onEdit={onEdit} onForm={(next) => (form = next)} />,
    );

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
    onEdit.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
    expect(onEdit).toHaveBeenCalledOnce();
    onEdit.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onEdit).toHaveBeenCalledOnce();
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
