import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ModelConfigModal from "../ModelConfigModal";
import { installMockFetch } from "@/test/mockFetch";

const emptyConfig = {
  llm: {
    enabled: true,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    multimodal: false,
  },
  vlm: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    use_llm: false,
    multimodal: false,
  },
  image: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
  },
  video: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "Volcano Engine（火山引擎）",
    custom_protocol: "",
  },
  oss: {
    enabled: false,
    access_key_id: "",
    access_key_secret: "",
    endpoint: "",
    bucket: "",
    public_base_url: "",
    policy_api_key: "",
  },
  executionAuthorization: { mode: "required" as const },
};

describe("ModelConfigModal configuration lifecycle", () => {
  it("stays unconfigured until the user tests and saves entered model data", async () => {
    const onClose = vi.fn();
    const { calls } = installMockFetch([
      {
        match: "/models/config/llm",
        method: "PATCH",
        response: { json: { ok: true } },
      },
      {
        match: "/models/config",
        method: "GET",
        response: { json: emptyConfig },
      },
      {
        match: "/models/test",
        method: "POST",
        response: { json: { ok: true, ms: 8 } },
      },
    ]);
    render(<ModelConfigModal open onClose={onClose} />);

    await waitFor(() => expect(screen.getAllByText("未配置")).toHaveLength(4));
    const keyInput = screen.getByPlaceholderText("sk-...");
    expect(keyInput).toHaveAttribute("type", "password");
    expect(
      screen.queryByRole("button", { name: "显示" }),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("model"), {
      target: { value: "saved-model" },
    });
    fireEvent.change(keyInput, { target: { value: "saved-secret" } });
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com"), {
      target: { value: "https://provider.test/v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /测试连通性/ }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/models/test"))).toBe(
        true,
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));
    // Sectioned save only PATCHes the section of the current tab and closes the
    // modal automatically on success.
    await waitFor(() => {
      const save = calls.find(
        (call) =>
          call.method === "PATCH" && call.url.endsWith("/models/config/llm"),
      );
      expect(save?.body).toMatchObject({
        model_name: "saved-model",
        api_key: "saved-secret",
        base_url: "https://provider.test/v1",
      });
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });
});
