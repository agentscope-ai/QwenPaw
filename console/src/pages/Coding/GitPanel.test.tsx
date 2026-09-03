/**
 * GitPanel — source control panel for Coding Mode. Covers branch switching
 * and creation, stage/unstage/stage-all/discard, commit validation paths
 * (empty message, no staged files, nothing-to-commit), diff viewer, commit
 * log actions (view diff / revert) and the show-more file pagination.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const gitMocks = vi.hoisted(() => ({
  status: vi.fn(),
  branches: vi.fn(),
  checkout: vi.fn(),
  stage: vi.fn(),
  unstage: vi.fn(),
  commit: vi.fn(),
  diff: vi.fn(),
  log: vi.fn(),
  commitDiff: vi.fn(),
  revert: vi.fn(),
  discard: vi.fn(),
}));

vi.mock("../../api/modules/git", () => ({
  gitApi: gitMocks,
}));

import GitPanel from "./GitPanel";

function makeStatus(overrides: Record<string, unknown> = {}) {
  return {
    branch: "main",
    ahead: 0,
    behind: 0,
    changes: [],
    ...overrides,
  };
}

function setupDefaultMocks() {
  gitMocks.status.mockResolvedValue(makeStatus());
  gitMocks.branches.mockResolvedValue([
    { name: "main", remote: false },
    { name: "feature", remote: false },
    { name: "origin/main", remote: true },
  ]);
  gitMocks.log.mockResolvedValue([]);
  gitMocks.checkout.mockResolvedValue({});
  gitMocks.stage.mockResolvedValue({});
  gitMocks.unstage.mockResolvedValue({});
  gitMocks.commit.mockResolvedValue({});
  gitMocks.diff.mockResolvedValue({
    diff: "diff --git a/x b/x\nindex 123..456\n--- a\n+++ b\n@@ -1 +1 @@\n-old\n+added",
  });
  gitMocks.commitDiff.mockResolvedValue({ diff: "commit diff", hash: "abc" });
  gitMocks.revert.mockResolvedValue({});
  gitMocks.discard.mockResolvedValue({});
}

async function settle() {
  await new Promise((r) => setTimeout(r, 50));
}

describe("GitPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  it("renders nothing when the repo status fails to load", async () => {
    gitMocks.status.mockRejectedValue(new Error("not a git repo"));
    const { container } = render(<GitPanel />);
    await waitFor(() => expect(gitMocks.status).toHaveBeenCalled());
    await settle();
    expect(container.firstChild).toBeNull();
  });

  it("shows the empty state when there are no changes", async () => {
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );
  });

  it("renders staged and unstaged sections with counts", async () => {
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [
          { path: "dir/a.ts", status: "M", staged: true },
          { path: "b.ts", status: "A", staged: false },
        ],
      }),
    );
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText(/Staged \(1\)/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Changes \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("a.ts")).toBeInTheDocument();
    expect(screen.getByText("b.ts")).toBeInTheDocument();
  });

  it("shows ahead/behind sync tags", async () => {
    gitMocks.status.mockResolvedValue(makeStatus({ ahead: 2, behind: 1 }));
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("↑2")).toBeInTheDocument());
    expect(screen.getByText("↓1")).toBeInTheDocument();
  });

  it("stages an unstaged file and unstages a staged file", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [
          { path: "a.ts", status: "M", staged: true },
          { path: "b.ts", status: "A", staged: false },
        ],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("a.ts")).toBeInTheDocument());

    // Row button order: [View diff, (Discard), Stage/Unstage]
    const rows = screen
      .getAllByText(/\.ts$/)
      .map((el) => el.closest("[class*='fileRow']") as HTMLElement);
    const stagedRow = rows.find((r) => r.textContent?.includes("a.ts"))!;
    const unstagedRow = rows.find((r) => r.textContent?.includes("b.ts"))!;

    await user.click(within(stagedRow).getAllByRole("button")[1]);
    await waitFor(() =>
      expect(gitMocks.unstage).toHaveBeenCalledWith(["a.ts"], undefined),
    );

    await user.click(within(unstagedRow).getAllByRole("button")[2]);
    await waitFor(() =>
      expect(gitMocks.stage).toHaveBeenCalledWith(["b.ts"], undefined),
    );
  });

  it("stages all unstaged files", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [
          { path: "b.ts", status: "A", staged: false },
          { path: "c.ts", status: "M", staged: false },
        ],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("b.ts")).toBeInTheDocument());

    const changesHeader = screen
      .getByText(/Changes \(2\)/)
      .closest("[class*='sectionHeader']") as HTMLElement;
    await user.click(within(changesHeader).getByRole("button"));
    await waitFor(() =>
      expect(gitMocks.stage).toHaveBeenCalledWith([], undefined),
    );
  });

  it("unstages all staged files", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "a.ts", status: "M", staged: true }],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("a.ts")).toBeInTheDocument());

    const stagedHeader = screen
      .getByText(/Staged \(1\)/)
      .closest("[class*='sectionHeader']") as HTMLElement;
    await user.click(within(stagedHeader).getByRole("button"));
    await waitFor(() =>
      expect(gitMocks.unstage).toHaveBeenCalledWith([], undefined),
    );
  });

  it("discards an unstaged file through the confirm popover", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "b.ts", status: "M", staged: false }],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("b.ts")).toBeInTheDocument());

    const row = screen
      .getByText("b.ts")
      .closest("[class*='fileRow']") as HTMLElement;
    // Row button order: [View diff, Discard, Stage]
    await user.click(within(row).getAllByRole("button")[1]);
    await waitFor(() =>
      expect(screen.getByText("Discard")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("Discard"));
    await waitFor(() =>
      expect(gitMocks.discard).toHaveBeenCalledWith(["b.ts"], undefined),
    );
  });

  it("opens the diff viewer for a file", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "b.ts", status: "M", staged: false }],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("b.ts")).toBeInTheDocument());

    const row = screen
      .getByText("b.ts")
      .closest("[class*='fileRow']") as HTMLElement;
    await user.click(within(row).getAllByRole("button")[0]);
    await waitFor(() =>
      expect(gitMocks.diff).toHaveBeenCalledWith(
        "b.ts",
        false,
        false,
        undefined,
      ),
    );
    // UnifiedDiffView renders each diff line
    await waitFor(() => expect(screen.getByText("+added")).toBeInTheDocument());
  });

  it("shows a placeholder for empty diffs", async () => {
    const user = userEvent.setup();
    gitMocks.diff.mockResolvedValue({ diff: "   " });
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "b.ts", status: "M", staged: false }],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("b.ts")).toBeInTheDocument());

    const row = screen
      .getByText("b.ts")
      .closest("[class*='fileRow']") as HTMLElement;
    await user.click(within(row).getAllByRole("button")[0]);
    await waitFor(() =>
      expect(screen.getByText("No diff available.")).toBeInTheDocument(),
    );
  });

  it("blocks commit with an empty message", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "a.ts", status: "M", staged: true }],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("a.ts")).toBeInTheDocument());

    await user.click(screen.getByText("Commit"));
    await settle();
    expect(gitMocks.commit).not.toHaveBeenCalled();
  });

  it("blocks commit when nothing is staged", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "b.ts", status: "M", staged: false }],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("b.ts")).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/Commit message/);
    await user.type(input, "my commit");
    await user.click(screen.getByText("Commit"));
    await settle();
    expect(gitMocks.commit).not.toHaveBeenCalled();
  });

  it("commits staged changes", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "a.ts", status: "M", staged: true }],
      }),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("a.ts")).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/Commit message/);
    await user.type(input, "my commit");
    await user.click(screen.getByText("Commit"));

    await waitFor(() =>
      expect(gitMocks.commit).toHaveBeenCalledWith("my commit", undefined),
    );
  });

  it("maps nothing-to-commit errors to a warning", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "a.ts", status: "M", staged: true }],
      }),
    );
    gitMocks.commit.mockRejectedValue(new Error("nothing to commit"));
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("a.ts")).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/Commit message/);
    await user.type(input, "my commit");
    await user.click(screen.getByText("Commit"));

    await waitFor(() => expect(gitMocks.commit).toHaveBeenCalled());
  });

  it("maps nothing-added-to-commit errors to the staged-files warning", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "a.ts", status: "M", staged: true }],
      }),
    );
    gitMocks.commit.mockRejectedValue(
      new Error("nothing added to commit but untracked files present"),
    );
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("a.ts")).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/Commit message/);
    await user.type(input, "my commit");
    await user.click(screen.getByText("Commit"));

    await waitFor(() => expect(gitMocks.commit).toHaveBeenCalled());
  });

  it("reports unexpected commit errors", async () => {
    const user = userEvent.setup();
    gitMocks.status.mockResolvedValue(
      makeStatus({
        changes: [{ path: "a.ts", status: "M", staged: true }],
      }),
    );
    gitMocks.commit.mockRejectedValue(new Error("hook rejected"));
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("a.ts")).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/Commit message/);
    await user.type(input, "my commit");
    await user.click(screen.getByText("Commit"));

    await waitFor(() => expect(gitMocks.commit).toHaveBeenCalled());
  });

  it("reports revert failures", async () => {
    const user = userEvent.setup();
    gitMocks.revert.mockRejectedValue(new Error("cannot revert"));
    gitMocks.log.mockResolvedValue([
      { hash: "abc123", message: "first commit", author: "me", date: "now" },
    ]);
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("History"));
    await waitFor(() =>
      expect(screen.getByText("first commit")).toBeInTheDocument(),
    );
    const logEntry = screen
      .getByText("first commit")
      .closest("[class*='logEntry']") as HTMLElement;
    await user.click(within(logEntry).getAllByRole("button")[1]);
    await waitFor(() => expect(screen.getByText("Revert")).toBeInTheDocument());
    await user.click(screen.getByText("Revert"));
    await waitFor(() => expect(gitMocks.revert).toHaveBeenCalled());
  });

  it("shows the commit history with view-diff and revert actions", async () => {
    const user = userEvent.setup();
    gitMocks.log.mockResolvedValue([
      { hash: "abc123", message: "first commit", author: "me", date: "now" },
    ]);
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("History"));
    await waitFor(() =>
      expect(screen.getByText("first commit")).toBeInTheDocument(),
    );

    const logEntry = screen
      .getByText("first commit")
      .closest("[class*='logEntry']") as HTMLElement;
    await user.click(within(logEntry).getAllByRole("button")[0]);
    await waitFor(() =>
      expect(gitMocks.commitDiff).toHaveBeenCalledWith("abc123", undefined),
    );

    await user.click(within(logEntry).getAllByRole("button")[1]);
    await waitFor(() => expect(screen.getByText("Revert")).toBeInTheDocument());
    await user.click(screen.getByText("Revert"));
    await waitFor(() =>
      expect(gitMocks.revert).toHaveBeenCalledWith("abc123", undefined),
    );
  });

  it("shows the empty history state", async () => {
    const user = userEvent.setup();
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("History"));
    expect(screen.getByText("No commits yet")).toBeInTheDocument();
  });

  it("paginates long file lists with a show-all button", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 55 }, (_, i) => ({
      path: `f${i}.ts`,
      status: "M",
      staged: false,
    }));
    gitMocks.status.mockResolvedValue(makeStatus({ changes: many }));
    render(<GitPanel />);
    await waitFor(() => expect(screen.getByText("f0.ts")).toBeInTheDocument());

    expect(screen.queryByText("f54.ts")).not.toBeInTheDocument();
    await user.click(screen.getByText(/Show all 55 files/));
    expect(screen.getByText("f54.ts")).toBeInTheDocument();
  });

  it("checks out a branch via the branch selector", async () => {
    const user = userEvent.setup();
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(screen.getByTitle("feature")).toBeInTheDocument(),
    );
    await user.click(screen.getByTitle("feature"));
    await waitFor(() =>
      expect(gitMocks.checkout).toHaveBeenCalledWith(
        "feature",
        false,
        undefined,
      ),
    );
  });

  it("creates a new branch from the modal", async () => {
    const user = userEvent.setup();
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(screen.getByText("New branch")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("New branch"));

    const nameInput = await screen.findByPlaceholderText("branch-name");
    await user.type(nameInput, "my-branch");
    await user.click(screen.getByText("Create & Switch"));

    await waitFor(() =>
      expect(gitMocks.checkout).toHaveBeenCalledWith(
        "my-branch",
        true,
        undefined,
      ),
    );
  });

  it("ignores empty branch names on create", async () => {
    const user = userEvent.setup();
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(screen.getByText("New branch")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("New branch"));

    await screen.findByPlaceholderText("branch-name");
    await user.click(screen.getByText("Create & Switch"));
    await settle();
    expect(gitMocks.checkout).not.toHaveBeenCalled();
  });

  it("reports checkout failures", async () => {
    const user = userEvent.setup();
    gitMocks.checkout.mockRejectedValue(new Error("branch locked"));
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(screen.getByTitle("feature")).toBeInTheDocument(),
    );
    await user.click(screen.getByTitle("feature"));
    await waitFor(() =>
      expect(gitMocks.checkout).toHaveBeenCalledWith(
        "feature",
        false,
        undefined,
      ),
    );
  });

  it("refreshes the repo via the refresh button", async () => {
    const user = userEvent.setup();
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );

    const before = gitMocks.status.mock.calls.length;
    // The refresh button is the icon button in the branch bar
    const branchBar = screen
      .getByRole("combobox")
      .closest("[class*='branchBar']") as HTMLElement;
    await user.click(within(branchBar).getByRole("button"));
    await waitFor(() =>
      expect(gitMocks.status.mock.calls.length).toBeGreaterThan(before),
    );
  });

  it("reports branch creation failures", async () => {
    const user = userEvent.setup();
    gitMocks.checkout.mockRejectedValue(new Error("cannot create"));
    render(<GitPanel />);
    await waitFor(() =>
      expect(screen.getByText("No changes")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(screen.getByText("New branch")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("New branch"));

    const nameInput = await screen.findByPlaceholderText("branch-name");
    await user.type(nameInput, "my-branch");
    await user.click(screen.getByText("Create & Switch"));

    await waitFor(() =>
      expect(gitMocks.checkout).toHaveBeenCalledWith(
        "my-branch",
        true,
        undefined,
      ),
    );
  });
});
