import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import api from "../../../../../api";
import type { ModelInfo, ProviderInfo } from "../../../../../api/types";
import { renderWithProviders } from "@/test/common_setup";

import { ModelConfigEditor } from "./ModelConfigEditor";

vi.mock("../../../../../api", () => ({
  default: {
    configureModel: vi.fn(),
  },
}));

vi.mock("./JsonConfigEditor", () => ({
  JsonConfigEditor: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (value: string) => void;
  }) => (
    <textarea
      aria-label="Generation config"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

const provider = { id: "openai" } as ProviderInfo;

function createModel(overrides: Partial<ModelInfo> = {}): ModelInfo {
  return {
    id: "test-model",
    name: "Test Model",
    supports_multimodal: null,
    supports_image: null,
    supports_video: null,
    max_input_length: 131072,
    generate_kwargs: {},
    relay_reasoning: true,
    thinking_enabled: null,
    thinking_budget: null,
    reasoning_effort: null,
    ...overrides,
  };
}

function renderEditor(model: ModelInfo, thinkingParamStyle?: "budget") {
  return renderWithProviders(
    <ModelConfigEditor
      providerId="openai"
      model={model}
      onSaved={vi.fn()}
      onProviderUpdated={vi.fn()}
      onClose={vi.fn()}
      thinkingParamStyle={thinkingParamStyle}
    />,
  );
}

describe("ModelConfigEditor output limits", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not turn an unknown capability into a request limit", async () => {
    vi.mocked(api.configureModel).mockResolvedValue(provider);
    const user = userEvent.setup();
    renderEditor(
      createModel({
        max_output_length: 8192,
        max_output_length_source: "api",
      }),
      "budget",
    );

    await user.click(screen.getAllByRole("switch")[0]);
    await user.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => expect(api.configureModel).toHaveBeenCalledOnce());
    const payload = vi.mocked(api.configureModel).mock.calls[0][2];
    expect(payload.generate_kwargs).not.toHaveProperty("max_tokens");
  });

  it("keeps a configured request limit when editing another setting", async () => {
    vi.mocked(api.configureModel).mockResolvedValue(provider);
    const user = userEvent.setup();
    renderEditor(
      createModel({
        generate_kwargs: { max_tokens: 4096, temperature: 0.2 },
      }),
      "budget",
    );

    await user.click(screen.getAllByRole("switch")[0]);
    await user.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => expect(api.configureModel).toHaveBeenCalledOnce());
    const payload = vi.mocked(api.configureModel).mock.calls[0][2];
    expect(payload.generate_kwargs).toEqual({
      max_tokens: 4096,
      temperature: 0.2,
    });
  });

  it("can clear a configured request limit back to auto", async () => {
    vi.mocked(api.configureModel).mockResolvedValue(provider);
    const user = userEvent.setup();
    renderEditor(
      createModel({
        generate_kwargs: { max_tokens: 8192, temperature: 0.2 },
      }),
    );

    await user.click(
      screen.getByRole("button", { name: "models.resetMaxTokens" }),
    );
    await user.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => expect(api.configureModel).toHaveBeenCalledOnce());
    expect(api.configureModel).toHaveBeenCalledWith(
      "openai",
      "test-model",
      expect.objectContaining({
        generate_kwargs: { temperature: 0.2 },
      }),
    );
  });
});

describe("ModelConfigEditor automatic context", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the runtime context without saving it as an override", async () => {
    vi.mocked(api.configureModel).mockResolvedValue(provider);
    const user = userEvent.setup();
    renderEditor(
      createModel({
        effective_max_input_length: 1000000,
        automatic_max_input_length: 1000000,
        context_length_source: "template",
      }),
      "budget",
    );
    expect(
      screen.getByRole("spinbutton", { name: "models.maxInputLengthLabel" }),
    ).toHaveValue(1000000);
    await user.hover(
      within(screen.getByText("models.maxInputLengthLabel")).getByRole(
        "button",
        { name: "common.help" },
      ),
    );
    expect(
      await screen.findByText(/models.metadataSource.template/),
    ).toBeInTheDocument();
    await user.click(screen.getAllByRole("switch")[0]);
    await user.click(screen.getByRole("button", { name: /Save/i }));
    await waitFor(() => expect(api.configureModel).toHaveBeenCalledOnce());
    expect(vi.mocked(api.configureModel).mock.calls[0][2]).not.toHaveProperty(
      "max_input_length",
    );
  });

  it("clears a manual override and previews the automatic context", async () => {
    vi.mocked(api.configureModel).mockResolvedValue(provider);
    const user = userEvent.setup();
    renderEditor(
      createModel({
        max_input_length: 16000,
        max_input_length_configured: true,
        effective_max_input_length: 16000,
        automatic_max_input_length: 64000,
        context_length_source: "user",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "models.resetContextLength" }),
    );
    expect(
      screen.getByRole("spinbutton", { name: "models.maxInputLengthLabel" }),
    ).toHaveValue(64000);
    await user.click(screen.getByRole("button", { name: /Save/i }));
    await waitFor(() => expect(api.configureModel).toHaveBeenCalledOnce());
    expect(
      vi.mocked(api.configureModel).mock.calls[0][2].max_input_length,
    ).toBeNull();
  });
});

describe("ModelConfigEditor thinking capability linkage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("updates the thinking control when the advanced declaration changes", async () => {
    vi.mocked(api.configureModel).mockResolvedValue(provider);
    const user = userEvent.setup();
    renderEditor(
      createModel({
        thinking_control: {
          kind: "budget",
          efforts: [],
          supports_off: true,
          budget_min: 1,
          budget_max: 8192,
        },
        thinking_enabled: true,
        thinking_budget: 4096,
      }),
    );

    expect(
      screen.getByRole("slider", { name: "thinkingControl.title" }),
    ).toBeInTheDocument();
    await user.click(screen.getByText("common.advancedSettings"));
    await user.click(screen.getByText("thinkingControl.declaration"));
    await user.click(
      screen.getByRole("combobox", { name: "thinkingControl.controlType" }),
    );
    await user.click(screen.getByText("thinkingControl.type.unsupported"));

    expect(
      screen.queryByRole("slider", { name: "thinkingControl.title" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "thinkingControl.unsupported" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Save/i }));
    await waitFor(() => expect(api.configureModel).toHaveBeenCalledOnce());
    expect(api.configureModel).toHaveBeenCalledWith(
      "openai",
      "test-model",
      expect.objectContaining({
        thinking_control: expect.objectContaining({ kind: "unsupported" }),
        thinking_enabled: null,
        thinking_budget: null,
        reasoning_effort: null,
      }),
    );
  });

  it("clears stale thinking settings when restoring automatic capability", async () => {
    vi.mocked(api.configureModel).mockResolvedValue(provider);
    const user = userEvent.setup();
    renderEditor(
      createModel({
        thinking_control: {
          kind: "budget",
          efforts: [],
          supports_off: true,
          budget_min: 1,
          budget_max: 8192,
        },
        thinking_enabled: true,
        thinking_budget: 4096,
      }),
    );

    await user.click(screen.getByText("common.advancedSettings"));
    await user.click(screen.getByText("thinkingControl.declaration"));
    await user.click(
      screen.getByRole("combobox", { name: "thinkingControl.controlType" }),
    );
    await user.click(screen.getByText("thinkingControl.type.unknown"));

    expect(
      screen.queryByRole("slider", { name: "thinkingControl.title" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Save/i }));
    await waitFor(() => expect(api.configureModel).toHaveBeenCalledOnce());
    expect(api.configureModel).toHaveBeenCalledWith(
      "openai",
      "test-model",
      expect.objectContaining({
        thinking_control: null,
        thinking_enabled: null,
        thinking_budget: null,
        reasoning_effort: null,
      }),
    );
  });

  it("applies edited budget bounds to the thinking slider", async () => {
    const user = userEvent.setup();
    renderEditor(
      createModel({
        thinking_control: {
          kind: "budget",
          efforts: [],
          supports_off: true,
          budget_min: 1,
          budget_max: 8192,
        },
      }),
    );

    await user.click(screen.getByText("common.advancedSettings"));
    await user.click(screen.getByText("thinkingControl.declaration"));
    const maximum = screen.getByRole("spinbutton", {
      name: /thinkingControl.maximum/,
    });
    await user.clear(maximum);
    await user.type(maximum, "2048");

    expect(
      screen.getByRole("slider", { name: "thinkingControl.title" }),
    ).toHaveAttribute("aria-valuemax", "2048");
  });
});
