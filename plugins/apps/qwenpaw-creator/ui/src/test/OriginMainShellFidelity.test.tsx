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
  it("keeps the origin Home card hierarchy, copy, classes, and actions", async () => {
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
    expect(await screen.findByText("雪夜短片")).toBeInTheDocument();
    for (const label of [
      "视频场景 短剧",
      "内容类型 采访",
      "画面长宽比 16:9",
      "图像分辨率 720P",
    ]) {
      expect(screen.getByText(label)).toHaveClass(
        "badge",
        "border",
        "text-[var(--color-text-secondary)]",
      );
    }
    expect(screen.getByRole("button", { name: "新建项目" })).toHaveClass(
      "btn-primary",
      "cursor-pointer",
    );
    expect(screen.getByRole("button", { name: "打开" })).toHaveClass(
      "btn-primary",
      "flex-1",
      "cursor-pointer",
    );
    expect(screen.getByRole("button", { name: "删除 雪夜短片" })).toHaveClass(
      "btn-primary",
      "flex-1",
      "cursor-pointer",
    );
    expect(container.querySelector("header")).toHaveClass(
      "border-b",
      "bg-[var(--color-bg-primary)]",
    );
    expect(screen.getByText("一段项目说明").parentElement).toHaveClass(
      "min-h-[52px]",
      "bg-[rgba(43,18,0,0.02)]",
    );
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
