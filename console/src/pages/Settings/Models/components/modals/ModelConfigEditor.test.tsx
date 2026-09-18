import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
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
    expect(
      screen.getByText(/models.metadataSource.template/),
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
