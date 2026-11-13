import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfigProvider, message } from "antd";
import SkillMarketBrowser from "../SkillMarketBrowser";
import type { MarketSkillResult } from "@/api/creator/skills";
import i18n from "@/i18n";
import zh from "@/locales/zh.json";

// Controllable market API: paging is decided by the (query, page) pair the
// component sends, so tests read the call log instead of the rendered rows.
const { searchMarketMock, importUrlMock, listProvidersMock } = vi.hoisted(
  () => ({
    searchMarketMock: vi.fn(),
    importUrlMock: vi.fn(),
    listProvidersMock: vi.fn(),
  }),
);

vi.mock("@/api/creator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/creator")>();
  return {
    ...actual,
    searchMarketSkills: searchMarketMock,
    importSkillFromUrl: importUrlMock,
    listMarketProviders: listProvidersMock,
  };
});

const LANG = "zh";
const PAGE_SIZE = 20;

function marketItem(slug: string): MarketSkillResult {
  return {
    source: "qwenpaw",
    source_label: null,
    slug,
    name: slug,
    description: `${slug} description`,
    source_url: `https://example.test/${slug}`,
    version: null,
    author: null,
    icon_url: null,
    stats: null,
  };
}

function searchPage(items: MarketSkillResult[], hasMore: boolean) {
  return Promise.resolve({
    results: items,
    has_more: hasMore,
    totals: { qwenpaw: items.length },
  });
}

function provider(
  label: string,
  available = true,
  reason: string | null = null,
) {
  return {
    key: label.toLowerCase(),
    label,
    available,
    reason,
    supports_browse: true,
  };
}

function installResult(name: string, renamedFrom: string | null = null) {
  return {
    imported: [name],
    skipped: [],
    count: 1,
    name,
    renamed_from: renamedFrom,
    source_url: "https://example.test/whatever",
    installed_from: "qwenpaw",
    ignored_files: 0,
  };
}

/** The props the pane would pass; `open` is the modal's lifecycle. */
interface BrowserState {
  open: boolean;
  installedNames: string[];
}

/** motion:false makes the antd Modal mount/unmount synchronously under jsdom. */
function browserTree(props: BrowserState, onInstalled: () => void) {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <SkillMarketBrowser
        open={props.open}
        onClose={vi.fn()}
        onInstalled={onInstalled}
        installedNames={props.installedNames}
      />
    </ConfigProvider>
  );
}

function renderBrowser(installedNames: string[] = []) {
  const onInstalled = vi.fn();
  const { unmount } = render(
    browserTree({ open: true, installedNames }, onInstalled),
  );
  return { onInstalled, unmount };
}

/**
 * Render the browser the way its parent does and let a test drive the props,
 * which is the only way to cross a close/reopen boundary: the install identity
 * has to survive the modal unmounting, and the library is refetched meanwhile.
 */
function renderControlled(installedNames: string[] = []) {
  const onInstalled = vi.fn();
  // Accumulate, so a later update builds on what the previous one set instead
  // of falling back to the first render's props.
  let state: BrowserState = { open: true, installedNames };
  const { rerender, unmount } = render(browserTree(state, onInstalled));
  return {
    onInstalled,
    unmount,
    update(next: Partial<BrowserState>) {
      state = { ...state, ...next };
      rerender(browserTree(state, onInstalled));
    },
  };
}

function searchBox(): HTMLElement {
  return screen.getByPlaceholderText(zh.skills.marketSearchPlaceholder);
}

// antd renders a two-CJK-character button label with a space ("搜索" shows as
// "搜 索"), so match the accessible name with optional whitespace per char.
// Anchored, because "安装" is a substring of "已安装".
function dialogButton(label: string): RegExp {
  return new RegExp(`^${label.split("").join("\\s*")}$`);
}

function buttonsByLabel(label: string): HTMLElement[] {
  // Query, not getAll: a test asserts the absence of an install action.
  return within(screen.getByRole("dialog")).queryAllByRole("button", {
    name: dialogButton(label),
  });
}

function buttonByLabel(label: string): HTMLElement {
  return within(screen.getByRole("dialog")).getByRole("button", {
    name: dialogButton(label),
  });
}

/** The n-th row's install action, failing loudly when it is not rendered. */
function installButton(index = 0): HTMLElement {
  const buttons = buttonsByLabel(zh.skills.marketInstall);
  expect(buttons.length).toBeGreaterThan(index);
  return buttons[index];
}

/** Submit the current input draft as a search. */
async function submitSearch(term: string): Promise<void> {
  // The draft must be flushed through a render before the click, otherwise
  // the click would still run against the previous `query` closure.
  await typeDraft(term);
  await act(async () => {
    fireEvent.click(buttonByLabel(zh.common.search));
  });
}

/** Edit the input without submitting it. */
async function typeDraft(term: string): Promise<void> {
  await act(async () => {
    fireEvent.change(searchBox(), { target: { value: term } });
  });
  expect(searchBox()).toHaveValue(term);
}

async function clickLoadMore(): Promise<void> {
  await act(async () => {
    fireEvent.click(buttonByLabel(zh.common.more));
  });
}

function pageRequests(): string[] {
  return searchMarketMock.mock.calls.map(([, page]) => `${String(page)}`);
}

describe("SkillMarketBrowser paging", () => {
  beforeEach(() => {
    searchMarketMock.mockReset();
    importUrlMock.mockReset();
    listProvidersMock.mockReset();
    // The install identity outlives the component on purpose, so every test
    // has to start from an empty store or the previous one would leak in.
    window.localStorage.clear();
    listProvidersMock.mockResolvedValue({ providers: [provider("QwenPaw")] });
    // Every test starts with the browse request the modal fires on open.
    searchMarketMock.mockImplementation((query: string, page: number) =>
      searchPage([marketItem(`p${page}-${query || "browse"}`)], true),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("requests page 2 for the term whose results are on screen", async () => {
    renderBrowser();
    await submitSearch("alpha");
    expect(searchMarketMock).toHaveBeenLastCalledWith(
      "alpha",
      1,
      PAGE_SIZE,
      LANG,
    );

    // Type a new term but do not submit it, then page. The draft must not
    // leak into the request: page 2 has to belong to "alpha".
    await typeDraft("beta");
    await clickLoadMore();

    expect(searchMarketMock).toHaveBeenLastCalledWith(
      "alpha",
      2,
      PAGE_SIZE,
      LANG,
    );
    // And the rows stay a single-term list: alpha page 1 + alpha page 2.
    expect(screen.getByText("p1-alpha")).toBeVisible();
    expect(screen.getByText("p2-alpha")).toBeVisible();
    expect(screen.queryByText("p1-beta")).toBeNull();
  });

  it("retries the page that failed instead of skipping it", async () => {
    let failPageTwo = true;
    searchMarketMock.mockImplementation((query: string, page: number) => {
      if (page === 1) {
        return searchPage([marketItem(`p1-${query}`)], true);
      }
      if (failPageTwo) {
        return Promise.reject(new Error("market unavailable"));
      }
      return searchPage([marketItem(`p2-${query}`)], false);
    });
    renderBrowser();
    await submitSearch("alpha");

    await clickLoadMore(); // page 2 fails
    expect(screen.queryByText("p2-alpha")).toBeNull();

    failPageTwo = false;
    await clickLoadMore(); // must retry page 2, not jump to page 3

    expect(pageRequests().filter((page) => page === "2")).toEqual(["2", "2"]);
    expect(searchMarketMock).toHaveBeenLastCalledWith(
      "alpha",
      2,
      PAGE_SIZE,
      LANG,
    );
    expect(screen.getByText("p1-alpha")).toBeVisible();
    expect(screen.getByText("p2-alpha")).toBeVisible();
  });

  it("starts a new term over at page 1 and drops the previous results", async () => {
    renderBrowser();
    await submitSearch("alpha");
    await clickLoadMore();
    expect(screen.getByText("p2-alpha")).toBeVisible();

    await submitSearch("beta");

    expect(searchMarketMock).toHaveBeenLastCalledWith(
      "beta",
      1,
      PAGE_SIZE,
      LANG,
    );
    // alpha's two pages are gone, so the next page request is beta page 2.
    expect(screen.queryByText("p1-alpha")).toBeNull();
    expect(screen.queryByText("p2-alpha")).toBeNull();

    await clickLoadMore();
    expect(searchMarketMock).toHaveBeenLastCalledWith(
      "beta",
      2,
      PAGE_SIZE,
      LANG,
    );
    expect(screen.getByText("p1-beta")).toBeVisible();
    expect(screen.getByText("p2-beta")).toBeVisible();
  });

  it("keeps paging from the last good term when a new search fails", async () => {
    let rejectAlpha = false;
    searchMarketMock.mockImplementation((query: string, page: number) => {
      if (rejectAlpha && query === "alpha") {
        return Promise.reject(new Error("market unavailable"));
      }
      return searchPage([marketItem(`p${page}-${query || "browse"}`)], true);
    });
    renderBrowser();
    await submitSearch("beta");

    // A failed search must not re-commit the term or reset the page: what is
    // on screen is still beta, so "load more" continues beta.
    rejectAlpha = true;
    await submitSearch("alpha");
    expect(screen.queryByText("p1-alpha")).toBeNull();

    rejectAlpha = false;
    await clickLoadMore();
    expect(searchMarketMock).toHaveBeenLastCalledWith(
      "beta",
      2,
      PAGE_SIZE,
      LANG,
    );
  });

  it("installs through the item source url and marks it installed", async () => {
    importUrlMock.mockResolvedValue(installResult("p1-alpha"));
    const { onInstalled } = renderBrowser();
    await submitSearch("alpha");

    await act(async () => {
      fireEvent.click(installButton());
    });

    expect(importUrlMock).toHaveBeenCalledWith("https://example.test/p1-alpha");
    expect(onInstalled).toHaveBeenCalled();
    expect(
      within(screen.getByRole("dialog")).queryByText(zh.skills.marketInstalled),
    ).not.toBeNull();
    expect(buttonByLabel(zh.skills.marketInstalled)).toBeDisabled();
  });

  it("does not offer an install for a skill already in the library", async () => {
    renderBrowser(["p1-alpha"]);
    await submitSearch("alpha");

    expect(buttonsByLabel(zh.skills.marketInstall)).toHaveLength(0);
    expect(buttonByLabel(zh.skills.marketInstalled)).toBeDisabled();
    expect(importUrlMock).not.toHaveBeenCalled();
  });

  it("reports the name the backend really installed and closes the row", async () => {
    // The market row is called "My Skill"; the backend folds it into a valid
    // slug, so neither the toast nor the row state may keep the row's name.
    importUrlMock.mockResolvedValue(installResult("my-skill", "My Skill"));
    const success = vi.spyOn(message, "success");
    const warning = vi.spyOn(message, "warning");
    const { onInstalled } = renderBrowser();
    await submitSearch("alpha");

    await act(async () => {
      fireEvent.click(installButton());
    });

    expect(success).toHaveBeenCalledWith(
      `${zh.skills.importUrlSuccess}: my-skill`,
    );
    expect(warning).toHaveBeenCalledWith(
      i18n.t("skills.importUrlRenamed", { from: "My Skill", to: "my-skill" }),
    );
    expect(onInstalled).toHaveBeenCalled();
    // The refreshed library carries the folded name, which never matches this
    // row, so the row-to-name map is what keeps a refused second install from
    // being offered.
    expect(buttonsByLabel(zh.skills.marketInstall)).toHaveLength(0);

    await act(async () => {
      fireEvent.click(buttonByLabel(zh.skills.marketInstalled));
    });
    expect(importUrlMock).toHaveBeenCalledTimes(1);
  });

  it("keeps a renamed install marked after a close and a reopen", async () => {
    importUrlMock.mockResolvedValue(installResult("my-skill", "My Skill"));
    const browser = renderControlled();
    await submitSearch("alpha");

    await act(async () => {
      fireEvent.click(installButton());
    });

    // The pane refetched its library after the install and now reports the
    // folded name; the market catalogue still labels this row "p1-alpha".
    // Only the row identity can tell that these are the same skill.
    await act(async () => {
      browser.update({ open: false, installedNames: ["my-skill"] });
    });
    await act(async () => {
      browser.update({ open: true });
    });
    await submitSearch("alpha");

    expect(buttonsByLabel(zh.skills.marketInstall)).toHaveLength(0);
    expect(buttonByLabel(zh.skills.marketInstalled)).toBeDisabled();
  });

  it("offers the install again once the renamed skill left the library", async () => {
    importUrlMock.mockResolvedValue(installResult("my-skill", "My Skill"));
    const browser = renderControlled();
    await submitSearch("alpha");

    await act(async () => {
      fireEvent.click(installButton());
    });

    // Deleting the skill must free the row again: the row memory is only
    // trusted while the library still reports the name it installed.
    await act(async () => {
      browser.update({ open: false, installedNames: [] });
    });
    await act(async () => {
      browser.update({ open: true });
    });
    await submitSearch("alpha");

    expect(buttonsByLabel(zh.skills.marketInstall)).toHaveLength(1);
    expect(buttonsByLabel(zh.skills.marketInstalled)).toHaveLength(0);
  });

  it("keeps the install identity across a pane remount", async () => {
    // Settings renders the pane conditionally, so switching to another pane
    // unmounts this whole tree and drops every piece of component state.
    importUrlMock.mockResolvedValue(installResult("my-skill", "My Skill"));
    const first = renderControlled();
    await submitSearch("alpha");
    await act(async () => {
      fireEvent.click(installButton());
    });
    first.unmount();

    // A fresh mount that already knows the folded name, exactly what the pane
    // would pass after refetching its library.
    renderBrowser(["my-skill"]);
    await submitSearch("alpha");

    expect(buttonsByLabel(zh.skills.marketInstall)).toHaveLength(0);
    expect(buttonByLabel(zh.skills.marketInstalled)).toBeDisabled();
  });

  it("frees the row after a delete and marks it again on reinstall", async () => {
    importUrlMock.mockResolvedValue(installResult("my-skill", "My Skill"));
    const first = renderControlled();
    await submitSearch("alpha");
    await act(async () => {
      fireEvent.click(installButton());
    });
    first.unmount();

    // The skill was deleted while the pane was gone: the stored identity must
    // not keep the row blocked forever.
    renderBrowser([]);
    await submitSearch("alpha");
    expect(buttonsByLabel(zh.skills.marketInstall)).toHaveLength(1);

    await act(async () => {
      fireEvent.click(installButton());
    });
    expect(importUrlMock).toHaveBeenCalledTimes(2);
    expect(buttonsByLabel(zh.skills.marketInstall)).toHaveLength(0);
    expect(buttonByLabel(zh.skills.marketInstalled)).toBeDisabled();
  });

  it("names the unusable markets together with the host's reason", async () => {
    listProvidersMock.mockResolvedValue({
      providers: [
        provider("QwenPaw"),
        provider("Aliyun", false, "access key 未配置"),
        provider("ClawHub", false, null),
      ],
    });
    renderBrowser();

    const notice = await screen.findByText(/Aliyun/);
    expect(notice.textContent).toContain("access key 未配置");
    expect(notice.textContent).toContain("ClawHub");
    // A reachable market is not listed as a problem.
    expect(notice.textContent).not.toContain("QwenPaw");
  });

  it("shows no market warning when every provider is usable", async () => {
    const error = vi.spyOn(message, "error");
    renderBrowser();
    await waitFor(() => expect(listProvidersMock).toHaveBeenCalled());

    expect(screen.queryByText(/Aliyun/)).toBeNull();
    expect(error).not.toHaveBeenCalled();
  });

  it("warns when the market status itself cannot be read", async () => {
    listProvidersMock.mockRejectedValue(new Error("network down"));
    const error = vi.spyOn(message, "error");
    renderBrowser();

    await waitFor(() =>
      expect(error).toHaveBeenCalledWith(zh.skills.marketLoadFailed),
    );
  });

  it("passes the backend's own search guidance through", async () => {
    const detail = "当前运行时未提供技能市场搜索能力，请改用 URL 导入";
    searchMarketMock.mockRejectedValue(new Error(detail));
    const error = vi.spyOn(message, "error");
    renderBrowser();
    await submitSearch("alpha");

    expect(error).toHaveBeenCalledWith(detail);
  });

  it("falls back to a generic failure when the server says nothing", async () => {
    searchMarketMock.mockRejectedValue(new Error(""));
    const error = vi.spyOn(message, "error");
    renderBrowser();
    await submitSearch("alpha");

    expect(error).toHaveBeenCalledWith(zh.skills.marketSearchFailed);
  });
});
