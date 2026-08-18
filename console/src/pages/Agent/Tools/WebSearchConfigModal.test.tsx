import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const hoisted = vi.hoisted(() => ({
  getToolConfig: vi.fn().mockResolvedValue({}),
}));

vi.mock("../../../api", () => ({
  default: {
    getToolConfig: hoisted.getToolConfig,
  },
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

function renderModal(onSave = vi.fn()) {
  return render(
    <WebSearchConfigModal
      tool={tool}
      visible
      onClose={vi.fn()}
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

  it("hides the api_key field and hint while provider is tavily (default)", async () => {
    hoisted.getToolConfig.mockResolvedValueOnce({});
    renderModal();

    await waitFor(() => {
      expect(selectedProvider()).toBe("tavily");
    });
    expect(passwordInput()).toBeNull();
    expect(
      screen.queryByText("tools.webSearchQuotaHintBefore"),
    ).not.toBeInTheDocument();
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
    fireEvent.change(passwordInput()!, { target: { value: "as_sk_new" } });

    // Switching provider triggers a credential re-fetch; the OK button stays
    // disabled until loadingConfig clears. Wait for it to be clickable.
    const okButton = screen.getByText("common.save").closest("button")!;
    await waitFor(() => {
      expect(okButton).not.toBeDisabled();
    });
    fireEvent.click(okButton);

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({
        provider: "anysearch",
        api_key: "as_sk_new",
      });
    });
  });
});

describe("WebSearchConfigModal keyless-provider guard", () => {
  it("drops the leftover api_key when switching back to tavily and saving", async () => {
    hoisted.getToolConfig
      .mockResolvedValueOnce({}) // open: saved config (tavily)
      .mockResolvedValueOnce({
        // switch to anysearch: its own credential slot
        provider: "anysearch",
        api_key: "***as_sk_restored***",
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

    // Back to tavily: the key must not be submitted into its slot.
    await switchProvider("tavily");
    const okButton = screen.getByText("common.save").closest("button")!;
    await waitFor(() => {
      expect(okButton).not.toBeDisabled();
    });
    fireEvent.click(okButton);

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({ provider: "tavily" });
    });
  });
});
