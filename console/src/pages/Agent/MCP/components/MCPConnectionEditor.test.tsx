import { useRef } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";
import { settingsSearchTarget } from "@/pages/SettingsCenter/settingsSearch";
import { useSettingsSearchTarget } from "@/pages/SettingsCenter/useSettingsSearchTarget";
import { MCPConnectionEditor } from "./MCPConnectionEditor";
import { readConnection, connectionError } from "./connectionValue";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const config = {
  key: "test",
  name: "Local tools",
  transport: "stdio",
  command: "node",
  args: ["/path with spaces/server.js"],
  env: { TOKEN: "********" },
  enabled: false,
};
describe("MCP connection editor", () => {
  afterEach(() => vi.restoreAllMocks());

  it("locates arguments without matching the help text or changing the connection", async () => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      {},
    ] as unknown as DOMRectList);
    const onChange = vi.fn();
    const target = settingsSearchTarget(
      "mcp",
      "acp.args",
      ((key: string) => key) as TFunction,
    );
    function Fixture() {
      const root = useRef<HTMLDivElement>(null);
      useSettingsSearchTarget(root, target, "mcp");
      return (
        <div ref={root}>
          <MCPConnectionEditor
            value={JSON.stringify(config)}
            onChange={onChange}
          />
        </div>
      );
    }
    render(<Fixture />);
    const args = screen.getByLabelText("acp.args · acp.argsHelp");
    await waitFor(() =>
      expect(args.closest("[data-settings-target]")).toHaveAttribute(
        "data-search-highlight",
        "true",
      ),
    );
    expect(args).toHaveValue(config.args[0]);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("opens editable essentials directly and preserves advanced values", () => {
    const onChange = vi.fn();
    render(
      <MCPConnectionEditor
        value={JSON.stringify(config)}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("mcp.form.name"), {
      target: { value: "Renamed" },
    });
    expect(JSON.parse(onChange.mock.lastCall![0])).toEqual({
      ...config,
      name: "Renamed",
    });
  });
  it("keeps a path containing spaces as one argument and permits multiline typing", () => {
    const onChange = vi.fn();
    render(
      <MCPConnectionEditor
        value={JSON.stringify(config)}
        onChange={onChange}
      />,
    );
    const args = screen.getByLabelText("acp.args · acp.argsHelp");
    fireEvent.change(args, {
      target: { value: "/path with spaces/server.js\n--read-only\n" },
    });
    expect(JSON.parse(onChange.mock.lastCall![0]).args).toEqual([
      "/path with spaces/server.js",
      "--read-only",
    ]);
    expect((args as HTMLTextAreaElement).value.endsWith("\n")).toBe(true);
  });
  it("validates incomplete connections before autosave", () => {
    expect(connectionError(readConnection("{"))).toBe(
      "skills.configInvalidJson",
    );
    expect(connectionError({ ...config, command: " " })).toBe(
      "mcp.form.commandRequired",
    );
    expect(connectionError({ ...config, transport: "sse", url: "" })).toBe(
      "mcp.form.urlRequired",
    );
    expect(connectionError(config)).toBeNull();
  });
});
