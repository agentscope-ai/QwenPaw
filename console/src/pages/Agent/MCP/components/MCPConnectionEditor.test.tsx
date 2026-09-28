import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
