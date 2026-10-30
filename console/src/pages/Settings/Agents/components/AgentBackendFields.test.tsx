// @vitest-environment jsdom
import React from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { Button, Form, Input, Tooltip } from "antd";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  harnessRegistry,
  type HarnessBackendDescriptor,
  type HarnessSettingsProps,
} from "@/plugins/harnesses";
import { renderWithProviders } from "@/test/common_setup";
import { AgentBackendFields } from "./AgentBackendFields";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const owners = ["first-owner", "second-owner"];
let rows: HarnessBackendDescriptor[] = [];
let currentForm: ReturnType<typeof Form.useForm>[0];
const originalHost = Object.getOwnPropertyDescriptor(window, "QwenPaw");
const vendorFetch = vi.fn();
let vendorSettings: Record<string, React.ComponentType<HarnessSettingsProps>>;

beforeAll(async () => {
  Object.defineProperty(window, "QwenPaw", {
    configurable: true,
    value: {
      host: {
        React,
        antd: {
          Button,
          Input,
          Tooltip,
          App: {
            useApp: () => ({ message: { success: vi.fn(), error: vi.fn() } }),
          },
        },
        fetch: vendorFetch,
        useLocale: () => "en",
      },
    },
  });
  // Load the real plugin modules without adding their separate TS projects to
  // the Console production type-check graph. Vitest resolves the public SDK.
  const modules = import.meta.glob<{
    Settings: React.ComponentType<HarnessSettingsProps>;
  }>("../../../../../../plugins/harness/*/frontend/src/Settings.tsx");
  const [codex, qoder] = await Promise.all([
    modules[
      "../../../../../../plugins/harness/codex/frontend/src/Settings.tsx"
    ](),
    modules[
      "../../../../../../plugins/harness/qoder/frontend/src/Settings.tsx"
    ](),
  ]);
  vendorSettings = { codex: codex.Settings, qoder: qoder.Settings };
});

afterAll(() => {
  if (originalHost) Object.defineProperty(window, "QwenPaw", originalHost);
  else Reflect.deleteProperty(window, "QwenPaw");
});

function descriptor(
  id: string,
  pluginId: string,
  status: HarnessBackendDescriptor["status"] = "available",
): HarnessBackendDescriptor {
  return {
    id,
    label: id,
    plugin_id: pluginId,
    status,
    capabilities: {},
    config_fields: [],
  };
}

function BackendForm({
  backend = "qwenpaw",
  settings = {},
}: {
  backend?: string;
  settings?: Record<string, unknown>;
}) {
  const [form] = Form.useForm();
  currentForm = form;
  return (
    <Form form={form} initialValues={{ backend, backend_settings: settings }}>
      <AgentBackendFields form={form} open />
    </Form>
  );
}

describe("AgentBackendFields", () => {
  beforeEach(() => {
    vendorFetch
      .mockReset()
      .mockImplementation(
        async (path: string) =>
          new Response(
            JSON.stringify(
              path.endsWith("/login")
                ? { type: "external", loginId: "local" }
                : { installed: true, authenticated: false, account: null },
            ),
            { headers: { "Content-Type": "application/json" } },
          ),
      );
    rows = [];
    harnessRegistry.syncCatalog([]);
    owners.forEach((owner) => harnessRegistry.disposeAll(owner));
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify({ backends: rows }), {
          headers: { "Content-Type": "application/json" },
        }),
    );
  });

  afterEach(() => {
    owners.forEach((owner) => harnessRegistry.disposeAll(owner));
    harnessRegistry.syncCatalog([]);
    vi.restoreAllMocks();
  });

  it("offers native creation and installation without probing absent vendors", async () => {
    renderWithProviders(<BackendForm />);
    fireEvent.click(screen.getByText("agent.backend.thirdPartyTitle"));

    expect(screen.getByText("agent.backend.nativeTitle")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "agent.backend.installPlugin" }),
    ).toHaveAttribute("href", "/market?tab=plugins&view=official");
    expect(screen.queryByText("Codex")).not.toBeInTheDocument();
    expect(screen.queryByText("Qoder")).not.toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.every(([url]) => !String(url).includes("/harnesses/")),
    ).toBe(true);
    expect(vendorFetch).not.toHaveBeenCalled();
    expect(currentForm.getFieldValue("backend")).toBe("qwenpaw");
  });

  it.each(["missing", "disabled", "failed"] as const)(
    "keeps the identity and settings of a saved %s backend",
    async (state) => {
      if (state !== "missing") {
        rows = [descriptor("retired", "first-owner", state)];
        harnessRegistry.syncCatalog(rows);
      }
      const settings = { model: "saved-model", binary: "/saved/path" };
      renderWithProviders(
        <BackendForm backend="retired" settings={settings} />,
      );

      expect(await screen.findByRole("status")).toHaveTextContent("retired");
      expect(screen.getByRole("status")).toHaveTextContent(
        `agent.backend.states.${state}`,
      );
      expect(currentForm.getFieldValue("backend")).toBe("retired");
      expect(currentForm.getFieldValue("backend_settings")).toEqual(settings);
    },
  );

  it("renders and writes settings only for the selected active owner", async () => {
    rows = [
      descriptor("first", "first-owner"),
      descriptor("second", "second-owner"),
    ];
    harnessRegistry.syncCatalog(rows);
    const first = vi.fn(() => React.createElement("p", {}, "first settings"));
    const second = vi.fn((props: HarnessSettingsProps) =>
      React.createElement(
        "button",
        {
          onClick: () =>
            props.onChange({ ...props.value, model: "second-model" }),
        },
        "second settings",
      ),
    );
    harnessRegistry.register("first-owner", {
      backendId: "first",
      SettingsComponent: first,
    });
    harnessRegistry.register("second-owner", {
      backendId: "second",
      SettingsComponent: second,
    });

    renderWithProviders(
      <BackendForm backend="second" settings={{ preserved: true }} />,
    );
    fireEvent.click(await screen.findByText("second settings"));
    expect(screen.queryByText("first settings")).not.toBeInTheDocument();
    expect(first).not.toHaveBeenCalled();
    expect(currentForm.getFieldValue("backend_settings")).toEqual({
      preserved: true,
      model: "second-model",
    });

    act(() => {
      rows = [rows[0], descriptor("second", "second-owner", "disabled")];
      harnessRegistry.syncCatalog(rows);
    });
    expect(screen.queryByText("second settings")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "agent.backend.states.disabled",
    );
    expect(currentForm.getFieldValue("backend")).toBe("second");
  });

  it.each([
    ["codex", "Codex executable", "Connect with ChatGPT"],
    ["qoder", "Qoder executable", "Connect to Qoder"],
  ])(
    "passes saved and edited %s settings to its real status and login requests",
    async (backend, binaryLabel, loginLabel) => {
      rows = [descriptor(backend, "first-owner")];
      harnessRegistry.syncCatalog(rows);
      harnessRegistry.register("first-owner", {
        backendId: backend,
        SettingsComponent: vendorSettings[backend],
      });
      vi.spyOn(window, "open").mockReturnValue(null);
      const saved = { binary: `/saved/${backend}`, model: "saved-model" };
      renderWithProviders(<BackendForm backend={backend} settings={saved} />);

      const connect = await screen.findByRole("button", { name: loginLabel });
      await waitFor(() => expect(connect).toBeEnabled());
      expect(vendorFetch).toHaveBeenCalledWith(`/harnesses/${backend}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: saved, device_code: false }),
      });
      const edited = { ...saved, binary: `/custom/${backend}` };
      fireEvent.change(screen.getByRole("textbox", { name: binaryLabel }), {
        target: { value: edited.binary },
      });
      expect(currentForm.getFieldValue("backend_settings")).toEqual(edited);
      fireEvent.click(screen.getByRole("button", { name: "Detect" }));
      await waitFor(() =>
        expect(vendorFetch).toHaveBeenLastCalledWith(
          `/harnesses/${backend}/status`,
          expect.objectContaining({
            body: JSON.stringify({ settings: edited, device_code: false }),
          }),
        ),
      );
      fireEvent.click(connect);
      await waitFor(() =>
        expect(vendorFetch).toHaveBeenCalledWith(
          `/harnesses/${backend}/login`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ settings: edited, device_code: false }),
          },
        ),
      );
    },
  );
});
