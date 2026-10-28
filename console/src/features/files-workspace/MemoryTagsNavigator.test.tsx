import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MemoryTagsNavigator from "./MemoryTagsNavigator";
import { agentsApi } from "../../api/modules/agents";
import type { MemoryTagFilePage } from "../../api/types/agents";

vi.mock("../../api/modules/agents", () => ({
  agentsApi: { getMemoryTags: vi.fn(), getMemoryTagFiles: vi.fn() },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { count?: number }) =>
      values?.count === undefined ? key : `${key}:${values.count}`,
    i18n: { language: "en" },
  }),
}));

const files: MemoryTagFilePage = {
  tag: "赵六",
  total_files: 1,
  page: 1,
  page_size: 50,
  items: [
    {
      path: "resources/orion.md",
      source: "workspace",
      relative_path: "resources/orion.md",
      name: "Orion owner",
      description: "Project owner",
      modified_at: 1700000000,
      memory_tags: ["赵六", "orion"],
    },
  ],
};
const props = () => ({
  agentId: "bot",
  tag: null as string | null,
  selectedPath: "",
  revision: 0,
  memoryConfig: { daily_dir: "memory", digest_dir: "digest" },
  onSelectTag: vi.fn(),
  onOpenFile: vi.fn(),
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(agentsApi.getMemoryTags).mockResolvedValue({
    items: [{ tag: "赵六", file_count: 7 }],
    total_tags: 1,
    page: 1,
    page_size: 50,
  });
  vi.mocked(agentsApi.getMemoryTagFiles).mockResolvedValue(files);
});

describe("MemoryTagsNavigator", () => {
  it("shows file counts and lets a user choose a tag", async () => {
    const callbacks = props();
    render(<MemoryTagsNavigator {...callbacks} />);
    fireEvent.click(await screen.findByRole("button", { name: /赵六.*7/ }));
    expect(callbacks.onSelectTag).toHaveBeenCalledWith("赵六");
    expect(agentsApi.getMemoryTagFiles).not.toHaveBeenCalled();
  });

  it("opens the exact agent workspace file, including resources outside the graph", async () => {
    const callbacks = { ...props(), tag: "赵六" };
    render(<MemoryTagsNavigator {...callbacks} />);
    fireEvent.click(await screen.findByRole("button", { name: /Orion owner/ }));
    expect(callbacks.onOpenFile).toHaveBeenCalledWith({
      source: "workspace",
      root: "workspace",
      path: "resources/orion.md",
    });
    expect(screen.getByText("files.memoryTagFilesCount:1")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "files.memoryTagsAll" }),
    );
    expect(callbacks.onSelectTag).toHaveBeenCalledWith(null);
  });

  it("paginates files without falling back to semantic search", async () => {
    vi.mocked(agentsApi.getMemoryTagFiles).mockResolvedValue({
      ...files,
      total_files: 75,
    });
    render(<MemoryTagsNavigator {...props()} tag="赵六" />);
    await screen.findByRole("button", { name: /Orion owner/ });
    fireEvent.click(
      screen.getByRole("button", { name: "files.memoryTagsNext" }),
    );
    await waitFor(() =>
      expect(agentsApi.getMemoryTagFiles).toHaveBeenLastCalledWith(
        "bot",
        "赵六",
        2,
        expect.any(AbortSignal),
      ),
    );
  });

  it.each([undefined, "project", "project:/other", "workspace"] as const)(
    "matches workspace results only for the agent root, selected root: %s",
    async (selectedRoot) => {
      render(
        <MemoryTagsNavigator
          {...props()}
          tag="赵六"
          selectedSource="workspace"
          selectedRoot={selectedRoot}
          selectedPath="resources/orion.md"
        />,
      );
      const result = await screen.findByRole("button", { name: /Orion owner/ });
      expect(result.getAttribute("aria-current")).toBe(
        selectedRoot === "workspace" ? "true" : null,
      );
    },
  );

  it.each(["daily", "digest"] as const)(
    "recognizes a %s result opened through its full workspace path",
    async (source) => {
      const path = `custom-${source}/note.md`;
      vi.mocked(agentsApi.getMemoryTagFiles).mockResolvedValue({
        ...files,
        items: [{ ...files.items[0], source, path, relative_path: "note.md" }],
      });
      render(
        <MemoryTagsNavigator
          {...props()}
          tag="赵六"
          selectedSource="workspace"
          selectedRoot="workspace"
          selectedPath={path}
        />,
      );
      expect(
        await screen.findByRole("button", { name: /Orion owner/ }),
      ).toHaveAttribute("aria-current", "true");
    },
  );

  it("highlights a daily result reused from a legacy memory tab", async () => {
    vi.mocked(agentsApi.getMemoryTagFiles).mockResolvedValue({
      ...files,
      items: [
        {
          ...files.items[0],
          source: "daily",
          path: "memory/note.md",
          relative_path: "note.md",
        },
      ],
    });
    render(
      <MemoryTagsNavigator
        {...props()}
        tag="赵六"
        selectedSource="memory"
        selectedPath="note.md"
      />,
    );
    expect(
      await screen.findByRole("button", { name: /Orion owner/ }),
    ).toHaveAttribute("aria-current", "true");
  });

  it.each([
    { daily_dir: "memory", digest_dir: "digest", prefix: "digest" },
    {
      daily_dir: "custom/daily",
      digest_dir: "custom/knowledge",
      prefix: "knowledge",
    },
  ])(
    "highlights the actual legacy digest file rather than its daily namesake: %j",
    async (memoryConfig) => {
      vi.mocked(agentsApi.getMemoryTagFiles).mockResolvedValue({
        ...files,
        total_files: 2,
        items: [
          {
            ...files.items[0],
            name: "Digest file",
            source: "digest",
            path: `${memoryConfig.digest_dir}/note.md`,
            relative_path: "note.md",
          },
          {
            ...files.items[0],
            name: "Daily namesake",
            source: "daily",
            path: `${memoryConfig.daily_dir}/${memoryConfig.prefix}/note.md`,
            relative_path: `${memoryConfig.prefix}/note.md`,
          },
        ],
      });
      render(
        <MemoryTagsNavigator
          {...props()}
          memoryConfig={memoryConfig}
          tag="赵六"
          selectedSource="memory"
          selectedPath={`${memoryConfig.prefix}/note.md`}
        />,
      );
      expect(
        await screen.findByRole("button", { name: /Digest file/ }),
      ).toHaveAttribute("aria-current", "true");
      expect(
        screen.getByRole("button", { name: /Daily namesake/ }),
      ).not.toHaveAttribute("aria-current");
    },
  );

  it("reports an unavailable index and retries instead of showing zero files", async () => {
    vi.mocked(agentsApi.getMemoryTagFiles).mockRejectedValueOnce(
      new Error("unavailable"),
    );
    render(<MemoryTagsNavigator {...props()} tag="赵六" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "files.memoryTagsLoadFailed",
    );
    expect(
      screen.queryByText("files.memoryTagFilesEmpty"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(
      await screen.findByRole("button", { name: /Orion owner/ }),
    ).toBeInTheDocument();
  });

  it("discards a late response after the selected agent or tag changes", async () => {
    let finishOld!: (value: MemoryTagFilePage) => void;
    vi.mocked(agentsApi.getMemoryTagFiles).mockReturnValueOnce(
      new Promise((resolve) => {
        finishOld = resolve;
      }),
    );
    const { rerender } = render(
      <MemoryTagsNavigator key="old" {...props()} tag="old" />,
    );
    rerender(
      <MemoryTagsNavigator key="new" {...props()} agentId="other" tag="赵六" />,
    );
    await screen.findByRole("button", { name: /Orion owner/ });
    await act(async () =>
      finishOld({
        ...files,
        items: [{ ...files.items[0], name: "Stale result" }],
      }),
    );
    expect(screen.queryByText("Stale result")).not.toBeInTheDocument();
  });
});
