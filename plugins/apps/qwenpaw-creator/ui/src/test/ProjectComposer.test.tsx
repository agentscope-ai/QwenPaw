import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectComposer } from "@/components/creator/ProjectComposer";
import type { ModelConfigData } from "@/contracts/creator/models";
import { installMockFetch } from "@/test/mockFetch";
import { useModelConfigStore } from "@/store/modelConfigStore";

const configuredModelConfig: ModelConfigData = {
  llm: {
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://example.test/v1",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    multimodal: true,
  },
  vlm: {
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://example.test/v1",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    use_llm: true,
    multimodal: true,
  },
  grounding: {
    enabled: true,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    reuse_llm: true,
    validation_source: "llm",
    tavily_api_key: "",
    serper_api_key: "",
    native_search_enabled: true,
    search_provider: "dashscope_qwen",
    search_reuse_llm: true,
    search_model_name: "",
    search_api_key: "",
    search_base_url: "",
    search_protocol: "DashScope（百炼）",
  },
  asr: {
    enabled: false,
    model_name: "fun-asr",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope Fun-ASR",
    custom_protocol: "",
    provider: "fun-asr",
    language: "",
    reuse_llm_key: true,
  },
  tts: {
    enabled: false,
    model_name: "qwen3-tts-flash",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    voice: "",
    reuse_llm_key: true,
    vc_model_name: "",
  },
  s2v: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    detect_model_name: "",
    reuse_llm_key: true,
  },
  embedding: {
    enabled: false,
    model_name: "qwen3-vl-embedding",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    reuse_vlm_key: true,
  },
  image: {
    enabled: true,
    model_name: "qwen-image",
    api_key: "",
    base_url: "https://example.test/image",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    translate_model: "",
    reuse_llm_key: true,
  },
  video: {
    enabled: true,
    model_name: "wan2.7-r2v",
    api_key: "",
    base_url: "https://example.test/video",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    reuse_llm_key: true,
  },
  oss: {
    enabled: false,
    access_key_id: "",
    access_key_secret: "",
    endpoint: "",
    bucket: "",
    public_base_url: "",
    policy_api_key: "",
  },
  executionAuthorization: { mode: "allow_all" },
  creationCheckpoints: { mode: "skip" },
  mediaReview: { mode: "required" },
  selfReview: {
    sync_enabled: false,
    media_enabled: false,
    render_enabled: false,
  },
};

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

describe("ProjectComposer ingest boundary", () => {
  // The model-config snapshot is a module-level singleton; a previous test's
  // fetch must not leak into the next render's synchronous assertions.
  beforeEach(() => {
    useModelConfigStore.setState({ config: null });
  });

  it("keeps only Agent and disabled Loop modes, and hides video format controls for editing", () => {
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: "Agent" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Loop" })).toBeDisabled();
    expect(screen.queryByText("Spec")).not.toBeInTheDocument();
    expect(screen.queryByText("Goal")).not.toBeInTheDocument();
    const resolutionSelect = screen.getByRole("combobox", { name: "分辨率" });
    const aspectRatioSelect = screen.getByRole("combobox", { name: "宽高比" });
    expect(resolutionSelect).toBeInTheDocument();
    expect(aspectRatioSelect).toBeInTheDocument();
    expect(resolutionSelect.parentElement).toHaveClass(
      "!mr-0",
      "!w-full",
      "!-translate-x-0.5",
      "!justify-center",
      "!text-center",
    );
    expect(aspectRatioSelect.parentElement).toHaveClass(
      "!mr-0",
      "!w-full",
      "!-translate-x-0.5",
      "!justify-center",
      "!text-center",
    );
    expect(resolutionSelect.parentElement?.nextElementSibling).toHaveClass(
      "!absolute",
      "!right-2",
    );
    expect(aspectRatioSelect.parentElement?.nextElementSibling).toHaveClass(
      "!absolute",
      "!right-2",
    );

    fireEvent.click(screen.getByRole("button", { name: "剪辑" }));
    expect(
      screen.queryByRole("combobox", { name: "分辨率" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "宽高比" }),
    ).not.toBeInTheDocument();
  });

  it("fails closed when the model configuration response is incomplete", async () => {
    installMockFetch([
      {
        match: "/models/config",
        response: { json: {} },
      },
    ]);
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText(/^例：霸道总裁短剧/), {
      target: { value: "制作一支短片" },
    });

    expect(await screen.findByText("必选模型未配置：")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /启动 Agent/ })).toBeDisabled();
  });

  it("derives a missing project name from the first 20 normalized description characters", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p-auto-name/messages",
        response: {
          json: {
            messageSeq: 1,
            eventSeq: 2,
            classification: "mutation_instruction",
            appendState: "appended",
            creatorSessionId: "s-auto-name",
            conversationId: "c-auto-name",
          },
        },
      },
      {
        match: "/projects",
        response: {
          json: {
            projectId: "p-auto-name",
            creatorSessionId: "s-auto-name",
            conversationId: "c-auto-name",
            projectSnapshotId: "snapshot-auto-name",
            header: {},
          },
        },
      },
    ]);
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText(/^例：霸道总裁短剧/), {
      target: {
        value: "  制作一个   关于雪夜城市与归途的电影感短片，画面温暖克制  ",
      },
    });
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
    const onClose = vi.fn();
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p-delayed/messages",
        response: {
          json: messageAccepted.then(() => ({
            messageSeq: 1,
            eventSeq: 2,
            classification: "mutation_instruction",
            appendState: "appended",
            creatorSessionId: "s-delayed",
            conversationId: "c-delayed",
          })),
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
        response: {
          json: {
            projectId: "p-delayed",
            creatorSessionId: "s-delayed",
            conversationId: "c-delayed",
            projectSnapshotId: "snapshot-delayed",
            header: {},
          },
        },
      },
    ]);
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={onClose} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText(/^例：霸道总裁短剧/), {
      target: { value: "用素材制作短片" },
    });
    const fileInput = [
      ...document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
    ].find((input) => !input.hasAttribute("webkitdirectory"))!;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["source"], "source.mp4", { type: "video/mp4" })],
      },
    });
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

  it("removes the obsolete end-to-end confirmation copy", () => {
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(
      screen.getByText("附件将进入资产库「用户上传」分类。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/启动后 Agent 将端到端推进/),
    ).not.toBeInTheDocument();
  });

  it("keeps the latest origin/main interview content-type option in the unchanged Composer shell", () => {
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "剪辑" }));
    expect(screen.getByRole("button", { name: "采访" })).toBeInTheDocument();
  });

  it("creates Project, waits for succeeded immutable versions, then sends exactly one initial message", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p1/messages",
        response: {
          json: {
            messageSeq: 1,
            eventSeq: 2,
            classification: "mutation_instruction",
            appendState: "appended",
            creatorSessionId: "s1",
            conversationId: "c1",
          },
        },
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
        response: {
          json: {
            projectId: "p1",
            creatorSessionId: "s1",
            conversationId: "c1",
            projectSnapshotId: "snapshot-1",
            header: {},
          },
        },
      },
    ]);
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText(/^项目名称（选填/), {
      target: { value: "新项目" },
    });
    fireEvent.change(screen.getByPlaceholderText(/^例：霸道总裁短剧/), {
      target: { value: "做一个雪夜 SUV 短片" },
    });
    const fileInput = [
      ...document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
    ].find((input) => !input.hasAttribute("webkitdirectory"))!;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["source"], "source.mp4", { type: "video/mp4" })],
      },
    });
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
    expect(
      calls.some((call) => /run-all|production|goal/i.test(call.url)),
    ).toBe(false);
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
                checksum: "sha",
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
        response: {
          json: {
            messageSeq: 1,
            eventSeq: 2,
            classification: "mutation_instruction",
            appendState: "appended",
            creatorSessionId: "s2",
            conversationId: "c2",
          },
        },
      },
      {
        match: "/projects",
        response: {
          json: {
            projectId: "p2",
            creatorSessionId: "s2",
            conversationId: "c2",
            projectSnapshotId: "snapshot-2",
            header: {},
          },
        },
      },
    ]);
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText(/^项目名称（选填/), {
      target: { value: "文件夹项目" },
    });
    fireEvent.change(screen.getByPlaceholderText(/^例：霸道总裁短剧/), {
      target: { value: "使用文件夹素材创作" },
    });
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
            progress: 0,
            assetVersionId: "av-url-prepublished",
          },
        },
      },
      {
        match: "/projects/p-url-fast/messages",
        method: "POST",
        response: {
          json: {
            messageSeq: 1,
            eventSeq: 2,
            classification: "mutation_instruction",
            appendState: "appended",
            creatorSessionId: "s-url-fast",
            conversationId: "c-url-fast",
          },
        },
      },
      {
        match: "/projects",
        method: "POST",
        response: {
          json: {
            projectId: "p-url-fast",
            creatorSessionId: "s-url-fast",
            conversationId: "c-url-fast",
            projectSnapshotId: "snapshot-url-fast",
            header: {},
          },
        },
      },
    ]);
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText(/^项目名称（选填/), {
      target: { value: "远程视频快速启动项目" },
    });
    fireEvent.change(screen.getByPlaceholderText(/^例：霸道总裁短剧/), {
      target: { value: "立即使用远程视频创作" },
    });
    fireEvent.change(screen.getByPlaceholderText("粘贴 URL 后回车"), {
      target: { value: "https://cdn.example.com/large-fast.mp4" },
    });
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
    expect(
      calls.some(
        (call) =>
          call.method === "GET" && call.url.includes("/tasks/task-url-fast"),
      ),
    ).toBe(false);
  });

  it("starts the Agent with the indexed remote version without waiting for local caching", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p-url/tasks/task-url",
        method: "GET",
        response: {
          json: {
            id: "task-url",
            projectId: "p-url",
            transactionId: null,
            specialistRunId: null,
            kind: "asset_ingest",
            targetRef: "asset:a-url",
            status: "SUCCEEDED",
            progress: 1,
            resultRefs: ["asset-version:av-url"],
            result: {},
            error: null,
          },
        },
      },
      {
        match: "/projects/p-url/assets",
        method: "POST",
        response: {
          json: {
            assetId: "a-url",
            taskId: "task-url",
            status: "RUNNING",
            progress: 0,
            assetVersionId: "av-url",
          },
        },
      },
      {
        match: "/projects/p-url/messages",
        method: "POST",
        response: {
          json: {
            messageSeq: 1,
            eventSeq: 2,
            classification: "mutation_instruction",
            appendState: "appended",
            creatorSessionId: "s-url",
            conversationId: "c-url",
          },
        },
      },
      {
        match: "/projects",
        method: "POST",
        response: {
          json: {
            projectId: "p-url",
            creatorSessionId: "s-url",
            conversationId: "c-url",
            projectSnapshotId: "snapshot-url",
            header: {},
          },
        },
      },
    ]);
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText(/^项目名称（选填/), {
      target: { value: "远程视频项目" },
    });
    fireEvent.change(screen.getByPlaceholderText(/^例：霸道总裁短剧/), {
      target: { value: "使用远程视频创作" },
    });
    fireEvent.change(screen.getByPlaceholderText("粘贴 URL 后回车"), {
      target: { value: "https://cdn.example.com/large.mp4" },
    });
    fireEvent.click(screen.getByRole("button", { name: /启动 Agent/ }));

    await waitFor(() =>
      expect(
        calls.some((call) => call.url.endsWith("/projects/p-url/messages")),
      ).toBe(true),
    );
    expect(
      calls.find((call) => call.url.endsWith("/projects/p-url/messages"))?.body,
    ).toMatchObject({
      assetVersionRefs: ["asset-version:av-url"],
      content: [
        { type: "text", text: "使用远程视频创作" },
        {
          type: "video_url",
          video_url: { url: "https://cdn.example.com/large.mp4" },
        },
      ],
    });
    expect(
      calls.some(
        (call) =>
          call.method === "GET" &&
          call.url.includes("/projects/p-url/tasks/task-url"),
      ),
    ).toBe(false);
  });

  it("does not block Agent startup on a remote cache task that may later fail", async () => {
    const { calls } = installComposerMockFetch([
      {
        match: "/projects/p-failed/tasks/task-failed",
        method: "GET",
        response: {
          json: {
            id: "task-failed",
            projectId: "p-failed",
            transactionId: null,
            specialistRunId: null,
            kind: "asset_ingest",
            targetRef: "asset:a-failed",
            status: "FAILED",
            progress: 0.4,
            resultRefs: [],
            result: null,
            error: {
              kind: "ASSET_INGEST_FAILED",
              items: [{ name: "large.mp4", error: "远程素材下载连接超时" }],
            },
          },
        },
      },
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
        response: {
          json: {
            messageSeq: 1,
            eventSeq: 2,
            classification: "mutation_instruction",
            appendState: "appended",
            creatorSessionId: "s-failed",
            conversationId: "c-failed",
          },
        },
      },
      {
        match: "/projects",
        method: "POST",
        response: {
          json: {
            projectId: "p-failed",
            creatorSessionId: "s-failed",
            conversationId: "c-failed",
            projectSnapshotId: "snapshot-failed",
            header: {},
          },
        },
      },
    ]);
    render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByPlaceholderText(/^项目名称（选填/), {
      target: { value: "失败远程视频项目" },
    });
    fireEvent.change(screen.getByPlaceholderText(/^例：霸道总裁短剧/), {
      target: { value: "使用远程视频创作" },
    });
    fireEvent.change(screen.getByPlaceholderText("粘贴 URL 后回车"), {
      target: { value: "https://cdn.example.com/large.mp4" },
    });
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
