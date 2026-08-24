import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import HomePage from "@/pages/HomePage";
import ModelConfigModal from "@/components/creator/ModelConfigModal";
import { ProjectComposer } from "@/components/creator/ProjectComposer";
import { installMockFetch } from "@/test/mockFetch";
import { configuredModelConfig } from "@/test/agentFixtures";

// Same fully-configured snapshot, but with hands-off media review so the
// execution-mode cards land on the YOLO stop.
const modelConfig = {
  ...configuredModelConfig,
  mediaReview: { mode: "auto_approve" as const },
};

const projectsPage = (item: Record<string, unknown>) => ({
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
      ...item,
    },
  ],
  limit: 100,
  offset: 0,
});

describe("origin/main visible shell fidelity", () => {
  it("keeps the redesigned Home project cards, copy, classes, and actions", async () => {
    installMockFetch([
      { match: "/models/config", response: { json: modelConfig } },
      { match: "/projects", response: { json: projectsPage({}) } },
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
    // The content type row was removed from cards; only the meta row shows.
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
          json: projectsPage({
            projectId: "p2",
            name: "采访粗切",
            scenario: "video_edit",
            coverVersionId: "ver-cover",
            coverVersionSource: "artifact",
            finalVideoVersionId: "ver-final",
          }),
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
    // The meta row keeps scenario, ratio and resolution; content type no
    // longer appears on cards.
    expect(screen.getByText("剪辑")).toBeInTheDocument();
    expect(screen.queryByText("类型：")).not.toBeInTheDocument();
    expect(screen.queryByText("采访")).not.toBeInTheDocument();
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
    expect(screen.getByPlaceholderText(/^例：霸道总裁短剧/)).toHaveClass(
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
      {
        match: "/models/config/permission-mode",
        response: { json: { ok: true } },
      },
    ]);
    const { container } = render(<ModelConfigModal open onClose={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getAllByText("qwen3.7-plus").length).toBeGreaterThan(0),
    );
    expect(screen.getByText("模型配置")).toBeInTheDocument();
    // The settings nav lands on the language pane with the LLM card open.
    expect(screen.getByRole("button", { name: /语言与理解/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(
      screen.getByRole("button", { name: /保存配置/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /关闭/ })).toBeInTheDocument();
    // allow_all + skip + auto_approve maps to the top (YOLO) stop of the
    // execution-mode cards.
    fireEvent.click(screen.getByRole("button", { name: /执行模式/ }));
    expect(screen.getByRole("radio", { name: /YOLO/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByText(/完全无人值守/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /全程确认/ }));
    expect(screen.getByRole("radio", { name: /全程确认/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByText(/逐次授权/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /语言与理解/ }));
    const keyInput = screen.getByPlaceholderText("sk-...");
    expect(keyInput).toHaveValue("saved-secret");
    expect(keyInput).toHaveAttribute("type", "password");
    expect(
      screen.queryByRole("button", { name: "显示" }),
    ).not.toBeInTheDocument();
    fireEvent.focus(keyInput);
    expect(keyInput).toHaveValue("saved-secret");
    expect(container.ownerDocument.querySelector(".ant-modal")).toHaveStyle({
      width: "1000px",
    });
  });
});
