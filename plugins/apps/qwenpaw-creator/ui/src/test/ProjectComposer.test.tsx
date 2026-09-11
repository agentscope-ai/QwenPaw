import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectComposer } from "@/components/creator/ProjectComposer";
import { configuredModelConfig } from "@/test/agentFixtures";
import { installMockFetch } from "@/test/mockFetch";
import { useModelConfigStore } from "@/store/modelConfigStore";

function installComposerMockFetch(
  routes: Parameters<typeof installMockFetch>[0],
) {
  return installMockFetch([
    {
      match: "/models/config",
      response: { json: configuredModelConfig },
    },
    ...routes,
  ]);
}

/** The 202 message-accepted payload for the initial goal message. */
const accepted = (creatorSessionId: string, conversationId: string) => ({
  messageSeq: 1,
  eventSeq: 2,
  classification: "mutation_instruction",
  appendState: "appended",
  creatorSessionId,
  conversationId,
});

/** The project-created payload returned by POST /projects. */
const created = (
  projectId: string,
  creatorSessionId: string,
  conversationId: string,
) => ({
  projectId,
  creatorSessionId,
  conversationId,
  projectSnapshotId: `snapshot-${projectId}`,
  header: {},
});

function renderComposer(onClose = vi.fn()) {
  render(
    <MemoryRouter>
      <ProjectComposer open onClose={onClose} />
    </MemoryRouter>,
  );
  return onClose;
}

const fill = (placeholder: RegExp | string, value: string) =>
  fireEvent.change(screen.getByPlaceholderText(placeholder), {
    target: { value },
  });

/** Attaches one local source.mp4 through the non-directory file input. */
const attachFile = () => {
  const fileInput = [
    ...document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  ].find((input) => !input.hasAttribute("webkitdirectory"))!;
  fireEvent.change(fileInput, {
    target: {
      files: [new File(["source"], "source.mp4", { type: "video/mp4" })],
    },
  });
};

describe("ProjectComposer ingest boundary", () => {
  // The model-config snapshot is a module-level singleton; a previous test's
  // fetch must not leak into the next render's synchronous assertions.
  beforeEach(() => {
    useModelConfigStore.setState({ config: null });
  });

  it("keeps only Agent and disabled Loop modes, and hides video format controls for editing", () => {
    renderComposer();
    expect(screen.getByRole("button", { name: "Agent" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Loop" })).toBeDisabled();
    expect(
      screen.getByText("附件将进入资产库「用户上传」分类。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/启动后 Agent 将端到端推进/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "分辨率" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "剪辑" }));
    expect(screen.getByRole("button", { name: "采访" })).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "分辨率" }),
    ).not.toBeInTheDocument();
  });

  it("fails closed when the model configuration response is incomplete", async () => {
    installMockFetch([
      {
        match: "/models/config",
        response: { json: {} },
      },
    ]);
    renderComposer();

    fill(/^例：霸道总裁短剧/, "制作一支短片");

    expect(await screen.findByText("必选模型未配置：")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /启动 Agent/ })).toBeDisabled();
  });

  it("derives a missing project name from the first 20 normalized description characters", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects",
        response: {
          json: created("p-auto-name", "s-auto-name", "c-auto-name"),
        },
      },
    ]);
    renderComposer();
    fill(
      /^例：霸道总裁短剧/,
      "  制作一个   关于雪夜城市与归途的电影感短片，画面温暖克制  ",
    );
    fireEvent.click(screen.getByRole("button", { name: /启动 Agent/ }));

    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/projects"))).toBe(true),
    );
    expect(
      calls.find((call) => call.url.endsWith("/projects"))?.body,
    ).toMatchObject({
      name: "制作一个 关于雪夜城市与归途的电影感短片",
      initialGoal: "制作一个   关于雪夜城市与归途的电影感短片，画面温暖克制",
    });
    expect(
      calls.some((call) => call.url.endsWith("/projects/p-auto-name/messages")),
    ).toBe(false);
  });

  it("navigates immediately and keeps ingest + first message in the background", async () => {
    let acceptMessage: (() => void) | undefined;
    const messageAccepted = new Promise<void>((resolve) => {
      acceptMessage = resolve;
    });
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p-delayed/messages",
        response: {
          json: messageAccepted.then(() => accepted("s-delayed", "c-delayed")),
        },
      },
      {
        match: "/projects/p-delayed/assets",
        response: {
          json: {
            assetId: "a1",
            taskId: "t1",
            status: "SUCCEEDED",
            assetVersionId: "av1",
          },
        },
      },
      {
        match: "/projects",
        response: { json: created("p-delayed", "s-delayed", "c-delayed") },
      },
    ]);
    const onClose = renderComposer();
    fill(/^例：霸道总裁短剧/, "用素材制作短片");
    attachFile();
    fireEvent.click(screen.getByRole("button", { name: /启动 Agent/ }));

    // The composer closes right after the Project exists — the user lands
    // on the project page while attachments upload in the background.
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(
      calls.find((call) => call.url.endsWith("/projects"))?.body,
    ).not.toHaveProperty("initialGoal");

    // The background continuation still sends the durable first message
    // (with the ingested asset refs) after navigation.
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.endsWith("/projects/p-delayed/messages")),
      ).toBe(true),
    );
    acceptMessage?.();
    await waitFor(() => {
      const messageCall = calls.find((call) =>
        call.url.endsWith("/projects/p-delayed/messages"),
      );
      expect(messageCall?.body).toHaveProperty("assetVersionRefs", [
        "asset-version:av1",
      ]);
    });
  });

  it("creates Project, waits for succeeded immutable versions, then sends exactly one initial message", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p1/messages",
        response: { json: accepted("s1", "c1") },
      },
      {
        match: "/projects/p1/assets",
        response: {
          json: {
            assetId: "a1",
            taskId: "t1",
            status: "SUCCEEDED",
            assetVersionId: "av1",
          },
        },
      },
      {
        match: "/projects",
        response: { json: created("p1", "s1", "c1") },
      },
    ]);
    renderComposer();
    fill(/^项目名称（选填/, "新项目");
    fill(/^例：霸道总裁短剧/, "做一个雪夜 SUV 短片");
    attachFile();
    fireEvent.click(screen.getByRole("button", { name: /启动 Agent/ }));
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.endsWith("/projects/p1/messages")),
      ).toBe(true),
    );
    const messageCall = calls.find((call) =>
      call.url.endsWith("/projects/p1/messages"),
    )!;
    expect(messageCall.body).toMatchObject({
      conversationId: "c1",
      content: [{ type: "text", text: "做一个雪夜 SUV 短片" }],
      assetVersionRefs: ["asset-version:av1"],
    });
    expect(
      calls.filter((call) => call.url.endsWith("/projects/p1/messages")),
    ).toHaveLength(1);
  });

  it("submits every successful folder-import version even though item rows have no status field", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p2/asset-imports/import-1",
        response: {
          json: {
            importId: "import-1",
            taskId: "import-1",
            status: "SUCCEEDED",
            progress: 1,
            items: [
              {
                name: "shot.mp4",
                assetVersionId: "av-folder",
              },
            ],
            failures: [],
          },
        },
      },
      {
        match: "/projects/p2/asset-imports",
        response: {
          json: { importId: "import-1", taskId: "import-1", eventSeq: 1 },
        },
      },
      {
        match: "/projects/p2/messages",
        response: { json: accepted("s2", "c2") },
      },
      {
        match: "/projects",
        response: { json: created("p2", "s2", "c2") },
      },
    ]);
    renderComposer();
    fill(/^项目名称（选填/, "文件夹项目");
    fill(/^例：霸道总裁短剧/, "使用文件夹素材创作");
    const file = new File(["video"], "shot.mp4", { type: "video/mp4" });
    Object.defineProperty(file, "webkitRelativePath", {
      value: "scene-a/shot.mp4",
    });
    const folderInput = [
      ...document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
    ].find((input) => input.hasAttribute("webkitdirectory"))!;
    fireEvent.change(folderInput, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /启动 Agent/ }));
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.endsWith("/projects/p2/messages")),
      ).toBe(true),
    );
    expect(
      calls.find((call) => call.url.endsWith("/projects/p2/messages"))?.body,
    ).toMatchObject({
      assetVersionRefs: ["asset-version:av-folder"],
    });
  });

  it("sends the initial message immediately when RUNNING remote ingest pre-publishes an asset version", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p-url-fast/assets",
        method: "POST",
        response: {
          json: {
            assetId: "a-url-fast",
            taskId: "task-url-fast",
            status: "RUNNING",
            assetVersionId: "av-url-prepublished",
          },
        },
      },
      {
        match: "/projects/p-url-fast/messages",
        method: "POST",
        response: { json: accepted("s-url-fast", "c-url-fast") },
      },
      {
        match: "/projects",
        method: "POST",
        response: { json: created("p-url-fast", "s-url-fast", "c-url-fast") },
      },
    ]);
    renderComposer();
    fill(/^例：霸道总裁短剧/, "立即使用远程视频创作");
    fill("粘贴 URL 后回车", "https://cdn.example.com/large-fast.mp4");
    fireEvent.click(screen.getByRole("button", { name: /启动 Agent/ }));

    await waitFor(() =>
      expect(
        calls.some((call) =>
          call.url.endsWith("/projects/p-url-fast/messages"),
        ),
      ).toBe(true),
    );
    expect(
      calls.find((call) => call.url.endsWith("/projects/p-url-fast/messages"))
        ?.body,
    ).toMatchObject({
      assetVersionRefs: ["asset-version:av-url-prepublished"],
      content: [
        { type: "text", text: "立即使用远程视频创作" },
        {
          type: "video_url",
          video_url: { url: "https://cdn.example.com/large-fast.mp4" },
        },
      ],
    });
  });

  it("does not block Agent startup on a remote cache task that may later fail", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p-failed/assets",
        method: "POST",
        response: {
          json: {
            assetId: "a-failed",
            taskId: "task-failed",
            status: "RUNNING",
            progress: 0,
            assetVersionId: null,
          },
        },
      },
      {
        match: "/projects/p-failed/messages",
        method: "POST",
        response: { json: accepted("s-failed", "c-failed") },
      },
      {
        match: "/projects",
        method: "POST",
        response: { json: created("p-failed", "s-failed", "c-failed") },
      },
    ]);
    renderComposer();
    fill(/^例：霸道总裁短剧/, "使用远程视频创作");
    fill("粘贴 URL 后回车", "https://cdn.example.com/large.mp4");
    fireEvent.click(screen.getByRole("button", { name: /启动 Agent/ }));

    await waitFor(() =>
      expect(
        calls.some((call) => call.url.endsWith("/projects/p-failed/messages")),
      ).toBe(true),
    );
    expect(calls.some((call) => call.url.includes("/tasks/task-failed"))).toBe(
      false,
    );
  });
});
