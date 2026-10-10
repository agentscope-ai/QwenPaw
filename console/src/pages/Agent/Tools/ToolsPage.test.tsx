import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({
  plugin: false,
  toggleEnabled: vi.fn(),
  enableAll: vi.fn(),
  disableAll: vi.fn(),
}));
vi.mock("react-i18next", async () => {
  const { createInstance } = await import("i18next");
  const en = await import("../../../locales/en.json");
  const zh = await import("../../../locales/zh.json");
  const i18n = createInstance();
  await i18n.init({
    lng: "en",
    fallbackLng: "en",
    resources: {
      en: { translation: en.default },
      zh: { translation: zh.default },
    },
  });
  return { useTranslation: () => ({ t: i18n.t.bind(i18n), i18n }) };
});
vi.mock("./useTools", () => ({
  useTools: () => ({
    tools: state.plugin
      ? [
          {
            name: "read_file",
            description: "Plugin original text",
            enabled: true,
            source_plugin_id: "example",
          },
        ]
      : [
          {
            name: "read_file",
            description: "Read file contents",
            enabled: true,
          },
          { name: "append_file", description: "Append text", enabled: false },
        ],
    loading: false,
    batchLoading: false,
    ...state,
    toggleAsyncExecution: vi.fn(),
    loadTools: vi.fn(),
    saveToolConfig: vi.fn(),
  }),
}));
import ToolsPage from "./index";
import { useTranslation } from "react-i18next";
beforeEach(async () => {
  vi.clearAllMocks();
  state.plugin = false;
  await useTranslation().i18n.changeLanguage("en");
});
describe("ToolsPage", () => {
  it("keeps plugin names and descriptions untranslated in Chinese", async () => {
    state.plugin = true;
    await useTranslation().i18n.changeLanguage("zh");
    render(<ToolsPage />);
    expect(
      screen.getByRole("heading", { name: "read_file" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Plugin original text")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "未分类" })).toBeInTheDocument();
    expect(screen.queryByText("读取文件")).not.toBeInTheDocument();
  });
  it("shows translated names and purposes and searches Chinese text", async () => {
    await useTranslation().i18n.changeLanguage("zh");
    render(<ToolsPage />);
    expect(
      screen.getByRole("heading", { name: "读取文件" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText("读取文本文件，查看内容或指定行。"),
      ).toBeVisible(),
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "追加" },
    });
    expect(
      screen.getByRole("heading", { name: "追加内容" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "读取文件" }),
    ).not.toBeInTheDocument();
  });
  it("hides empty groups and filters with trimmed case-insensitive input", () => {
    render(<ToolsPage />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "missing tool" },
    });
    expect(screen.getByRole("status")).toHaveTextContent("No matching tools");
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  APPEND  " },
    });
    expect(
      screen.getByRole("region", { name: "Files & code" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Read files" }),
    ).not.toBeInTheDocument();
  });
  it("exposes an accessible switch for a disabled tool", () => {
    render(<ToolsPage />);
    fireEvent.click(
      screen.getByRole("switch", { name: "Enable Append to files" }),
    );
    expect(state.toggleEnabled).toHaveBeenCalledWith(
      expect.objectContaining({ name: "append_file", enabled: false }),
    );
  });
});
