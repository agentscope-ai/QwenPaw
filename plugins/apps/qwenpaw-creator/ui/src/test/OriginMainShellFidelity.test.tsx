import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import HomePage from "@/pages/HomePage";
import ModelConfigModal from "@/components/creator/ModelConfigModal";
import { ProjectComposer } from "@/components/creator/ProjectComposer";
import { installMockFetch } from "@/test/mockFetch";

const modelConfig = {
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
  image: {
    enabled: true,
    model_name: "qwen-image",
    api_key: "",
    base_url: "https://example.test/image",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
  },
  video: {
    enabled: true,
    model_name: "wan2.7-r2v",
    api_key: "",
    base_url: "https://example.test/video",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
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
};

describe("origin/main visible shell fidelity", () => {
  it("keeps the redesigned Home project cards, copy, classes, and actions", async () => {
    installMockFetch([
      { match: "/models/config", response: { json: modelConfig } },
      {
        match: "/projects",
        response: {
          json: {
            items: [
              {
                projectId: "p1",
                name: "雪夜短片",
                description: "一段项目说明",
                scenario: "short_drama",
                contentType: "interview",
                aspectRatio: "16:9",
                resolution: "720P",
                createdAt: "2026-07-01T00:00:00Z",
                updatedAt: "2026-07-02T00:00:00Z",
              },
            ],
            limit: 100,
            offset: 0,
          },
        },
      },
    ]);
    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    // The project grid lives under the second tab: text-only cards with
    // name, description, meta row and update time, actions on hover.
    fireEvent.click(screen.getByRole("tab", { name: "我的项目" }));
    expect(await screen.findByText("雪夜短片")).toBeInTheDocument();
    // Content type is editing-only, so a short drama never shows it.
    expect(screen.getByText("短剧")).toBeInTheDocument();
    expect(screen.queryByText("类型：")).not.toBeInTheDocument();
    expect(screen.queryByText("采访")).not.toBeInTheDocument();
    expect(screen.getByText("16:9")).toBeInTheDocument();
    expect(screen.getByText("720P")).toBeInTheDocument();
    expect(screen.getByText("一段项目说明")).toHaveClass(
      "line-clamp-2",
      "text-[var(--color-text-tertiary)]",
    );
    // No preview chip without a rendered final cut.
    expect(
      screen.queryByRole("button", { name: "预览 雪夜短片 成片" }),
    ).not.toBeInTheDocument();
    // Creation happens through the floating pill instead of a button.
    expect(
      screen.queryByRole("button", { name: "新建项目" }),
    ).not.toBeInTheDocument();
    const floatingEntry = screen
      .getAllByRole("button", { name: "开始创作" })
      .find((button) => button.className.includes("fixed"));
    expect(floatingEntry).toBeDefined();
    expect(floatingEntry).toHaveClass("bg-[#FF9D4D]", "rounded-full");
    // Export moved to the plan page; the card keeps a muted always-visible
    // delete icon instead of a hover dropdown.
    expect(
      screen.queryByRole("button", { name: "雪夜短片 更多操作" }),
    ).not.toBeInTheDocument();
    const deleteButton = screen.getByRole("button", { name: "删除 雪夜短片" });
    expect(deleteButton).toHaveClass(
      "text-[var(--color-text-tertiary)]",
      "hover:text-[var(--color-danger)]",
    );
    expect(container.querySelector("header")).toHaveClass(
      "border-b",
      "bg-[var(--color-bg-primary)]",
    );
    // The floating pill returns to the hero composer view.
    fireEvent.click(floatingEntry!);
    expect(screen.getByRole("tab", { name: "开始创作" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows the content type and the final-cut preview for editing projects", async () => {
    installMockFetch([
      { match: "/models/config", response: { json: modelConfig } },
      {
        match: "/projects",
        response: {
          json: {
            items: [
              {
                projectId: "p2",
                name: "采访粗切",
                description: "一段项目说明",
                scenario: "video_edit",
                contentType: "interview",
                aspectRatio: "16:9",
                resolution: "720P",
                coverVersionId: "ver-cover",
                coverVersionSource: "artifact",
                finalVideoVersionId: "ver-final",
                createdAt: "2026-07-01T00:00:00Z",
                updatedAt: "2026-07-02T00:00:00Z",
              },
            ],
            limit: 100,
            offset: 0,
          },
        },
      },
    ]);
    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("tab", { name: "我的项目" }));
    expect(await screen.findByText("采访粗切")).toBeInTheDocument();
    // Editing is the one scenario that carries a content type on the meta row.
    expect(screen.getByText("类型：")).toHaveClass(
      "font-medium",
      "text-[var(--color-text-secondary)]",
    );
    expect(screen.getByText("采访")).toHaveClass(
      "text-[var(--color-text-tertiary)]",
    );
    // A final cut enables the preview chip playing in a modal video.
    const previewButton = screen.getByRole("button", {
      name: "预览 采访粗切 成片",
    });
    fireEvent.click(previewButton);
    const video = container.ownerDocument.querySelector("video");
    expect(video).not.toBeNull();
    expect(video!.getAttribute("src")).toContain("/media/artifacts/ver-final");
  });

  it("keeps the origin Composer hierarchy, copy, controls, and 720px modal", () => {
    const { container } = render(
      <MemoryRouter>
        <ProjectComposer open onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(
      screen.getByText("把目标、素材和限制交给 Agent"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "资料输入是一次性的启动动作。进入项目后，它们会变成可管理、可引用、可追踪的项目资产。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/^项目名称（选填/)).toHaveClass(
      "!rounded-none",
      "!border-x-0",
      "!bg-transparent",
    );
    expect(screen.getByPlaceholderText(/^目标描述：/)).toHaveClass(
      "!border-none",
      "!p-4",
    );
    expect(
      screen.getByRole("button", { name: "添加文件" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "选择文件夹" }),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("粘贴 URL 后回车")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /启动 Agent/ })).toBeDisabled();
    expect(container.ownerDocument.querySelector(".ant-modal")).toHaveStyle({
      width: "720px",
    });
  });

  it("keeps the origin model modal with direct single-file values", async () => {
    installMockFetch([
      { match: "/models/config", response: { json: modelConfig } },
    ]);
    const { container } = render(<ModelConfigModal open onClose={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getAllByText("qwen3.7-plus").length).toBeGreaterThan(0),
    );
    expect(screen.getByText("模型配置")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /LLM/ })).toHaveClass(
      "segmented-tab",
      "active",
    );
    expect(
      screen.getByRole("button", { name: /保存配置/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /取\s*消/ })).toBeInTheDocument();
    const authorizationToggle = screen.getByRole("checkbox", {
      name: "高花费模型执行授权",
    });
    expect(authorizationToggle).not.toBeChecked();
    expect(
      screen.getByText("开启后，高花费模型的执行需要确认。"),
    ).toBeInTheDocument();
    fireEvent.click(authorizationToggle);
    expect(authorizationToggle).toBeChecked();
    expect(
      screen.getByText("开启后，高花费模型的执行需要确认。"),
    ).toBeInTheDocument();
    const keyInput = screen.getByPlaceholderText("sk-...");
    expect(keyInput).toHaveValue("saved-secret");
    expect(keyInput).toHaveAttribute("type", "password");
    expect(
      screen.queryByRole("button", { name: "显示" }),
    ).not.toBeInTheDocument();
    fireEvent.focus(keyInput);
    expect(keyInput).toHaveValue("saved-secret");
    expect(container.ownerDocument.querySelector(".ant-modal")).toHaveStyle({
      width: "800px",
    });
  });
});
