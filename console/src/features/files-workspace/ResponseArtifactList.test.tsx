// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "files.artifactCreated": "已新增",
        "files.artifactModified": "已修改",
        "files.artifactSent": "已发送",
        "files.artifactsCollapse": "收起",
        "files.artifactsExpand": "展开更多",
      })[key] ?? key,
  }),
}));

import ResponseArtifactList from "./ResponseArtifactList";

function successfulFileIo(path: string, name = "write_file") {
  return [
    {
      id: `result-${path}`,
      type: "tool_call_output",
      status: "completed",
      content: [
        {
          data: {
            call_id: `call-${path}`,
            name,
            arguments: JSON.stringify({ file_path: path }),
          },
        },
        { data: { call_id: `call-${path}`, state: "success" } },
      ],
    },
  ];
}

/**
 * A successful ``send_file_to_user`` result, mirroring the shape observed in
 * persisted console sessions.
 *
 * The DataBlock source shape varies with the delivery path: text files arrive
 * as ``{type: "url", url: "file://…"}`` while images are inlined as
 * ``{type: "base64", data: …}``. Detection keys on the block type, so the
 * base64 shape is deliberately used here as the stricter fixture — it fails
 * immediately if any ``source.url`` coupling is reintroduced.
 */
function successfulSendFile(path: string) {
  const name = path.split("/").pop() ?? path;
  return [
    {
      id: `result-send-${path}`,
      type: "tool_call_output",
      status: "completed",
      content: [
        {
          data: {
            call_id: `call-send-${path}`,
            name: "send_file_to_user",
            arguments: JSON.stringify({ file_path: path }),
          },
        },
        {
          data: {
            call_id: `call-send-${path}`,
            state: "success",
            output: [
              {
                type: "data",
                source: { type: "base64", data: "iVBORw0KGgoAAAANSUhEUg" },
                name,
              },
              { type: "text", text: "File sent successfully." },
            ],
          },
        },
      ],
    },
  ];
}

/**
 * A failed ``send_file_to_user`` result. The backend reports state=success
 * even for errors, but the result carries only a TextBlock (no DataBlock),
 * so ResponseArtifactList must not surface an artifact.
 */
function failedSendFile(path: string) {
  return [
    {
      id: `result-sendfail-${path}`,
      type: "tool_call_output",
      status: "completed",
      content: [
        {
          data: {
            call_id: `call-sendfail-${path}`,
            name: "send_file_to_user",
            arguments: JSON.stringify({ file_path: path }),
          },
        },
        {
          data: {
            call_id: `call-sendfail-${path}`,
            state: "success",
            output: [
              { type: "text", text: `Error: The file ${path} does not exist.` },
            ],
          },
        },
      ],
    },
  ];
}

describe("ResponseArtifactList", () => {
  it("renders each file as a flat preview entry", () => {
    render(
      <ResponseArtifactList
        messages={[
          ...successfulFileIo("snack-shop/public/main.js"),
          ...successfulFileIo("snack-shop/package.json"),
        ]}
      />,
    );

    expect(screen.getByText("main.js")).toBeInTheDocument();
    expect(screen.getByText("snack-shop/public/main.js")).toBeInTheDocument();
    expect(screen.getByText("package.json")).toBeInTheDocument();
    expect(screen.getAllByText("已新增")).toHaveLength(2);
    expect(screen.getAllByText("已新增")[0].tagName).toBe("SMALL");
  });

  it("marks edit and append operations as modified", () => {
    render(
      <ResponseArtifactList
        messages={[
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
        messages={Array.from({ length: 3 }, (_, index) =>
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
        messages={Array.from({ length: 5 }, (_, index) =>
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
      <ResponseArtifactList messages={successfulFileIo("reports/final.md")} />,
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
        messages={[
          { type: "message", content: [{ text: "hello" }] },
          {
            type: "tool_call_output",
            content: [
              {
                data: {
                  name: "shell",
                  arguments: JSON.stringify({
                    file_path: "not-an-artifact.md",
                  }),
                },
              },
              { data: { state: "success" } },
            ],
          },
        ]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders a live SSE file by pairing its tool call and result", () => {
    const liveOutput = [
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
    ];
    render(<ResponseArtifactList messages={liveOutput} />);

    expect(
      screen.getByRole("button", { name: "result.md result.md" }),
    ).toBeInTheDocument();
  });

  it("does not show failed file operations", () => {
    const { container } = render(
      <ResponseArtifactList
        messages={[
          {
            type: "tool_call_output",
            status: "failed",
            content: [
              {
                data: {
                  call_id: "failed-write",
                  name: "write_file",
                  arguments: JSON.stringify({ file_path: "failed.md" }),
                },
              },
              { data: { call_id: "failed-write", state: "failed" } },
            ],
          },
        ]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("surfaces a successfully sent file as an artifact", () => {
    render(
      <ResponseArtifactList
        messages={successfulSendFile("reports/summary.pdf")}
      />,
    );

    expect(screen.getByText("summary.pdf")).toBeInTheDocument();
    expect(screen.getByText("reports/summary.pdf")).toBeInTheDocument();
  });

  it("marks sent files with the sent status", () => {
    render(<ResponseArtifactList messages={successfulSendFile("notes.txt")} />);

    expect(screen.getByText("已发送")).toBeInTheDocument();
  });

  it("does not show send_file_to_user when the result has no DataBlock", () => {
    const { container } = render(
      <ResponseArtifactList messages={failedSendFile("missing.pdf")} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("surfaces an absolute path as an attachment artifact", () => {
    render(
      <ResponseArtifactList
        messages={successfulSendFile("/tmp/workspace/export.csv")}
      />,
    );

    expect(screen.getByText("export.csv")).toBeInTheDocument();
    expect(screen.getByText("已发送")).toBeInTheDocument();
  });

  it("routes a ~ path to the attachment preview the backend expands", () => {
    // parseInternalFileLink would treat `~` as a workspace-relative segment;
    // the preview endpoint expanduser()s it instead, so it must reach the
    // attachment branch.
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);
    render(
      <ResponseArtifactList
        messages={successfulSendFile("~/reports/summary.md")}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "summary.md ~/reports/summary.md",
      }),
    );

    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail.target.source).toBe("attachment");
    expect(event.detail.target.path).toBe("~/reports/summary.md");
    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("surfaces a filename containing a literal #", () => {
    // Tool paths are filesystem paths, not Markdown hrefs: `#` must stay part
    // of the name instead of being parsed as a line-reference fragment.
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);
    render(
      <ResponseArtifactList
        messages={successfulSendFile("reports/Report #3.pdf")}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Report #3.pdf reports/Report #3.pdf",
      }),
    );

    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail.target).toEqual({
      source: "workspace",
      path: "reports/Report #3.pdf",
      root: "project",
    });
    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("still rejects parent-segment traversal", () => {
    const { container } = render(
      <ResponseArtifactList
        messages={successfulSendFile("../shared/report.pdf")}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
