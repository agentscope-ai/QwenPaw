// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "files.artifactCreated": "已新增",
        "files.artifactModified": "已修改",
        "files.artifactsCollapse": "收起",
        "files.artifactsExpand": "展开更多",
      })[key] ?? key,
  }),
}));

import ResponseArtifactList from "./ResponseArtifactList";

function successfulFileIo(path: string, name = "write_file") {
  return [
    {
      id: `call-${path}`,
      type: "tool_call",
      name,
      params: { file_path: path },
    },
    {
      id: `result-${path}`,
      type: "tool_call_output",
      call_id: `call-${path}`,
      status: "completed",
    },
  ];
}

describe("ResponseArtifactList", () => {
  it("renders each file as a flat preview entry", () => {
    render(
      <ResponseArtifactList
        output={[
          ...successfulFileIo("snack-shop/public/main.js"),
          ...successfulFileIo("snack-shop/package.json"),
        ]}
      />,
    );

    expect(screen.getByText("main.js")).toBeInTheDocument();
    expect(screen.getByText("snack-shop/public/main.js")).toBeInTheDocument();
    expect(screen.getByText("package.json")).toBeInTheDocument();
    expect(screen.getAllByText("已新增")).toHaveLength(2);
  });

  it("marks edit and append operations as modified", () => {
    render(
      <ResponseArtifactList
        output={[
          ...successfulFileIo("notes.md", "edit_file"),
          ...successfulFileIo("journal.md", "append_file"),
        ]}
      />,
    );

    expect(screen.getAllByText("已修改")).toHaveLength(2);
  });

  it("collapses files beyond two rows and allows expanding them", () => {
    render(
      <ResponseArtifactList
        output={Array.from({ length: 3 }, (_, index) =>
          successfulFileIo(`file-${index}.md`),
        ).flat()}
      />,
    );

    const toggle = screen.getByRole("button", { name: /展开更多/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("收起")).toBeInTheDocument();
  });

  it("shows two columns when the response has enough width", () => {
    const rect = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ width: 700 } as DOMRect);
    render(
      <ResponseArtifactList
        output={Array.from({ length: 5 }, (_, index) =>
          successfulFileIo(`wide-${index}.md`),
        ).flat()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "wide-0.md wide-0.md" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /展开更多/ }),
    ).toBeInTheDocument();
    rect.mockRestore();
  });

  it("opens the existing file preview when clicked", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);
    render(
      <ResponseArtifactList output={successfulFileIo("reports/final.md")} />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "final.md reports/final.md",
      }),
    );

    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail.target).toEqual({
      source: "workspace",
      path: "reports/final.md",
      root: "project",
    });
    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("renders nothing when the response has no successful file IO", () => {
    const { container } = render(
      <ResponseArtifactList
        output={[{ type: "message", content: [{ text: "hello" }] }]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("reads the normalized ResponseCard content-data shape", () => {
    render(
      <ResponseArtifactList
        output={[
          {
            id: "write-call",
            type: "tool_call",
            content: [
              {
                data: {
                  call_id: "write-call",
                  name: "write_file",
                  arguments: JSON.stringify({ file_path: "result.md" }),
                },
              },
            ],
          },
          {
            id: "write-output",
            type: "tool_call_output",
            content: [{ data: { call_id: "write-call", state: "success" } }],
          },
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: "result.md result.md" }),
    ).toBeInTheDocument();
  });

  it("does not show failed file operations", () => {
    const { container } = render(
      <ResponseArtifactList
        output={[
          {
            id: "failed-write",
            type: "tool_call",
            name: "write_file",
            params: { file_path: "failed.md" },
          },
          {
            type: "tool_call_output",
            call_id: "failed-write",
            status: "failed",
          },
        ]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
