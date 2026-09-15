// @vitest-environment jsdom
import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExecutionModelSelect } from "./ExecutionModelSelect";
const api = vi.hoisted(() => ({ listProviders: vi.fn() }));
vi.mock("../../../../api/modules/provider", () => ({ providerApi: api }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("antd", () => ({
  Select: ({
    value,
    options,
    onChange,
    disabled,
    "aria-label": label,
  }: any) => (
    <select
      aria-label={label}
      disabled={disabled}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((item: any) => (
        <option key={item.value} value={item.value}>
          {item.label}
        </option>
      ))}
    </select>
  ),
  Alert: ({ message }: any) => <div role="alert">{message}</div>,
}));
afterEach(cleanup);
beforeEach(() => {
  api.listProviders.mockResolvedValue([
    {
      id: "p",
      name: "Provider",
      is_custom: true,
      base_url: "https://example.test",
      models: [
        { id: "model:v1", name: "Model" },
        { id: "model:v2", name: "Model 2" },
      ],
      extra_models: [],
    },
  ]);
});
describe("ExecutionModelSelect", () => {
  it("keeps old tasks at Default without emitting a configuration change", async () => {
    const change = vi.fn();
    render(<ExecutionModelSelect onChange={change} />);
    await screen.findByText("Provider");
    expect(
      (
        screen.getByRole("combobox", {
          name: "models.provider",
        }) as HTMLSelectElement
      ).value,
    ).toBe("");
    expect(
      (
        screen.getByRole("combobox", {
          name: "models.model",
        }) as HTMLSelectElement
      ).disabled,
    ).toBe(true);
    expect(change).not.toHaveBeenCalled();
  });
  it("selects a task model and allows returning to Default", async () => {
    const change = vi.fn();
    render(
      <ExecutionModelSelect
        value={{ provider_id: "p", model: "model:v1" }}
        onChange={change}
      />,
    );
    await screen.findByText("Provider");
    expect(
      (
        screen.getByRole("combobox", {
          name: "models.provider",
        }) as HTMLSelectElement
      ).value,
    ).toBe("p");
    fireEvent.change(
      screen.getByRole("combobox", { name: "models.provider" }),
      { target: { value: "" } },
    );
    expect(
      (
        screen.getByRole("combobox", {
          name: "models.model",
        }) as HTMLSelectElement
      ).value,
    ).toBe("model:v1");
    expect(change).toHaveBeenLastCalledWith(null);
    fireEvent.change(
      screen.getByRole("combobox", { name: "models.provider" }),
      {
        target: { value: "p" },
      },
    );
    expect(change).toHaveBeenLastCalledWith({
      provider_id: "p",
      model: "model:v1",
    });
  });
  it("changes the model within the selected provider", async () => {
    const change = vi.fn();
    render(
      <ExecutionModelSelect
        value={{ provider_id: "p", model: "model:v1" }}
        onChange={change}
      />,
    );
    await screen.findByText("Model 2 (model:v2)");
    fireEvent.change(screen.getByRole("combobox", { name: "models.model" }), {
      target: { value: "model:v2" },
    });
    expect(change).toHaveBeenLastCalledWith({
      provider_id: "p",
      model: "model:v2",
    });
  });
  it("preserves a saved model when loading fails", async () => {
    api.listProviders.mockRejectedValue(new Error("offline"));
    const change = vi.fn();
    render(<ExecutionModelSelect value="removed:model" onChange={change} />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(
      (
        screen.getByRole("combobox", {
          name: "models.provider",
        }) as HTMLSelectElement
      ).value,
    ).toBe("removed");
    expect(change).not.toHaveBeenCalled();
  });
});
