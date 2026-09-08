// @vitest-environment jsdom
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Modal } from "antd";
import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";
import { OfficialPluginList } from "./OfficialPluginList";

const hoisted = vi.hoisted(() => ({
  plugins: [] as OfficialPluginCatalogEntry[],
  handleInstall: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/hooks/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("../hooks/useOfficialPlugins", () => ({
  useOfficialPlugins: () => ({
    loading: false,
    catalogError: null,
    plugins: hoisted.plugins,
    installingId: null,
    loadCatalog: vi.fn(),
    handleInstall: hoisted.handleInstall,
  }),
}));

function makeEntry(
  version: string,
  overrides: Partial<OfficialPluginCatalogEntry> = {},
): OfficialPluginCatalogEntry {
  return {
    id: `creator-${version}`,
    plugin_id: "creator",
    name: "Creator",
    description: `Description ${version}`,
    version,
    author: "AgentScope",
    kind: "tool",
    size: `${version} MB`,
    sha256: "sha",
    install_url: `https://example.com/creator-${version}.zip`,
    installed: false,
    upgrade_available: false,
    ...overrides,
  };
}

function selectVersion(article: HTMLElement, version: string) {
  fireEvent.mouseDown(
    within(article).getByRole("combobox", {
      name: "pluginManager.catalogVersion",
    }),
  );
  fireEvent.click(screen.getByText(`v${version}`));
}

describe("OfficialPluginList", () => {
  beforeEach(() => {
    hoisted.plugins.length = 0;
    hoisted.handleInstall.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders one card per plugin and defaults to its newest version", () => {
    hoisted.plugins.push(
      makeEntry("1.0.1"),
      makeEntry("1.1.1"),
      makeEntry("1.0.3"),
    );

    render(<OfficialPluginList onInstalled={vi.fn()} />);

    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(
      within(screen.getByRole("article", { name: "Creator" })).getByText(
        "v1.1.1",
      ),
    ).toBeInTheDocument();
  });

  it("installs the version selected from the shared plugin card", () => {
    const oldVersion = makeEntry("1.0.1");
    hoisted.plugins.push(oldVersion, makeEntry("1.1.1"));

    render(<OfficialPluginList onInstalled={vi.fn()} />);
    const article = screen.getByRole("article", { name: "Creator" });
    selectVersion(article, "1.0.1");
    fireEvent.click(
      within(article).getByRole("button", {
        name: /pluginManager.catalogInstall/,
      }),
    );

    expect(hoisted.handleInstall).toHaveBeenCalledWith(oldVersion);
  });

  it("keeps the selected version when switching to list view", () => {
    const oldVersion = makeEntry("1.0.1");
    hoisted.plugins.push(oldVersion, makeEntry("1.1.1"));

    render(<OfficialPluginList onInstalled={vi.fn()} />);
    selectVersion(screen.getByRole("article", { name: "Creator" }), "1.0.1");
    fireEvent.click(screen.getByLabelText("skills.listView"));
    fireEvent.click(
      screen.getByRole("button", {
        name: /pluginManager.catalogInstall/,
      }),
    );

    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(hoisted.handleInstall).toHaveBeenCalledWith(oldVersion);
  });

  it("marks the installed version and confirms a downgrade", async () => {
    const downgradeVersion = makeEntry("1.0.0", {
      installed: true,
      installed_version: "1.1.0",
    });
    hoisted.plugins.push(
      downgradeVersion,
      makeEntry("1.2.0", {
        installed: true,
        installed_version: "1.1.0",
      }),
      makeEntry("1.1.0", {
        installed: true,
        installed_version: "1.1.0",
      }),
    );
    const confirm = vi.spyOn(Modal, "confirm").mockReturnValue({
      destroy: vi.fn(),
      update: vi.fn(),
    });

    render(<OfficialPluginList onInstalled={vi.fn()} />);
    const article = screen.getByRole("article", { name: "Creator" });
    fireEvent.mouseDown(within(article).getByRole("combobox"));
    expect(
      screen.getByText("v1.1.0 · pluginManager.catalogInstalledVersion"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("v1.0.0"));
    fireEvent.click(
      within(article).getByRole("button", {
        name: /pluginManager.catalogDowngrade/,
      }),
    );

    expect(confirm).toHaveBeenCalledTimes(1);
    const options = confirm.mock.calls[0][0] as {
      okType: string;
      onOk: () => Promise<void>;
    };
    expect(options.okType).toBe("danger");
    await act(async () => {
      await options.onOk();
    });
    expect(hoisted.handleInstall).toHaveBeenCalledWith(downgradeVersion);
  });

  it("shows reinstall when the installed version is selected", () => {
    hoisted.plugins.push(
      makeEntry("1.2.0", {
        installed: true,
        installed_version: "1.1.0",
      }),
      makeEntry("1.1.0", {
        installed: true,
        installed_version: "1.1.0",
      }),
    );

    render(<OfficialPluginList onInstalled={vi.fn()} />);
    const article = screen.getByRole("article", { name: "Creator" });
    fireEvent.mouseDown(within(article).getByRole("combobox"));
    fireEvent.click(
      screen.getByText("v1.1.0 · pluginManager.catalogInstalledVersion"),
    );

    expect(
      within(article).getByRole("button", {
        name: /pluginManager.catalogReinstall/,
      }),
    ).toBeInTheDocument();
  });
});
