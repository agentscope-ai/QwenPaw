import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ModelInfo } from "../../../../../api/types";
import { renderWithProviders } from "@/test/common_setup";

// The inherited hint interpolates the effective value into translated text,
// so this file needs a real i18next instance (the shared test setup renders
// raw keys, which would hide the number entirely).
import "@/i18n";

import { ContextLengthField } from "./ModelTokenFields";

type WindowModel = Pick<
  ModelInfo,
  | "max_input_length"
  | "effective_max_input_length"
  | "effective_max_input_length_source"
>;

function renderField(model: WindowModel, value: number | null = null) {
  const onChange = vi.fn();
  renderWithProviders(
    <ContextLengthField value={value} onChange={onChange} model={model} />,
  );
  return { onChange };
}

describe("ContextLengthField", () => {
  it("shows the inherited window and where it comes from", () => {
    renderField({
      max_input_length: null,
      effective_max_input_length: 272000,
      effective_max_input_length_source: "catalog",
    });

    expect(screen.getByPlaceholderText("272000")).toBeInTheDocument();
    expect(
      screen.getByText(/Inherited · effective 272,000 · from built-in catalog/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Clear override/i }),
    ).toBeNull();
  });

  it("labels the 128k fallback as the default source", () => {
    renderField({
      max_input_length: null,
      effective_max_input_length: 131072,
      effective_max_input_length_source: "default",
    });

    expect(
      screen.getByText(/Inherited · effective 131,072 · from 128K default/),
    ).toBeInTheDocument();
  });

  it("shows a user override without the inherited hint", async () => {
    const user = userEvent.setup();
    const { onChange } = renderField(
      {
        max_input_length: 65536,
        effective_max_input_length: 65536,
        effective_max_input_length_source: "user",
      },
      65536,
    );

    expect(screen.getByDisplayValue("65536")).toBeInTheDocument();
    expect(screen.queryByText(/Inherited ·/)).toBeNull();

    await user.click(screen.getByRole("button", { name: /Clear override/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
