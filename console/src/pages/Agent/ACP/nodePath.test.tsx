import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { beforeEach, expect, it, vi } from "vitest";
import i18n from "../../../i18n";
import api from "../../../api";
import ACPPage from "./index";

vi.mock("@agentscope-ai/design", async () => {
  const antd = await import("antd");
  return {
    Button: antd.Button,
    Form: antd.Form,
    Input: antd.Input,
    Modal: antd.Modal,
    Select: antd.Select,
  };
});
vi.mock("../../../api", () => ({
  default: {
    getACPConfig: vi.fn(),
    getACPNodeRuntime: vi.fn(),
    updateACPNodeRuntime: vi.fn(),
  },
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "default" }),
}));
vi.mock("../../../utils/openExternalLink", () => ({
  isDesktopTauriRuntime: () => false,
}));
vi.mock("./components/ACPCard", () => ({ ACPCard: () => null }));
vi.mock("./components/ACPDrawer", () => ({
  ACPDrawer: () => null,
  parseArgsText: () => [],
  parseEnvText: () => ({}),
  stringifyArgs: () => "",
  stringifyEnv: () => "",
}));

beforeEach(async () => {
  await i18n.changeLanguage("zh");
  vi.clearAllMocks();
  vi.mocked(api.getACPConfig).mockResolvedValue({ agents: {} });
  vi.mocked(api.getACPNodeRuntime).mockResolvedValue({
    node_path: "",
    effective_node_path: "/usr/bin/node",
    candidates: [],
  });
  vi.mocked(api.updateACPNodeRuntime).mockResolvedValue({
    node_path: "/opt/node",
    effective_node_path: "/opt/node",
    candidates: [],
  });
});

async function openPathInput() {
  render(
    <ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}>
      <App>
        <ACPPage />
      </App>
    </ConfigProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: i18n.t("acp.nodeSettings") }),
  );
  await waitFor(() => expect(api.getACPNodeRuntime).toHaveBeenCalled());
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByText(i18n.t("acp.chooseOtherNode")));
  return screen.findByRole("textbox", { name: "请输入 node 可执行文件路径" });
}

it("uses a Chinese application dialog and cancels without saving the Node path", async () => {
  const prompt = vi.spyOn(window, "prompt");
  const input = await openPathInput();
  expect(input).toHaveValue("/usr/bin/node");
  expect(
    screen.getByRole("button", { name: /确\s*[认定]/ }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /取\s*消/ }));
  await waitFor(() =>
    expect(
      screen.queryByRole("textbox", { name: "请输入 node 可执行文件路径" }),
    ).toBeNull(),
  );
  expect(api.updateACPNodeRuntime).not.toHaveBeenCalled();
  expect(prompt).not.toHaveBeenCalled();
  prompt.mockRestore();
});

it("keeps empty input open and saves only a confirmed nonblank path", async () => {
  const input = await openPathInput();
  fireEvent.change(input, { target: { value: "   " } });
  fireEvent.click(screen.getByRole("button", { name: /确\s*[认定]/ }));
  expect(api.updateACPNodeRuntime).not.toHaveBeenCalled();
  await waitFor(() => expect(
    screen.getByRole("textbox", { name: "请输入 node 可执行文件路径" }),
  ).toBeVisible());
  fireEvent.change(input, { target: { value: "  /opt/node  " } });
  fireEvent.click(screen.getByRole("button", { name: /确\s*[认定]/ }));
  await waitFor(() =>
    expect(api.updateACPNodeRuntime).toHaveBeenCalledWith({
      node_path: "/opt/node",
    }),
  );
});
