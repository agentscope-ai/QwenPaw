/**
 * ProviderConfigModal — provider configuration dialog covering the save
 * flow, connection testing, authorization revocation, custom headers,
 * Anthropic auth-mode switching and the embedded JSON config editor.
 *
 * Regression family: Settings/Models modal cluster (repeated CI intercepts
 * 2026-08-28 .. 2026-09-02 per Appraiser ci_intercepts). Uses the real antd
 * Form/Input/Select/Radio (bridged over the design stub whose ESM build loses
 * antd Form statics under Vitest CJS interop), and a spy on the imperative
 * Modal.confirm so the revoke dialog can be driven deterministically.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const apiMocks = vi.hoisted(() => ({
  testProviderConnection: vi.fn(),
  configureProvider: vi.fn(),
}));

vi.mock("../../../../../api", () => ({
  default: apiMocks,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
}));

const confirmSpy = vi.hoisted(() => vi.fn());

// Bridge the modal to the real antd implementations so the real form
// validation paths execute (the design stub's Form lacks useForm/useWatch
// under Vitest's CJS interop). Modal is replaced with a renderer that shows
// the footer and captures imperative confirm() calls.
vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const antd = await import("antd");
  const original = (await importOriginal()) as Record<string, unknown>;

  const modalLike = ({ children, footer, title }: Record<string, unknown>) =>
    React.createElement(
      "div",
      { role: "dialog" },
      title ? React.createElement("div", null, title as any) : null,
      children as any,
      footer ? React.createElement("div", null, footer as any) : null,
    );

  return {
    ...original,
    Form: antd.Form,
    Input: antd.Input,
    Select: antd.Select,
    Radio: antd.Radio,
    Modal: Object.assign(modalLike, {
      confirm: confirmSpy,
      info: vi.fn(),
      warning: vi.fn(),
      error: vi.fn(),
    }),
  };
});

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: messageMocks }),
}));

import { ProviderConfigModal } from "./ProviderConfigModal";
import { renderWithProviders } from "@/test/common_setup";

function makeProvider(overrides: Record<string, unknown> = {}) {
  return {
    id: "custom-provider",
    name: "My Provider",
    api_key: "",
    api_key_prefix: "",
    base_url: "https://api.example.com/v1",
    is_custom: true,
    freeze_url: false,
    chat_model: "OpenAIChatModel",
    support_connection_check: true,
    generate_kwargs: {},
    ...overrides,
  };
}

function renderModal(
  provider = makeProvider(),
  activeModels: unknown = null,
  onSaved = vi.fn().mockResolvedValue(undefined),
) {
  const onClose = vi.fn();
  const rendered = renderWithProviders(
    <ProviderConfigModal
      provider={provider as never}
      activeModels={activeModels}
      open
      onClose={onClose}
      onSaved={onSaved}
    />,
  );
  return { onClose, onSaved, unmount: rendered.unmount };
}

/** Dirty the form by typing an api key so the save button enables. */
async function dirtyForm(user: ReturnType<typeof userEvent.setup>) {
  const keyInput = screen.getByPlaceholderText("models.enterApiKeyOptional");
  await user.type(keyInput, "sk-x");
}

describe("ProviderConfigModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.testProviderConnection.mockResolvedValue({ success: true });
    apiMocks.configureProvider.mockResolvedValue({});
  });

  describe("render and hints", () => {
    it("renders custom provider name and protocol fields", () => {
      renderModal();
      expect(
        screen.getAllByText("models.providerNameLabel").length,
      ).toBeGreaterThan(0);
      expect(screen.getByText("models.protocol")).toBeInTheDocument();
    });

    it("shows the leave-blank hint when an api key already exists", () => {
      renderModal(makeProvider({ api_key: "sk-existing" }));
      expect(
        screen.getByPlaceholderText("models.leaveBlankKeep"),
      ).toBeInTheDocument();
    });

    it("shows the prefix hint for providers with key prefixes", () => {
      renderModal(makeProvider({ api_key_prefix: "sk-" }));
      expect(
        screen.getByPlaceholderText("models.enterApiKey"),
      ).toBeInTheDocument();
    });

    it("shows optional key hint when no prefix rules exist", () => {
      renderModal();
      expect(
        screen.getByPlaceholderText("models.enterApiKeyOptional"),
      ).toBeInTheDocument();
    });

    it("shows revoke and test buttons only with a key and connection check", () => {
      renderModal(makeProvider({ api_key: "sk-abc" }));
      expect(
        screen.getAllByText("models.revokeAuthorization").length,
      ).toBeGreaterThan(0);
      expect(screen.getByText("models.testConnection")).toBeInTheDocument();
    });

    it("hides revoke button when no api key is configured", () => {
      renderModal();
      expect(
        screen.queryByText("models.revokeAuthorization"),
      ).not.toBeInTheDocument();
    });

    it("shows provider-specific base url hints", () => {
      const cases: Array<[string, string]> = [
        ["azure-openai", "models.azureEndpointHint"],
        ["anthropic", "models.anthropicEndpointHint"],
        ["openai", "models.openAIEndpoint"],
        ["opencode", "models.openAICompatibleEndpoint"],
        ["ollama", "models.ollamaEndpointHint"],
        ["lmstudio", "models.lmstudioEndpointHint"],
      ];
      for (const [id, hint] of cases) {
        const { unmount } = renderModal(makeProvider({ id, is_custom: false }));
        expect(screen.getByText(hint)).toBeInTheDocument();
        unmount();
      }
    });

    it("falls back to the generic endpoint hint for unknown providers", () => {
      renderModal(makeProvider({ id: "unknown-builtin", is_custom: false }));
      expect(screen.getByText("models.apiEndpointHint")).toBeInTheDocument();
    });

    it("uses the anthropic hint for custom providers with anthropic protocol", () => {
      renderModal(makeProvider({ chat_model: "AnthropicChatModel" }));
      expect(
        screen.getByText("models.anthropicEndpointHint"),
      ).toBeInTheDocument();
    });

    it("disables base url editing for frozen-url providers", () => {
      renderModal(makeProvider({ freeze_url: true }));
      const input = screen.getByDisplayValue("https://api.example.com/v1");
      expect(input).toBeDisabled();
    });
  });

  describe("base url options select", () => {
    it("renders a select with meta base_url_options and the select hint", () => {
      renderModal(
        makeProvider({
          is_custom: false,
          meta: {
            base_url_options: [
              { label: "Primary", value: "https://p.example" },
              { label: "Backup", value: "https://b.example" },
            ],
          },
        }),
      );
      expect(screen.getByText("models.selectBaseURLHint")).toBeInTheDocument();
      expect(screen.getByRole("combobox")).toBeInTheDocument();
    });

    it("ignores malformed base_url_options entries without crashing", () => {
      renderModal(
        makeProvider({
          is_custom: false,
          meta: {
            base_url_options: [
              { label: "Good", value: "https://g.example" },
              { label: 123, value: "bad" },
              null,
              "not-an-object",
            ],
          },
        }),
      );
      expect(screen.getByRole("combobox")).toBeInTheDocument();
    });
  });

  describe("save flow", () => {
    it("saves after a successful connection check", async () => {
      const user = userEvent.setup();
      const { onSaved } = renderModal();

      await dirtyForm(user);
      await user.click(screen.getByText("models.save"));

      await waitFor(() =>
        expect(apiMocks.configureProvider).toHaveBeenCalled(),
      );
      expect(apiMocks.testProviderConnection).toHaveBeenCalledWith(
        "custom-provider",
        expect.objectContaining({ api_key: "sk-x" }),
      );
      expect(apiMocks.configureProvider).toHaveBeenCalledWith(
        "custom-provider",
        expect.objectContaining({
          api_key: "sk-x",
          generate_kwargs: {},
          custom_headers: {},
        }),
      );
      expect(onSaved).toHaveBeenCalled();
      expect(messageMocks.success).toHaveBeenCalled();
    });

    it("skips the connection check when unsupported", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ support_connection_check: false }));

      await dirtyForm(user);
      await user.click(screen.getByText("models.save"));

      await waitFor(() =>
        expect(apiMocks.configureProvider).toHaveBeenCalled(),
      );
      expect(apiMocks.testProviderConnection).not.toHaveBeenCalled();
    });

    it("aborts saving when the connection check fails", async () => {
      apiMocks.testProviderConnection.mockResolvedValue({
        success: false,
        message: "bad key",
      });
      const user = userEvent.setup();
      renderModal();

      await dirtyForm(user);
      await user.click(screen.getByText("models.save"));

      await waitFor(() =>
        expect(apiMocks.testProviderConnection).toHaveBeenCalled(),
      );
      expect(apiMocks.configureProvider).not.toHaveBeenCalled();
      expect(messageMocks.error).toHaveBeenCalled();
    });

    it("sends parsed generate config in the payload", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ support_connection_check: false }));

      const textarea = document.querySelector("textarea")!;
      fireEvent.change(textarea, {
        target: { value: '{"temperature": 0.7}' },
      });

      await user.click(screen.getByText("models.save"));

      await waitFor(() =>
        expect(apiMocks.configureProvider).toHaveBeenCalledWith(
          "custom-provider",
          expect.objectContaining({
            generate_kwargs: { temperature: 0.7 },
          }),
        ),
      );
    });

    it("blocks saving on invalid JSON in generate config", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ support_connection_check: false }));

      const textarea = document.querySelector("textarea")!;
      fireEvent.change(textarea, { target: { value: "{ not json" } });

      await user.click(screen.getByText("models.save"));

      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(apiMocks.configureProvider).not.toHaveBeenCalled();
    });

    it("blocks saving when generate config is not an object", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ support_connection_check: false }));

      const textarea = document.querySelector("textarea")!;
      fireEvent.change(textarea, { target: { value: "[1, 2]" } });

      await user.click(screen.getByText("models.save"));

      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(apiMocks.configureProvider).not.toHaveBeenCalled();
    });

    it("blocks saving when the base url is cleared (required rule)", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ support_connection_check: false }));

      const baseInput = screen.getByDisplayValue("https://api.example.com/v1");
      await user.clear(baseInput);
      await user.click(screen.getByText("models.save"));

      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(apiMocks.configureProvider).not.toHaveBeenCalled();
      // Form validation failures are swallowed silently (no error toast)
      expect(messageMocks.error).not.toHaveBeenCalled();
    });

    it("rejects an invalid base url protocol", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ support_connection_check: false }));

      const baseInput = screen.getByDisplayValue("https://api.example.com/v1");
      await user.clear(baseInput);
      await user.type(baseInput, "ftp://nope.example");
      await user.click(screen.getByText("models.save"));

      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(apiMocks.configureProvider).not.toHaveBeenCalled();
    });

    it("rejects api keys with the wrong prefix", async () => {
      const user = userEvent.setup();
      renderModal(
        makeProvider({
          api_key_prefix: "sk-",
          support_connection_check: false,
        }),
      );

      const keyInput = screen.getByPlaceholderText("models.enterApiKey");
      await user.type(keyInput, "wrong-prefix-key");
      await user.click(screen.getByText("models.save"));

      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(apiMocks.configureProvider).not.toHaveBeenCalled();
    });

    it("surfaces unexpected save errors", async () => {
      apiMocks.configureProvider.mockRejectedValue(new Error("boom"));
      const user = userEvent.setup();
      renderModal(makeProvider({ support_connection_check: false }));

      await dirtyForm(user);
      await user.click(screen.getByText("models.save"));

      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("boom"),
      );
    });
  });

  describe("test connection button", () => {
    it("reports success", async () => {
      const user = userEvent.setup();
      renderModal();

      await user.click(screen.getByText("models.testConnection"));

      await waitFor(() => expect(messageMocks.success).toHaveBeenCalled());
    });

    it("reports failure as a warning", async () => {
      apiMocks.testProviderConnection.mockResolvedValue({
        success: false,
        message: "denied",
      });
      const user = userEvent.setup();
      renderModal();

      await user.click(screen.getByText("models.testConnection"));

      await waitFor(() => expect(messageMocks.warning).toHaveBeenCalled());
    });

    it("reports unexpected errors", async () => {
      apiMocks.testProviderConnection.mockRejectedValue(new Error("net down"));
      const user = userEvent.setup();
      renderModal();

      await user.click(screen.getByText("models.testConnection"));

      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("net down"),
      );
    });
  });

  describe("revoke authorization", () => {
    async function openConfirm(user: ReturnType<typeof userEvent.setup>) {
      await user.click(screen.getAllByText("models.revokeAuthorization")[0]);
      await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
      const opts = confirmSpy.mock.calls[
        confirmSpy.mock.calls.length - 1
      ]?.[0] as {
        onOk: () => Promise<void>;
      };
      await opts.onOk();
    }

    it("revokes through the confirm dialog (active llm provider)", async () => {
      const user = userEvent.setup();
      const { onSaved } = renderModal(makeProvider({ api_key: "sk-live" }), {
        active_llm: { provider_id: "custom-provider" },
      });

      await openConfirm(user);

      expect(apiMocks.configureProvider).toHaveBeenCalledWith(
        "custom-provider",
        { api_key: "" },
      );
      expect(onSaved).toHaveBeenCalled();
      expect(messageMocks.success).toHaveBeenCalledWith(
        "models.authorizationRevoked",
      );
    });

    it("uses the simple message for non-active providers", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ api_key: "sk-live" }), {
        active_llm: { provider_id: "another" },
      });

      await openConfirm(user);

      expect(messageMocks.success).toHaveBeenCalledWith(
        "models.authorizationRevokedSimple",
      );
    });

    it("reports revoke failures", async () => {
      apiMocks.configureProvider.mockRejectedValue(new Error("cannot revoke"));
      const user = userEvent.setup();
      renderModal(makeProvider({ api_key: "sk-live" }));

      await openConfirm(user);

      expect(messageMocks.error).toHaveBeenCalledWith("cannot revoke");
    });

    it("uses the active-llm confirm content variant", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ api_key: "sk-live" }), {
        active_llm: { provider_id: "custom-provider" },
      });

      await user.click(screen.getAllByText("models.revokeAuthorization")[0]);
      await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
      const opts = confirmSpy.mock.calls[
        confirmSpy.mock.calls.length - 1
      ]?.[0] as { content: string };
      expect(opts.content).toBe("models.revokeConfirmContent");
    });
  });

  describe("advanced config", () => {
    async function openAdvanced(user: ReturnType<typeof userEvent.setup>) {
      await user.click(screen.getByText("models.advancedConfig"));
      await waitFor(() =>
        expect(screen.getByText("models.customHeaders")).toBeInTheDocument(),
      );
    }

    it("adds, edits and removes custom header rows", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ custom_headers: { "X-One": "1" } }));
      await openAdvanced(user);

      expect(screen.getByDisplayValue("X-One")).toBeInTheDocument();

      await user.click(screen.getByText("models.addHeader"));
      const emptyInputs = screen.getAllByDisplayValue("");
      await user.type(emptyInputs[emptyInputs.length - 2], "X-Two");
      await user.type(emptyInputs[emptyInputs.length - 1], "2");
      expect(screen.getByDisplayValue("X-Two")).toBeInTheDocument();

      const deleteIcons = document.querySelectorAll(
        "[class*='customHeaderDelete']",
      );
      fireEvent.click(deleteIcons[0]);
      expect(screen.queryByDisplayValue("X-One")).not.toBeInTheDocument();
    });

    it("sends configured headers in the save payload", async () => {
      const user = userEvent.setup();
      renderModal(
        makeProvider({
          custom_headers: { "X-Keep": "v" },
          support_connection_check: false,
        }),
      );

      await dirtyForm(user);
      await user.click(screen.getByText("models.save"));

      await waitFor(() =>
        expect(apiMocks.configureProvider).toHaveBeenCalledWith(
          "custom-provider",
          expect.objectContaining({ custom_headers: { "X-Keep": "v" } }),
        ),
      );
    });

    it("switches anthropic auth mode and sends it in the payload", async () => {
      const user = userEvent.setup();
      renderModal(
        makeProvider({
          id: "anthropic",
          is_custom: false,
          support_connection_check: false,
        }),
      );

      await user.click(screen.getByText("models.advancedConfig"));
      await waitFor(() =>
        expect(screen.getByText("models.authMode")).toBeInTheDocument(),
      );

      await user.click(screen.getByText("models.authModeAuthToken"));

      const keyInput = screen.getByPlaceholderText(
        "models.enterApiKeyOptional",
      );
      await user.type(keyInput, "token-x");
      await user.click(screen.getByText("models.save"));

      await waitFor(() =>
        expect(apiMocks.configureProvider).toHaveBeenCalledWith(
          "anthropic",
          expect.objectContaining({ auth_mode: "auth_token" }),
        ),
      );
    });

    it("labels the key field as auth token in auth_token mode", () => {
      renderModal(
        makeProvider({
          id: "anthropic",
          is_custom: false,
          auth_mode: "auth_token",
        }),
      );
      expect(
        screen.getAllByText("models.authModeAuthToken").length,
      ).toBeGreaterThanOrEqual(1);
    });

    it("omits auth_mode for non-anthropic providers", async () => {
      const user = userEvent.setup();
      renderModal(makeProvider({ support_connection_check: false }));

      await dirtyForm(user);
      await user.click(screen.getByText("models.save"));

      await waitFor(() =>
        expect(apiMocks.configureProvider).toHaveBeenCalledWith(
          "custom-provider",
          expect.objectContaining({ auth_mode: undefined }),
        ),
      );
    });
  });

  describe("JsonCodeEditor", () => {
    function getTextarea(): HTMLTextAreaElement {
      return document.querySelector(
        "[class*='jsonEditorTextarea']",
      ) as HTMLTextAreaElement;
    }

    it("renders highlighted tokens for prefilled JSON", async () => {
      renderModal(
        makeProvider({
          generate_kwargs: { flag: true, nothing: null, count: 3.5 },
        }),
      );

      await waitFor(() => {
        const container = document.querySelector(
          "[class*='jsonEditorHighlight']",
        );
        expect(container).not.toBeNull();
      });

      const html = document.querySelector(
        "[class*='jsonEditorHighlight']",
      )!.innerHTML;
      expect(html).toContain("jsonEditorTokenKey");
      expect(html).toContain("jsonEditorTokenBoolean");
      expect(html).toContain("jsonEditorTokenNull");
      expect(html).toContain("jsonEditorTokenNumber");
      expect(html).toContain("jsonEditorTokenPunctuation");
    });

    it("shows the placeholder in the highlight layer when empty", () => {
      renderModal();
      fireEvent.click(screen.getByText("models.advancedConfig"));
      const highlight = document.querySelector(
        "[class*='jsonEditorHighlight']",
      );
      expect(highlight?.textContent).toContain("Example:");
    });

    it("inserts indentation on Tab", async () => {
      vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
        cb(0);
        return 0;
      });
      renderModal();
      fireEvent.click(screen.getByText("models.advancedConfig"));

      const textarea = getTextarea();
      fireEvent.change(textarea, { target: { value: "line one" } });
      textarea.selectionStart = 8;
      textarea.selectionEnd = 8;
      fireEvent.keyDown(textarea, { key: "Tab" });

      expect(textarea.value).toBe("line one  ");
      vi.mocked(window.requestAnimationFrame).mockRestore();
    });

    it("outdents on Shift+Tab when the cursor sits after the indent", async () => {
      vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
        cb(0);
        return 0;
      });
      renderModal();
      fireEvent.click(screen.getByText("models.advancedConfig"));

      const textarea = getTextarea();
      fireEvent.change(textarea, { target: { value: "  indented" } });
      textarea.selectionStart = 2;
      textarea.selectionEnd = 2;
      fireEvent.keyDown(textarea, { key: "Tab", shiftKey: true });

      expect(textarea.value).toBe("indented");
      vi.mocked(window.requestAnimationFrame).mockRestore();
    });

    it("keeps flush lines unchanged on Shift+Tab", async () => {
      vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
        cb(0);
        return 0;
      });
      renderModal();
      fireEvent.click(screen.getByText("models.advancedConfig"));

      const textarea = getTextarea();
      fireEvent.change(textarea, { target: { value: "flush" } });
      textarea.selectionStart = 5;
      textarea.selectionEnd = 5;
      fireEvent.keyDown(textarea, { key: "Tab", shiftKey: true });

      expect(textarea.value).toBe("flush");
      vi.mocked(window.requestAnimationFrame).mockRestore();
    });

    it("indents and outdents multi-line selections", async () => {
      vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
        cb(0);
        return 0;
      });
      renderModal();
      fireEvent.click(screen.getByText("models.advancedConfig"));

      const textarea = getTextarea();
      fireEvent.change(textarea, { target: { value: "a\nb" } });
      textarea.selectionStart = 1;
      textarea.selectionEnd = 3;
      fireEvent.keyDown(textarea, { key: "Tab" });
      expect(textarea.value).toBe("  a\n  b");

      textarea.selectionStart = 3;
      textarea.selectionEnd = 7;
      fireEvent.keyDown(textarea, { key: "Tab", shiftKey: true });
      expect(textarea.value).toBe("a\nb");
      vi.mocked(window.requestAnimationFrame).mockRestore();
    });

    it("syncs highlight scroll with the textarea", () => {
      renderModal();
      fireEvent.click(screen.getByText("models.advancedConfig"));

      const textarea = getTextarea();
      const highlight = document.querySelector(
        "[class*='jsonEditorHighlight']",
      ) as HTMLDivElement;

      Object.defineProperty(textarea, "scrollTop", {
        value: 42,
        configurable: true,
      });
      fireEvent.scroll(textarea);
      expect(highlight.scrollTop).toBe(42);
    });

    it("ignores non-Tab keys in the editor", () => {
      renderModal();
      fireEvent.click(screen.getByText("models.advancedConfig"));

      const textarea = getTextarea();
      fireEvent.change(textarea, { target: { value: "abc" } });
      fireEvent.keyDown(textarea, { key: "a" });
      expect(textarea.value).toBe("abc");
    });
  });
});
