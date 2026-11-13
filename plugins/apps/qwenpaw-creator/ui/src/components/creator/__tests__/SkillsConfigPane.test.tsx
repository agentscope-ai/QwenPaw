import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfigProvider, message } from "antd";
import SkillsConfigPane from "../SkillsConfigPane";
import type {
  MarketSkillResult,
  SkillContent,
  SkillItem,
} from "@/api/creator/skills";
import zh from "@/locales/zh.json";

// Controllable API mocks so a test can hold skill "alpha"'s save open while
// the editor moves on to "beta" -- the state transition the save-completion
// sequence guard defends against (see the note inside that test on why the
// drive-through is synthetic rather than user-reachable).
const {
  listSkillsMock,
  getSkillContentMock,
  saveSkillMock,
  importUrlMock,
  searchMarketMock,
  listProvidersMock,
} = vi.hoisted(() => ({
  listSkillsMock: vi.fn(),
  getSkillContentMock: vi.fn(),
  saveSkillMock: vi.fn(),
  importUrlMock: vi.fn(),
  searchMarketMock: vi.fn(),
  listProvidersMock: vi.fn(),
}));

vi.mock("@/api/creator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/creator")>();
  return {
    ...actual,
    listSkills: listSkillsMock,
    getSkillContent: getSkillContentMock,
    saveSkill: saveSkillMock,
    importSkillFromUrl: importUrlMock,
    searchMarketSkills: searchMarketMock,
    listMarketProviders: listProvidersMock,
  };
});

function skillItem(name: string): SkillItem {
  return {
    name,
    description: `${name} description`,
    enabled: true,
    status: "available",
    reason: null,
    builtin: false,
  };
}

function skillContent(name: string): SkillContent {
  return {
    ok: true,
    skill: name,
    content: `${name} original body`,
    truncated: false,
  };
}

/** motion:false makes the antd Modal mount/unmount synchronously under jsdom. */
function renderPane() {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <SkillsConfigPane />
    </ConfigProvider>,
  );
}

// Row edit buttons in list order ([0]=alpha, [1]=beta). Scoped to role=button
// so the open editor dialog -- whose title is also t("skills.edit") and which
// is aria-labelledby that title -- is not matched.
function editButtons(): HTMLElement[] {
  return screen.getAllByRole("button", { name: zh.skills.edit });
}

// antd renders a two-CJK-character button label with a space ("保存" shows as
// "保 存"), so match the accessible name with optional whitespace per char.
function clickDialogButton(label: string): void {
  const name = new RegExp(label.split("").join("\\s*"));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name }),
  );
}

function saveButton(): HTMLElement {
  const name = new RegExp(zh.common.save.split("").join("\\s*"));
  return within(screen.getByRole("dialog")).getByRole("button", { name });
}

/** Open the create dialog through the "Add skill" dropdown. */
async function openCreateDialog(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: zh.skills.add }));
  const item = await screen.findByRole("menuitem", {
    name: zh.skills.newSkill,
  });
  fireEvent.click(item);
  await screen.findByRole("dialog");
}

describe("SkillsConfigPane editor session guard", () => {
  beforeEach(() => {
    listSkillsMock.mockResolvedValue({
      items: [skillItem("alpha"), skillItem("beta")],
    });
    getSkillContentMock.mockImplementation((name: string) =>
      Promise.resolve(skillContent(name)),
    );
  });

  it("keeps a newer edit open when an older save resolves late", async () => {
    // alpha's save stays pending until the test releases it, so it resolves
    // only after the editor has moved on to beta.
    let releaseAlphaSave = () => {};
    saveSkillMock.mockImplementation((name: string) =>
      name === "alpha"
        ? new Promise<{ ok: boolean; name: string }>((resolve) => {
            releaseAlphaSave = () => resolve({ ok: true, name });
          })
        : Promise.resolve({ ok: true, name }),
    );

    renderPane();
    await screen.findByText("alpha");
    await screen.findByText("beta");
    expect(editButtons()).toHaveLength(2);

    // Open alpha and start a save that will not resolve yet.
    fireEvent.click(editButtons()[0]);
    await screen.findByDisplayValue("alpha original body");
    await act(async () => {
      clickDialogButton(zh.common.save);
    });
    expect(saveSkillMock).toHaveBeenCalledWith(
      "alpha",
      "alpha original body",
      true,
    );

    // While alpha's save is still in flight, move the editor to beta and make
    // an unsaved edit. antd 6.5.0 blocks every cancel/close path during
    // confirmLoading and its mask covers the row actions, so this synthetic
    // drive-through proves the session-sequence state machine only -- it is
    // not a reproduction of a user-reachable flow.
    fireEvent.click(editButtons()[1]);
    await screen.findByDisplayValue("beta original body");
    fireEvent.change(screen.getByDisplayValue("beta original body"), {
      target: { value: "beta UNSAVED edit" },
    });

    // alpha's save now resolves late, after the editor moved on to beta.
    await act(async () => {
      releaseAlphaSave();
    });

    // The guard: alpha's completion must not close beta or drop its edits. A
    // regression closes the dialog and it stays closed, so this never settles.
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeNull();
      expect(screen.getByDisplayValue("beta UNSAVED edit")).toBeVisible();
    });
  });

  it("closes the editor when the save is still the active session", async () => {
    saveSkillMock.mockResolvedValue({ ok: true, name: "alpha" });

    renderPane();
    await screen.findByText("alpha");
    fireEvent.click(editButtons()[0]);
    await screen.findByDisplayValue("alpha original body");

    await act(async () => {
      clickDialogButton(zh.common.save);
    });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(saveSkillMock).toHaveBeenCalledWith(
      "alpha",
      "alpha original body",
      true,
    );
  });
});

/** Open the URL import dialog through the "Add skill" dropdown. */
async function openUrlImportDialog(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: zh.skills.add }));
  const item = await screen.findByRole("menuitem", {
    name: zh.skills.importUrl,
  });
  fireEvent.click(item);
  await screen.findByRole("dialog");
}

// The example typed by these tests, deliberately different from the field's
// own placeholder example.
const _URL_INPUT = "https://skills.sh/owner/repo/skill";

// Match the placeholder by shape instead of literal text: the component's
// example URL is product copy that moves with the recommended market, and a
// hard-coded copy of it here would only fail once the test already broke.
function urlInput(): HTMLElement {
  return within(screen.getByRole("dialog")).getByPlaceholderText(/^https:\/\//);
}

function importNameInput(): HTMLElement {
  return screen.getByPlaceholderText(zh.skills.importUrlNamePlaceholder);
}

function importButton(): HTMLElement {
  const name = new RegExp(zh.common.import.split("").join("\\s*"));
  return within(screen.getByRole("dialog")).getByRole("button", { name });
}

function importResult(name: string): Record<string, unknown> {
  return {
    imported: [name],
    skipped: [],
    count: 1,
    name,
    renamed_from: null,
    source_url: _URL_INPUT,
    installed_from: "skills-sh",
    ignored_files: 0,
  };
}

describe("SkillsConfigPane URL import", () => {
  beforeEach(() => {
    importUrlMock.mockReset();
    listSkillsMock.mockResolvedValue({
      items: [skillItem("alpha"), skillItem("beta")],
    });
    getSkillContentMock.mockImplementation((name: string) =>
      Promise.resolve(skillContent(name)),
    );
  });

  // antd renders toasts into a portal on document.body that outlives the
  // rendered tree, so a refusal left here would also match a later case's
  // inline hint by text and make findByText resolve to multiple elements.
  afterEach(async () => {
    await act(async () => {
      message.destroy();
    });
  });

  it("refuses an import whose chosen name already exists", async () => {
    // Same rule as the create flow, on the import path: an occupied name is
    // someone else's skill, and the panel must not offer that submit.
    importUrlMock.mockResolvedValue(importResult("alpha"));

    renderPane();
    await screen.findByText("alpha");
    await openUrlImportDialog();

    fireEvent.change(urlInput(), {
      target: { value: "https://skills.sh/acme/skills/alpha" },
    });
    fireEvent.change(importNameInput(), { target: { value: "alpha" } });

    expect(await screen.findByText(zh.skills.nameTaken)).toBeInTheDocument();
    expect(importButton()).toBeDisabled();
    await act(async () => {
      clickDialogButton(zh.common.import);
    });
    expect(importUrlMock).not.toHaveBeenCalled();

    // A free name is an ordinary import again: no warning, submit restored.
    fireEvent.change(importNameInput(), { target: { value: "gamma" } });
    expect(screen.queryByText(zh.skills.nameTaken)).toBeNull();
    expect(importButton()).toBeEnabled();
  });

  it("imports a skill from the URL and refreshes the list", async () => {
    importUrlMock.mockResolvedValue(importResult("hub-skill"));

    renderPane();
    await screen.findByText("alpha");
    const initialLoads = listSkillsMock.mock.calls.length;
    await openUrlImportDialog();

    // An untrimmed URL is what the user pasted; the request must carry the
    // trimmed one, and no name means the remote bundle decides.
    fireEvent.change(urlInput(), {
      target: { value: "  https://skills.sh/acme/skills/hub-skill  " },
    });
    await act(async () => {
      clickDialogButton(zh.common.import);
    });

    expect(importUrlMock).toHaveBeenCalledWith(
      "https://skills.sh/acme/skills/hub-skill",
      "",
    );
    expect(
      await screen.findByText(`${zh.skills.importUrlSuccess}: hub-skill`),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(listSkillsMock.mock.calls.length).toBeGreaterThan(initialLoads),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("surfaces the backend refusal instead of a generic failure", async () => {
    // The server is the authority on names and market reachability; its
    // reason is what has to reach the user.
    importUrlMock.mockRejectedValue(new Error("技能名已存在: alpha"));

    renderPane();
    await screen.findByText("alpha");
    await openUrlImportDialog();
    fireEvent.change(urlInput(), {
      target: { value: "https://skills.sh/acme/skills/alpha" },
    });
    await act(async () => {
      clickDialogButton(zh.common.import);
    });

    expect(await screen.findByText("技能名已存在: alpha")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("SkillsConfigPane duplicate skill name", () => {
  beforeEach(() => {
    // Vitest keeps call history across cases in a file, and this case asserts
    // a save that never happens.
    saveSkillMock.mockReset();
    listSkillsMock.mockResolvedValue({
      items: [skillItem("alpha"), skillItem("beta")],
    });
    getSkillContentMock.mockImplementation((name: string) =>
      Promise.resolve(skillContent(name)),
    );
  });

  it("refuses to create a skill on a name that already exists", async () => {
    // The backend is the authority, but the panel must not even offer the
    // destructive submit: a create on an occupied name would replace the
    // SKILL.md of the skill that already owns it.
    saveSkillMock.mockResolvedValue({ ok: true, name: "alpha" });

    renderPane();
    await screen.findByText("alpha");

    await openCreateDialog();
    fireEvent.change(screen.getByPlaceholderText("my-video-editing-skill"), {
      target: { value: "alpha" },
    });

    // toBeInTheDocument rather than toBeVisible: rc-motion keeps a freshly
    // opened dialog at opacity 0 under jsdom, and toBeVisible walks ancestor
    // opacity. The disabled save below is the part that must hold.
    expect(await screen.findByText(zh.skills.nameTaken)).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    await act(async () => {
      clickDialogButton(zh.common.save);
    });
    expect(saveSkillMock).not.toHaveBeenCalled();

    // A free name stays an ordinary create: no warning, no overwrite intent.
    fireEvent.change(screen.getByPlaceholderText("my-video-editing-skill"), {
      target: { value: "gamma" },
    });
    expect(screen.queryByText(zh.skills.nameTaken)).toBeNull();
    expect(saveButton()).toBeEnabled();
    await act(async () => {
      clickDialogButton(zh.common.save);
    });
    expect(saveSkillMock).toHaveBeenCalledWith(
      "gamma",
      expect.any(String),
      false,
    );
  });
});

describe("SkillsConfigPane pending-write freeze", () => {
  beforeEach(() => {
    saveSkillMock.mockReset();
    importUrlMock.mockReset();
    listSkillsMock.mockResolvedValue({
      items: [skillItem("alpha"), skillItem("beta")],
    });
    getSkillContentMock.mockImplementation((name: string) =>
      Promise.resolve(skillContent(name)),
    );
  });

  // antd renders toasts into a portal on document.body that outlives the
  // rendered tree, so one left here would match a later case's inline hint.
  afterEach(async () => {
    await act(async () => {
      message.destroy();
    });
  });

  // focus + keyboard rather than type(): a write in flight puts antd's
  // confirmLoading on the dialog, and what these cases assert is whether
  // keystrokes reach the field, not where a click lands. jsdom leaves the
  // caret at 0 on focus, so move it to the end the way a click into an
  // already-filled editor would -- otherwise the typing prepends.
  function focusAndType(element: HTMLElement, text: string) {
    const field = element as HTMLInputElement | HTMLTextAreaElement;
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
    return userEvent.setup().keyboard(text);
  }

  it("freezes the editor body so a save cannot drop what is typed next", async () => {
    // The request carries the content as of the click and success closes this
    // same session, so an editable body let the user type a newer draft that
    // the closing dialog then discarded without a word. editSeqRef separates
    // sessions, not drafts inside one.
    let releaseSave = () => {};
    saveSkillMock.mockImplementation(
      (name: string) =>
        new Promise<{ ok: boolean; name: string }>((resolve) => {
          releaseSave = () => resolve({ ok: true, name });
        }),
    );

    renderPane();
    await screen.findByText("alpha");
    fireEvent.click(editButtons()[0]);
    const body = await screen.findByDisplayValue("alpha original body");

    // Positive control: real keystrokes do land before the save starts, so
    // the no-op below is the freeze and not a harness that cannot type.
    await focusAndType(body, " drafted");
    expect(body).toHaveDisplayValue("alpha original body drafted");

    await act(async () => {
      clickDialogButton(zh.common.save);
    });
    expect(saveSkillMock).toHaveBeenCalledWith(
      "alpha",
      "alpha original body drafted",
      true,
    );

    expect(body).toHaveAttribute("readonly");
    expect(
      within(screen.getByRole("dialog")).getByRole("switch"),
    ).toBeDisabled();
    await focusAndType(body, " then lost");
    expect(body).toHaveDisplayValue("alpha original body drafted");

    await act(async () => {
      releaseSave();
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // One submit, carrying exactly the draft that was on screen at the click:
    // nothing typed afterwards was stored, and nothing was silently dropped.
    expect(saveSkillMock).toHaveBeenCalledTimes(1);
  });

  it("freezes the URL fields so a pending import cannot drop a retype", async () => {
    // Same shape one dialog over: success closes this dialog and clears both
    // fields, so a URL retyped during the wait would vanish the same way.
    let releaseImport = () => {};
    importUrlMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          releaseImport = () => resolve(importResult("hub-skill"));
        }),
    );

    renderPane();
    await screen.findByText("alpha");
    await openUrlImportDialog();
    const url = urlInput();

    await focusAndType(url, "https://x");
    expect(url).toHaveDisplayValue("https://x");
    fireEvent.change(url, { target: { value: _URL_INPUT } });

    await act(async () => {
      clickDialogButton(zh.common.import);
    });
    expect(importUrlMock).toHaveBeenCalledWith(_URL_INPUT, "");

    expect(url).toHaveAttribute("readonly");
    expect(importNameInput()).toHaveAttribute("readonly");
    await focusAndType(url, "lost");
    expect(url).toHaveDisplayValue(_URL_INPUT);

    await act(async () => {
      releaseImport();
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(importUrlMock).toHaveBeenCalledTimes(1);
  });
});

/** One catalogue row, shaped like the market search response. */
function marketItem(slug: string): MarketSkillResult {
  return {
    source: "qwenpaw",
    source_label: null,
    slug,
    name: slug,
    description: `${slug} description`,
    source_url: `https://market.test/${slug}`,
    version: null,
    author: null,
    icon_url: null,
    stats: null,
  };
}

/** Open the market browser through the "Add skill" dropdown. */
async function openMarket(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: zh.skills.add }));
  const item = await screen.findByRole("menuitem", {
    name: zh.skills.browseMarket,
  });
  fireEvent.click(item);
  await screen.findByRole("dialog");
}

// Anchored, because "安装" is a substring of "已安装", and spaced, because
// antd renders a two-CJK-character button label as "安 装".
function dialogButtonByLabel(label: string): HTMLElement {
  const name = new RegExp(`^${label.split("").join("\\s*")}$`);
  return within(screen.getByRole("dialog")).getByRole("button", { name });
}

function installButtons(): HTMLElement[] {
  return within(screen.getByRole("dialog")).queryAllByRole("button", {
    name: new RegExp(`^${zh.skills.marketInstall.split("").join("\\s*")}$`),
  });
}

async function submitMarketSearch(term: string): Promise<void> {
  const box = within(screen.getByRole("dialog")).getByPlaceholderText(
    zh.skills.marketSearchPlaceholder,
  );
  // Flush the draft through a render before clicking, or the click would run
  // against the previous query closure.
  await act(async () => {
    fireEvent.change(box, { target: { value: term } });
  });
  await act(async () => {
    fireEvent.click(dialogButtonByLabel(zh.common.search));
  });
}

describe("SkillsConfigPane market install identity", () => {
  beforeEach(() => {
    listSkillsMock.mockReset();
    importUrlMock.mockReset();
    searchMarketMock.mockReset();
    listProvidersMock.mockReset();
    window.localStorage.clear();
    listProvidersMock.mockResolvedValue({
      providers: [
        {
          key: "qwenpaw",
          label: "QwenPaw",
          available: true,
          reason: null,
          supports_browse: true,
        },
      ],
    });
    searchMarketMock.mockResolvedValue({
      results: [marketItem("p1-alpha")],
      has_more: false,
      totals: { qwenpaw: 1 },
    });
  });

  it("keeps a renamed install marked after the pane remounts", async () => {
    // Settings renders this pane behind `activePane === "skills"`, so
    // switching panes rebuilds the whole tree -- the boundary the install
    // identity has to survive, unlike a close/reopen of the modal alone.
    listSkillsMock.mockResolvedValue({ items: [] });
    importUrlMock.mockResolvedValue({
      ...importResult("my-skill"),
      renamed_from: "My Skill",
    });

    const first = renderPane();
    await openMarket();
    await submitMarketSearch("alpha");
    await act(async () => {
      fireEvent.click(installButtons()[0]);
    });
    expect(importUrlMock).toHaveBeenCalledWith("https://market.test/p1-alpha");

    first.unmount();
    // The refetched library reports the folded name while the catalogue still
    // labels the row "p1-alpha"; only the remembered identity links them.
    listSkillsMock.mockResolvedValue({ items: [skillItem("my-skill")] });
    renderPane();
    await screen.findByText("my-skill");

    await openMarket();
    await submitMarketSearch("alpha");

    expect(installButtons()).toHaveLength(0);
    expect(dialogButtonByLabel(zh.skills.marketInstalled)).toBeDisabled();
  });
});
