// @vitest-environment jsdom
/**
 * RunToolBatchCard tests — batch tool result parsing:
 * media block extraction from nested raw blocks (url variants, files arrays,
 * _raw_blocks, file-like tool_result/tool_use), text-block extraction,
 * JSON stripping of previewed media, dedupe, media type classification,
 * calling-state inline results, and the large-output copy fallback.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    title,
    inlineResult,
    defaultExpanded,
    children,
  }: {
    title: string;
    inlineResult?: string | null;
    defaultExpanded?: boolean;
    children?: React.ReactNode;
  }) => (
    <div data-defaultexpanded={String(!!defaultExpanded)}>
      <div data-testid="shell-title">{title}</div>
      {inlineResult ? <div data-testid="inline">{inlineResult}</div> : null}
      {children}
    </div>
  ),
  DefaultBlock: ({
    title,
    content,
    copyTitle,
  }: {
    title: string;
    content: string;
    copyTitle?: string;
  }) => (
    <div data-testid={`block-${title}`} data-copy={copyTitle ?? null}>
      {content}
    </div>
  ),
  MediaPreview: ({
    media,
  }: {
    media: { url: string; name: string; type: string };
  }) => (
    <div
      data-testid={`media-${media.type}`}
    >{`${media.name}@${media.url}`}</div>
  ),
}));

vi.mock("../shared/utils", () => ({
  shortFileName: (path: string) => path.split("/").pop() || path,
  stringifyResult: (result: unknown) =>
    typeof result === "string"
      ? result
      : result == null
      ? ""
      : JSON.stringify(result),
  toDisplayUrl: (url: string) => url,
  getFileExtFromPath: (url: string) => {
    const clean = url.split(/[?#]/)[0];
    const dot = clean.lastIndexOf(".");
    return dot >= 0 ? clean.slice(dot + 1).toLowerCase() : "";
  },
}));

import RunToolBatchCard from "./RunToolBatchCard";

const content = (
  overrides: Partial<{
    status: string;
    params: Record<string, unknown>;
    result: unknown;
  }> = {},
) => ({
  type: "tool_call" as const,
  id: "batch-1",
  name: "run_tool_batch",
  status: (overrides.status ?? "done") as "done",
  params: overrides.params ?? {},
  result: overrides.result,
});

describe("RunToolBatchCard calling state", () => {
  it("shows the running inline hint and a workflow block while calling", () => {
    render(<RunToolBatchCard content={content({ status: "calling" })} />);
    expect(screen.getByTestId("inline").textContent).toBe(
      "tool.runToolBatchRunning",
    );
    expect(screen.getByTestId("block-Workflow")).toBeTruthy();
    expect(screen.queryByTestId("block-Steps")).toBeNull();
  });

  it("shows the progress count and a steps block when actions exist", () => {
    render(
      <RunToolBatchCard
        content={content({ status: "calling", params: { actions: [1, 2, 3] } })}
      />,
    );
    expect(screen.getByTestId("inline").textContent).toContain('"count":3');
    expect(screen.getByTestId("block-Steps").textContent).toContain(
      '"count":3',
    );
  });
});

describe("RunToolBatchCard title and steps", () => {
  it("uses the file label from params.file_path in the title", () => {
    render(
      <RunToolBatchCard
        content={content({ params: { file_path: "/a/b/flow.json" } })}
      />,
    );
    expect(screen.getByTestId("shell-title").textContent).toContain(
      "flow.json",
    );
  });

  it("falls back to the generic workflow label", () => {
    render(<RunToolBatchCard content={content({})} />);
    expect(screen.getByTestId("shell-title").textContent).toContain(
      "tool.runToolBatch",
    );
  });

  it("renders the step count for completed batches", () => {
    render(
      <RunToolBatchCard content={content({ params: { actions: [{}, {}] } })} />,
    );
    expect(screen.getByTestId("block-Steps").textContent).toContain(
      '"count":2',
    );
  });
});

describe("RunToolBatchCard text output", () => {
  it("joins nested text blocks as the output", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: {
            content: [
              { type: "text", text: "line one" },
              { type: "text", text: "line two" },
            ],
          },
        })}
      />,
    );
    expect(screen.getByTestId("block-Output").textContent).toBe(
      "line one\nline two",
    );
  });

  it("parses JSON strings inside text blocks", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: JSON.stringify([{ type: "text", text: "from json" }]),
        })}
      />,
    );
    expect(screen.getByTestId("block-Output").textContent).toBe("from json");
  });

  it("walks _raw_blocks for text blocks", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: {
            _raw_blocks: [{ type: "text", text: "raw text" }],
          },
        })}
      />,
    );
    expect(screen.getByTestId("block-Output").textContent).toBe("raw text");
  });

  it("falls back to the stringified result when there are no text blocks", () => {
    render(
      <RunToolBatchCard content={content({ result: "plain string result" })} />,
    );
    expect(screen.getByTestId("block-Output").textContent).toBe(
      "plain string result",
    );
  });

  it("skips non-JSON strings shaped like JSON", () => {
    render(<RunToolBatchCard content={content({ result: "[not json" })} />);
    expect(screen.getByTestId("block-Output").textContent).toBe("[not json");
  });

  it("renders nothing when there is neither output nor media", () => {
    render(<RunToolBatchCard content={content({ result: "   " })} />);
    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.queryByTestId(/^media-/)).toBeNull();
  });
});

describe("RunToolBatchCard media extraction", () => {
  it("extracts typed media blocks by url and classification", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: {
            files: [
              { url: "/out/pic.png" },
              { url: "/out/clip.mp4" },
              { url: "/out/song.mp3" },
              { url: "/out/report.pdf" },
            ],
          },
        })}
      />,
    );
    expect(screen.getByTestId("media-image").textContent).toBe(
      "pic.png@/out/pic.png",
    );
    expect(screen.getByTestId("media-video").textContent).toBe(
      "clip.mp4@/out/clip.mp4",
    );
    expect(screen.getByTestId("media-audio").textContent).toBe(
      "song.mp3@/out/song.mp3",
    );
    expect(screen.getByTestId("media-file").textContent).toBe(
      "report.pdf@/out/report.pdf",
    );
  });

  it("prefers explicit type and the highest-priority url fields", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: [
            { type: "image", image_url: "/i.png", filename: "explicit.png" },
            { type: "file", uri: "uri-value", name: "named" },
            { type: "file", path: "/p.txt" },
            { type: "file", source: { url: "/src.jpg" } },
          ],
        })}
      />,
    );
    expect(
      screen.getAllByTestId("media-image").map((el) => el.textContent),
    ).toContain("explicit.png@/i.png");
    expect(screen.getByText("named@uri-value")).toBeTruthy();
    expect(screen.getByText("p.txt@/p.txt")).toBeTruthy();
    // source.url with a .jpg extension is classified as an image
    expect(
      screen.getAllByTestId("media-image").map((el) => el.textContent),
    ).toContain("src.jpg@/src.jpg");
  });

  it("keeps the explicit image type even for unknown extensions", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: [{ type: "image", url: "/x.unknownext" }],
        })}
      />,
    );
    expect(screen.getByTestId("media-image").textContent).toBe(
      "x.unknownext@/x.unknownext",
    );
  });

  it("falls back to title-derived names and skips blocks without urls", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: [
            { type: "file", url: "/a.bin", title: "The Title" },
            { type: "file", name: "orphan" },
          ],
        })}
      />,
    );
    expect(screen.getByText("The Title@/a.bin")).toBeTruthy();
    expect(screen.queryByText(/orphan@/)).toBeNull();
  });

  it("dedupes identical media blocks", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: {
            items: [
              { type: "file", url: "/dup.txt" },
              { type: "file", url: "/dup.txt" },
            ],
          },
        })}
      />,
    );
    expect(screen.getAllByText("dup.txt@/dup.txt")).toHaveLength(1);
  });

  it("collects media from file-like tool_result blocks and nested payloads", () => {
    render(
      <RunToolBatchCard
        content={content({
          result: {
            results: [
              { type: "tool_result", filename: "f.bin", url: "/f.bin" },
              { payload: { attachments: [{ type: "file", url: "/g.bin" }] } },
            ],
          },
        })}
      />,
    );
    expect(screen.getByText("f.bin@/f.bin")).toBeTruthy();
    expect(screen.getByText("g.bin@/g.bin")).toBeTruthy();
  });

  it("uses media-derived names to strip previewed JSON from the output", () => {
    const result = {
      files: [{ url: "/m.png" }],
      extra: "kept",
    };
    render(<RunToolBatchCard content={content({ result })} />);
    expect(screen.getByTestId("media-image")).toBeTruthy();
    // the serialized media object is stripped; the leftover output stays
    const output = screen.getByTestId("block-Output").textContent || "";
    expect(output).toContain("kept");
    expect(output).not.toContain("/m.png");
  });

  it("expands the card automatically when media is present", () => {
    const { container } = render(
      <RunToolBatchCard
        content={content({ result: [{ type: "file", url: "/e.txt" }] })}
      />,
    );
    expect(container.querySelector("[data-defaultexpanded]")).toHaveAttribute(
      "data-defaultexpanded",
      "true",
    );
  });
});

describe("RunToolBatchCard large output", () => {
  it("passes the full text as copyTitle beyond the threshold", () => {
    const big = "x".repeat(13000);
    render(<RunToolBatchCard content={content({ result: big })} />);
    expect(screen.getByTestId("block-Output")).toHaveAttribute(
      "data-copy",
      big,
    );
  });

  it("omits copyTitle below the threshold", () => {
    render(<RunToolBatchCard content={content({ result: "short" })} />);
    expect(screen.getByTestId("block-Output")).not.toHaveAttribute("data-copy");
  });
});
