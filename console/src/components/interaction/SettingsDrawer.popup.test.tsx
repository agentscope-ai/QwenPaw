// @vitest-environment jsdom
import { useState } from "react";
import { Form, Select } from "antd";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OsAppHost from "@/os/OsAppHost";
import { renderWithProviders } from "@/test/common_setup";
import { ExecutionModelSelect } from "@/pages/Control/CronJobs/components/ExecutionModelSelect";
import { SettingsDrawer } from "./SettingsDrawer";

const api = vi.hoisted(() => ({ listProviders: vi.fn() }));

vi.mock("@/api/modules/provider", () => ({ providerApi: api }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function setViewport(desktop: boolean) {
  vi.mocked(window.matchMedia).mockImplementation((query: string) => ({
    matches: desktop && query.includes("min-width: 768px"),
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function DrawerHarness() {
  const [open, setOpen] = useState(true);
  const [slot, setSlot] = useState<{
    provider_id: string;
    model: string;
  } | null>(null);
  const [form] = Form.useForm();
  const values = Form.useWatch([], form);
  const modelSlot = Form.useWatch(["request", "model_slot_override"], {
    form,
    preserve: true,
  });

  return (
    <OsAppHost>
      <SettingsDrawer
        open={open}
        onClose={() => setOpen(false)}
        title="Cron editor"
      >
        <Form
          form={form}
          initialValues={{
            request: { model_slot_override: null },
            dispatch: { mode: "stream" },
          }}
        >
          <ExecutionModelSelect
            value={slot}
            onChange={(next) => {
              setSlot(next);
              form.setFieldValue(["request", "model_slot_override"], next);
            }}
          />
          <Form.Item name={["dispatch", "mode"]}>
            <Select
              aria-label="dispatch mode"
              options={[
                { value: "stream", label: "stream" },
                { value: "final", label: "final" },
              ]}
            />
          </Form.Item>
        </Form>
        <output data-testid="form-values">
          {JSON.stringify({ ...values, modelSlot })}
        </output>
      </SettingsDrawer>
    </OsAppHost>
  );
}

async function selectProviderAndModel(desktop: boolean) {
  const user = userEvent.setup();
  const provider = await screen.findByRole("combobox", {
    name: "models.provider",
  });
  const model = screen.getByRole("combobox", { name: "models.model" });

  expect(model).toBeDisabled();
  await user.click(provider);
  const providerOption = await screen.findByText("Provider One", {
    selector: ".ant-select-item-option-content",
  });
  const providerOptionTarget = providerOption.closest<HTMLElement>(
    ".ant-select-item-option",
  );
  const overlayRoot = document.querySelector(".os-window-overlay-root");
  const popup = providerOption.closest("[class*='select-dropdown']");
  expect(overlayRoot).not.toBeNull();
  expect(popup).not.toBeNull();
  expect(providerOptionTarget).not.toBeNull();
  expect(overlayRoot!.contains(popup)).toBe(desktop);
  if (desktop) {
    expect(providerOption.closest('[role="dialog"]')).toBeNull();
  } else {
    expect(popup!.parentElement).toHaveAttribute("data-vaul-drawer");
  }
  await user.click(providerOptionTarget!);

  await waitFor(() =>
    expect(
      screen.getByRole("combobox", { name: "models.model" }),
    ).not.toBeDisabled(),
  );
  expect(provider.closest(".ant-select")).toHaveTextContent("Provider One");
  expect(
    screen
      .getByRole("combobox", { name: "models.model" })
      .closest(".ant-select"),
  ).toHaveTextContent("Model One (model-one)");
  expect(screen.getByTestId("form-values")).toHaveTextContent(
    '"provider_id":"provider-one","model":"model-one"',
  );
  expect(screen.getByTestId("form-values")).toHaveTextContent(
    '"dispatch":{"mode":"stream"}',
  );

  await user.click(screen.getByRole("combobox", { name: "models.model" }));
  const modelOption = await screen.findByText("Model Two (model-two)", {
    selector: ".ant-select-item-option-content",
  });
  await user.click(
    modelOption.closest<HTMLElement>(".ant-select-item-option")!,
  );
  expect(screen.getByTestId("form-values")).toHaveTextContent(
    '"provider_id":"provider-one","model":"model-two"',
  );
  expect(
    screen
      .getByRole("combobox", { name: "models.model" })
      .closest(".ant-select"),
  ).toHaveTextContent("Model Two (model-two)");
  expect(screen.getByTestId("form-values")).toHaveTextContent(
    '"dispatch":{"mode":"stream"}',
  );
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  api.listProviders.mockResolvedValue([
    {
      id: "provider-one",
      name: "Provider One",
      is_custom: true,
      base_url: "https://example.test",
      models: [
        { id: "model-one", name: "Model One" },
        { id: "model-two", name: "Model Two" },
      ],
      extra_models: [],
    },
  ]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SettingsDrawer popup interaction", () => {
  it("keeps real Select popups clickable in the desktop modal", async () => {
    setViewport(true);
    renderWithProviders(<DrawerHarness />);
    await selectProviderAndModel(true);
  });

  it("keeps real Select popups clickable in the mobile bottom sheet", async () => {
    setViewport(false);
    renderWithProviders(<DrawerHarness />);
    await selectProviderAndModel(false);
  });
});
