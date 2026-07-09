import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreatorDiscoveryList } from "./CreatorDiscoveryList";
import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";

function makeEntry(
  id: string,
  name: string,
  kind: string,
): OfficialPluginCatalogEntry {
  return {
    id,
    plugin_id: id,
    name,
    description: `${name} description`,
    version: "1.0.0",
    author: "",
    kind,
    size: "",
    sha256: "",
    install_url: `https://example.com/${id}.zip`,
    installed: false,
    upgrade_available: false,
  };
}

describe("CreatorDiscoveryList", () => {
  it("renders one card per app", () => {
    render(
      <CreatorDiscoveryList
        apps={[makeEntry("a", "Alpha", "app"), makeEntry("b", "Beta", "app")]}
        installingId={null}
        onInstall={vi.fn()}
      />,
    );
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("calls onInstall with the selected entry", async () => {
    const onInstall = vi.fn();
    render(
      <CreatorDiscoveryList
        apps={[makeEntry("a", "Alpha", "app")]}
        installingId={null}
        onInstall={onInstall}
      />,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onInstall).toHaveBeenCalledTimes(1);
    expect(onInstall).toHaveBeenCalledWith(
      expect.objectContaining({ id: "a" }),
    );
  });

  it("disables other buttons while one is installing", () => {
    render(
      <CreatorDiscoveryList
        apps={[makeEntry("a", "Alpha", "app"), makeEntry("b", "Beta", "app")]}
        installingId="a"
        onInstall={vi.fn()}
      />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons[0].className).toContain("ant-btn-loading");
    expect(buttons[1]).toBeDisabled();
  });
});
