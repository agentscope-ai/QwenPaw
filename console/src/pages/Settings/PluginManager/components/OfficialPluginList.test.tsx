// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

  it("shows the version selector for an uninstalled single version", () => {
    hoisted.plugins.push(makeEntry("1.0.0"));

    render(<OfficialPluginList onInstalled={vi.fn()} />);
    const article = screen.getByRole("article", { name: "Creator" });

    expect(within(article).getByRole("combobox")).toBeInTheDocument();
    expect(within(article).getByText("v1.0.0")).toBeInTheDocument();
    expect(
      within(article).getByRole("button", {
        name: /pluginManager.catalogInstall/,
      }),
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

  it("only shows update when the installed version is outdated", () => {
    const oldVersion = makeEntry("1.0.0", {
      installed: true,
      installed_version: "1.1.0",
    });
    const latestVersion = makeEntry("1.2.0", {
      installed: true,
      installed_version: "1.1.0",
    });
    hoisted.plugins.push(
      oldVersion,
      latestVersion,
      makeEntry("1.1.0", {
        installed: true,
        installed_version: "1.1.0",
      }),
    );
    render(<OfficialPluginList onInstalled={vi.fn()} />);
    const article = screen.getByRole("article", { name: "Creator" });

    expect(within(article).queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(
      within(article).getByRole("button", {
        name: /pluginManager.update/,
      }),
    );

    expect(hoisted.handleInstall).toHaveBeenCalledWith(latestVersion);
  });

  it("only shows the selector when the latest version is installed", () => {
    const oldVersion = makeEntry("1.1.0", {
      installed: true,
      installed_version: "1.2.0",
    });
    hoisted.plugins.push(
      makeEntry("1.2.0", {
        installed: true,
        installed_version: "1.2.0",
      }),
      oldVersion,
    );

    render(<OfficialPluginList onInstalled={vi.fn()} />);
    const article = screen.getByRole("article", { name: "Creator" });

    expect(within(article).getByRole("combobox")).toBeInTheDocument();
    expect(within(article).queryByRole("button")).not.toBeInTheDocument();
    fireEvent.mouseDown(within(article).getByRole("combobox"));
    expect(
      document.querySelector(".ant-select-item-option-selected .lucide-check"),
    ).not.toBeNull();
    fireEvent.click(screen.getByText("v1.1.0"));
    expect(
      within(article).getByRole("button", {
        name: /pluginManager.catalogInstall/,
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      within(article).getByRole("button", {
        name: /pluginManager.catalogInstall/,
      }),
    );
    expect(hoisted.handleInstall).toHaveBeenCalledWith(oldVersion);
  });

  it("shows the selector when the only catalog version is installed", () => {
    hoisted.plugins.push(
      makeEntry("1.0.0", {
        installed: true,
        installed_version: "1.0.0",
      }),
    );

    render(<OfficialPluginList onInstalled={vi.fn()} />);
    const article = screen.getByRole("article", { name: "Creator" });

    expect(within(article).getByRole("combobox")).toBeInTheDocument();
    expect(within(article).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a catalog-external installed version as the current selection", () => {
    hoisted.plugins.push(
      makeEntry("1.0.0", {
        installed: true,
        installed_version: "1.1.0",
      }),
    );

    render(<OfficialPluginList onInstalled={vi.fn()} />);
    const article = screen.getByRole("article", { name: "Creator" });
    expect(within(article).queryByRole("button")).not.toBeInTheDocument();
    expect(within(article).getByTitle("v1.1.0")).toBeInTheDocument();
    selectVersion(article, "1.0.0");
    expect(
      within(article).getByRole("button", {
        name: /pluginManager.catalogInstall/,
      }),
    ).toBeEnabled();
  });
});
