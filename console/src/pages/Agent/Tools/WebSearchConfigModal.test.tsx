import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ModalFuncProps } from "antd";

const hoisted = vi.hoisted(() => ({
  getToolConfig: vi.fn().mockResolvedValue({}),
  confirm: vi.fn(),
}));

vi.mock("../../../api", () => ({
  default: {
    getToolConfig: hoisted.getToolConfig,
  },
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { destroy: vi.fn(), error: vi.fn() },
    modal: { confirm: hoisted.confirm },
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// The design package's ESM build loses antd Form's static methods (useForm /
// useWatch) under Vitest's CJS interop. Bridge the components the modal uses
// to the real antd implementations; everything else stays as-is.
vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const antd = await import("antd");
  const original = (await importOriginal()) as Record<string, unknown>;
  return {
    ...original,
    Form: antd.Form,
    Modal: antd.Modal,
    Input: antd.Input,
    Select: antd.Select,
  };
});

import type { ToolInfo } from "../../../api/modules/tools";
import { WebSearchConfigModal } from "./WebSearchConfigModal";

const tool: ToolInfo = {
  name: "web_search",
  enabled: true,
  async_execution: false,
  description: "Search the web",
  icon: "🔎",
  config_fields: [],
  config_values: {},
};

function renderModal(onSave = vi.fn(), onClose = vi.fn()) {
  return render(
    <WebSearchConfigModal
      tool={tool}
      visible
      onClose={onClose}
      onSave={onSave}
    />,
  );
}

// antd Modal renders in a portal attached to document.body, so the modal
// content is not inside the render() container — query globally.
function passwordInput(): HTMLInputElement | null {
  return document.querySelector('input[type="password"]');
}

// The selected option is rendered as .ant-select-selection-item with the
// option text; the combobox itself carries no readable text.
function selectedProvider(): string {
  return (
    document.querySelector(".ant-select-selection-item")?.textContent ?? ""
  );
}

async function switchProvider(provider: string) {
  fireEvent.mouseDown(screen.getByRole("combobox"));
  await waitFor(() => {
    expect(screen.getByTitle(provider)).toBeInTheDocument();
  });
  fireEvent.click(screen.getByTitle(provider));
}

describe("WebSearchConfigModal", () => {
  beforeEach(() => {
    hoisted.getToolConfig.mockReset();
    hoisted.getToolConfig.mockResolvedValue({});
  });
  it("fetches saved config on open and backfills provider + masked key", async () => {
    hoisted.getToolConfig.mockResolvedValueOnce({
      provider: "anysearch",
      api_key: "***masked***",
    });
    renderModal();

    await waitFor(() => {
      expect(hoisted.getToolConfig).toHaveBeenCalledWith("web_search");
    });
    expect(selectedProvider()).toBe("anysearch");
    expect(passwordInput()).toHaveValue("***masked***");
  });

  it("shows the optional api_key field and tavily hint while provider is tavily", async () => {
    hoisted.getToolConfig.mockResolvedValueOnce({});
    renderModal();

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });
    expect(passwordInput()).not.toBeNull();
    expect(
      screen.getAllByText(
        (_, el) =>
          el?.textContent?.includes("tools.webSearchTavilyKeyHintBefore") ??
          false,
      ).length,
    ).toBeGreaterThan(0);
    const link = screen.getByRole("link", { name: "tavily.com" });
    expect(link).toHaveAttribute("href", "https://tavily.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(
      screen.queryByRole("link", { name: "anysearch.com" }),
    ).not.toBeInTheDocument();
  });

  it("switching to anysearch shows the api_key field, quota hint and register link", async () => {
    hoisted.getToolConfig.mockResolvedValueOnce({});
    renderModal();

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });

    await switchProvider("anysearch");

    expect(passwordInput()).not.toBeNull();
    // Typography.Text splits the hint into before/link/after children, so
    // match on the combined textContent instead of a single text node. The
    // matcher also hits ancestor elements, hence getAllByText.
    expect(
      screen.getAllByText(
        (_, el) =>
          el?.textContent?.includes("tools.webSearchQuotaHintBefore") ?? false,
      ).length,
    ).toBeGreaterThan(0);
    const link = screen.getByRole("link", { name: "anysearch.com" });
    expect(link).toHaveAttribute("href", "https://anysearch.com");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("lists firecrawl and loads its credential slot when selected", async () => {
    hoisted.getToolConfig.mockResolvedValueOnce({});
    renderModal();

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });

    await switchProvider("firecrawl");

    expect(passwordInput()).not.toBeNull();
    await waitFor(() => {
      expect(hoisted.getToolConfig).toHaveBeenLastCalledWith("web_search", {
        provider: "firecrawl",
      });
    });
  });

  it("re-fetches with the selected provider when switching inside the modal", async () => {
    hoisted.getToolConfig.mockResolvedValueOnce({});
    renderModal();

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });

    await switchProvider("anysearch");

    await waitFor(() => {
      expect(hoisted.getToolConfig).toHaveBeenLastCalledWith("web_search", {
        provider: "anysearch",
      });
    });
  });

  it("refills the api_key from the switched provider's credential slot", async () => {
    hoisted.getToolConfig
      .mockResolvedValueOnce({}) // open: saved config (tavily)
      .mockResolvedValueOnce({
        // switch to anysearch: its own credential slot
        provider: "anysearch",
        api_key: "***as_sk_restored***",
      });
    renderModal();

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });

    await switchProvider("anysearch");

    await waitFor(() => {
      expect(passwordInput()).toHaveValue("***as_sk_restored***");
    });
  });

  it("saves the submitted values through onSave", async () => {
    hoisted.getToolConfig.mockResolvedValueOnce({});
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderModal(onSave);

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });

    await switchProvider("anysearch");

    // Switching provider triggers a credential re-fetch; the OK button stays
    // disabled until loadingConfig clears. Wait before typing as the fetched
    // credential is allowed to refill the field while loading.
    await waitFor(() => expect(passwordInput()).not.toBeDisabled());
    fireEvent.change(passwordInput()!, { target: { value: "as_sk_new" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({
        provider: "anysearch",
        api_key: "as_sk_new",
      });
    });
  });

  it("saves a tavily api_key into the tavily credential slot", async () => {
    hoisted.getToolConfig.mockResolvedValueOnce({});
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderModal(onSave);

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });
    await waitFor(() => expect(passwordInput()).not.toBeNull());
    await waitFor(() => expect(passwordInput()).not.toBeDisabled());
    fireEvent.change(passwordInput()!, { target: { value: "tvly-new" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({
        provider: "tavily",
        api_key: "tvly-new",
      });
    });
  });
});

describe("WebSearchConfigModal provider-slot isolation", () => {
  beforeEach(() => {
    hoisted.getToolConfig.mockReset();
    hoisted.getToolConfig.mockResolvedValue({});
  });

  it("loads the tavily credential slot when switching back from anysearch", async () => {
    hoisted.getToolConfig
      .mockResolvedValueOnce({}) // open: saved config (tavily)
      .mockResolvedValueOnce({
        // switch to anysearch: its own credential slot
        provider: "anysearch",
        api_key: "***as_sk_restored***",
      })
      .mockResolvedValueOnce({
        // switch back to tavily: its own credential slot
        provider: "tavily",
        api_key: "***tvly_restored***",
      });
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderModal(onSave);

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });

    await switchProvider("anysearch");
    await waitFor(() => {
      expect(passwordInput()).toHaveValue("***as_sk_restored***");
    });

    await switchProvider("tavily");
    await waitFor(() => {
      expect(passwordInput()).toHaveValue("***tvly_restored***");
    });
    await waitFor(() => {
      expect(hoisted.getToolConfig).toHaveBeenLastCalledWith("web_search", {
        provider: "tavily",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({
        provider: "tavily",
        api_key: "***tvly_restored***",
      });
    });
  });
});

describe("WebSearchConfigModal failed provider switch", () => {
  beforeEach(() => {
    hoisted.getToolConfig.mockReset();
    hoisted.getToolConfig.mockResolvedValue({});
  });

  it("does not save when the firecrawl slot fails to load", async () => {
    hoisted.getToolConfig
      .mockResolvedValueOnce({
        provider: "anysearch",
        api_key: "as-private-draft",
      })
      .mockRejectedValueOnce(new Error("network"));
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <WebSearchConfigModal
        tool={tool}
        visible
        onClose={onClose}
        onSave={onSave}
      />,
    );

    await waitFor(() => {
      expect(passwordInput()).toHaveValue("as-private-draft");
    });

    await switchProvider("firecrawl");

    await waitFor(() => {
      expect(
        screen.getByText("tools.webSearchConfigLoadError"),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("does not save the previous provider key when the new slot fails to load", async () => {
    hoisted.getToolConfig
      .mockResolvedValueOnce({
        provider: "tavily",
        api_key: "tvly-private-draft",
      })
      .mockRejectedValueOnce(new Error("network"));
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <WebSearchConfigModal
        tool={tool}
        visible
        onClose={onClose}
        onSave={onSave}
      />,
    );

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });
    await waitFor(() => {
      expect(passwordInput()).toHaveValue("tvly-private-draft");
    });

    await switchProvider("anysearch");

    await waitFor(() => {
      expect(
        screen.getByText("tools.webSearchConfigLoadError"),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("WebSearchConfigModal initial-load failure", () => {
  beforeEach(() => {
    hoisted.getToolConfig.mockReset();
    hoisted.getToolConfig.mockResolvedValue({});
  });

  it("retries the saved-config request instead of forcing the tavily slot", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    hoisted.getToolConfig
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({
        provider: "anysearch",
        api_key: "***as_sk_restored***",
      });

    render(
      <WebSearchConfigModal
        tool={tool}
        visible
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByText("tools.webSearchConfigLoadError"),
      ).toBeInTheDocument();
    });
    expect(hoisted.getToolConfig).toHaveBeenCalledWith("web_search");
    expect(hoisted.getToolConfig).not.toHaveBeenCalledWith("web_search", {
      provider: "tavily",
    });

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));

    await waitFor(() => {
      expect(selectedProvider()).toBe("anysearch");
    });
    expect(passwordInput()).toHaveValue("***as_sk_restored***");
    // Retry must call the initial saved-config endpoint again (no provider).
    expect(
      hoisted.getToolConfig.mock.calls.filter(
        (args) => args.length === 1 && args[0] === "web_search",
      ),
    ).toHaveLength(2);
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("WebSearchConfigModal close behavior", () => {
  beforeEach(() => {
    hoisted.getToolConfig.mockReset();
    hoisted.getToolConfig.mockResolvedValue({});
    hoisted.confirm.mockReset();
  });

  it("closes without saving or confirming while a provider slot is loading", async () => {
    hoisted.getToolConfig
      .mockResolvedValueOnce({
        provider: "tavily",
        api_key: "***tvly_saved***",
      })
      .mockImplementationOnce(() => new Promise(() => {}));
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    renderModal(onSave, onClose);

    await waitFor(() => expect(passwordInput()).not.toBeDisabled());
    await switchProvider("anysearch");
    await waitFor(() => expect(passwordInput()).toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledOnce();
    expect(onSave).not.toHaveBeenCalled();
    expect(hoisted.confirm).not.toHaveBeenCalled();
  });

  it("lets users keep or discard edits after a loaded configuration fails to save", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("offline"));
    const onClose = vi.fn();
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const view = renderModal(onSave, onClose);

    await waitFor(() => expect(passwordInput()).not.toBeDisabled());
    fireEvent.change(passwordInput()!, { target: { value: "tvly-new" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(hoisted.confirm).toHaveBeenCalledOnce());
    expect(onClose).not.toHaveBeenCalled();
    const keepEditing = hoisted.confirm.mock.calls[0][0] as ModalFuncProps;
    await act(async () => {
      keepEditing.onCancel?.();
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(passwordInput()).toHaveValue("tvly-new");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(hoisted.confirm).toHaveBeenCalledTimes(2));
    const discardEdits = hoisted.confirm.mock.calls[1][0] as ModalFuncProps;
    await act(async () => {
      discardEdits.onOk?.();
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());

    view.unmount();
    await act(async () => {});
    expect(onSave).toHaveBeenCalledTimes(2);
    error.mockRestore();
  });
});
