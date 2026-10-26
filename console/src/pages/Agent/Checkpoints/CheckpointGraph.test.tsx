/**
 * CheckpointGraph — the virtualised Git-lane graph of the Checkpoints page.
 *
 * Covered behaviour: the three render arms (empty description / nothing while
 * the container is still unmeasured / the virtual list), the lane-width
 * clamping, the SVG lane drawing (vertical lane segments, the parent-lane
 * curve, the HEAD halo), the per-kind node glyph, the row text fallback
 * chains, selection styling and the click callback, the column header, and the
 * size observer lifecycle.
 *
 * react-window is stubbed so every row renders: virtualisation itself is
 * third-party behaviour, but the props handed to the list (item size,
 * overscan, item count, item data, item key) are asserted so the wiring stays
 * pinned.
 *
 * Two shapes of the product drive the assertions below and are easy to get
 * wrong, so they are spelled out:
 *  - the list arm needs a measured box, therefore clientWidth/clientHeight
 *    have to be defined on HTMLElement for those cases (jsdom reports 0);
 *  - buildGraphRows snapshots lanesBefore *after* assigning the node's own
 *    commit into its lane, so a row's lanesBefore always contains that row's
 *    own commit; an isolated commit therefore still draws one top segment.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";

const listSpy = vi.hoisted(() => ({ current: null as any }));
const i18nState = vi.hoisted(() => ({
  resolvedLanguage: "en" as string | undefined,
}));

vi.mock("react-window", () => ({
  FixedSizeList: (props: any) => {
    listSpy.current = props;
    const Row = props.children as React.ComponentType<any>;
    return (
      <div data-testid="virtual-list">
        {Array.from({ length: props.itemCount }, (_, i) => (
          <Row
            key={i}
            index={i}
            style={{ top: i * props.itemSize }}
            data={props.itemData}
          />
        ))}
      </div>
    );
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: i18nState,
  }),
}));

import { CheckpointGraph } from "./CheckpointGraph";
import { buildGraphRows, type GraphRow } from "./graphLayout";
import styles from "./index.module.less";

const ROW_HEIGHT = 58;
const CENTER = ROW_HEIGHT / 2;
const LANE_X = [15, 33, 51];
const PALETTE = [
  "#3178c6",
  "#2d8a68",
  "#b26a1b",
  "#8b5fbf",
  "#c34f67",
  "#3b8793",
];

function makeNode(over: Record<string, unknown> = {}) {
  return {
    ref: "refs/heads/main",
    kind: "auto",
    session_key: "console:sess-a",
    name: "",
    commit: "c1",
    sha: "c1short",
    timestamp_ms: 1700000000000,
    subject: "initial subject",
    query: null,
    channel: "console",
    restore_index: null,
    parent_commit: null,
    is_head: false,
    user_id: "u1",
    session_id: "sid-1",
    session_title: "Session One",
    ...over,
  } as any;
}

function setSize(width: number, height: number) {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    value: width,
  });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    value: height,
  });
}

function renderGraph(nodes: any[], over: Record<string, unknown> = {}) {
  const rows = (over.rows as GraphRow[]) ?? buildGraphRows(nodes);
  const onSelect = (over.onSelect as any) ?? vi.fn();
  const utils = render(
    <CheckpointGraph
      rows={rows}
      laneCount={(over.laneCount as number) ?? 1}
      selectedCommit={(over.selectedCommit as string | null) ?? null}
      onSelect={onSelect}
      emptyDescription={
        (over.emptyDescription as string) ?? "no checkpoints yet"
      }
    />,
  );
  return { ...utils, rows, onSelect };
}

/** The graph svg of one row (lucide icons also render svg, so scope by class). */
function graphSvg(container: HTMLElement, rowIndex = 0) {
  return container.querySelectorAll(`svg.${styles.graphSvg}`)[rowIndex] as
    | SVGSVGElement
    | undefined;
}

function lanesOf(svg: SVGSVGElement, edge: "top" | "bottom") {
  const attr = edge === "top" ? "y1" : "y2";
  const fixed = edge === "top" ? "0" : String(ROW_HEIGHT);
  return Array.from(svg.querySelectorAll("line")).filter(
    (l) => l.getAttribute(attr) === fixed,
  );
}

beforeEach(() => {
  listSpy.current = null;
  i18nState.resolvedLanguage = "en";
  setSize(0, 0);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (HTMLElement.prototype as any).clientWidth;
  delete (HTMLElement.prototype as any).clientHeight;
});

describe("CheckpointGraph — render arms", () => {
  it("shows the caller supplied empty description when there are no rows", () => {
    const { container } = renderGraph([], {
      emptyDescription: "nothing recorded",
    });
    expect(screen.getByText("nothing recorded")).toBeInTheDocument();
    expect(screen.queryByTestId("virtual-list")).not.toBeInTheDocument();
    const empty = container.querySelector(".ant-empty");
    expect(empty).not.toBeNull();
    expect(empty?.className).toContain(styles.emptyState);
    expect(empty?.querySelector(".ant-empty-description")?.textContent).toBe(
      "nothing recorded",
    );
    expect(empty?.querySelector(".ant-empty-image svg")).not.toBeNull();
  });

  it("renders no list and no empty state while the container box is still zero", () => {
    setSize(0, 0);
    const { container } = renderGraph([makeNode()]);
    expect(screen.queryByTestId("virtual-list")).not.toBeInTheDocument();
    expect(screen.queryByText("no checkpoints yet")).not.toBeInTheDocument();
    const body = container.querySelector(`.${styles.graphBody}`);
    expect(body).not.toBeNull();
    expect(body?.children.length).toBe(0);
  });

  it("still renders nothing when only the width is measured", () => {
    setSize(640, 0);
    renderGraph([makeNode()]);
    expect(screen.queryByTestId("virtual-list")).not.toBeInTheDocument();
    expect(screen.queryByText("no checkpoints yet")).not.toBeInTheDocument();
  });

  it("still renders nothing when only the height is measured", () => {
    setSize(0, 480);
    renderGraph([makeNode()]);
    expect(screen.queryByTestId("virtual-list")).not.toBeInTheDocument();
    expect(screen.queryByText("no checkpoints yet")).not.toBeInTheDocument();
  });

  it("renders the virtual list once both dimensions are measured", () => {
    setSize(760, 480);
    renderGraph([makeNode()]);
    expect(screen.getByTestId("virtual-list")).toBeInTheDocument();
    expect(screen.queryByText("no checkpoints yet")).not.toBeInTheDocument();
  });

  it("hands the measured box, row height and overscan to the list", () => {
    setSize(760, 480);
    renderGraph([
      makeNode(),
      makeNode({ commit: "c2", sha: "c2short", ref: "refs/heads/b" }),
    ]);
    const props = listSpy.current;
    expect(props.height).toBe(480);
    expect(props.width).toBe(760);
    expect(props.itemSize).toBe(ROW_HEIGHT);
    expect(props.itemCount).toBe(2);
    expect(props.overscanCount).toBe(8);
    expect(typeof props.itemKey).toBe("function");
    expect(props.itemData.rows).toHaveLength(2);
    expect(props.itemData.graphWidth).toBeGreaterThan(0);
    expect(props.itemData.locale).toBe("en");
    expect(props.itemData.colors).toBeInstanceOf(Map);
    expect(Object.keys(props.itemData.labels).sort()).toEqual([
      "auto",
      "pre-restore",
      "sha",
      "snap",
    ]);
  });

  it("keys list rows by the node ref, not by the commit", () => {
    setSize(760, 480);
    renderGraph([
      makeNode({ ref: "refs/heads/main", commit: "c1" }),
      makeNode({
        ref: "refs/tags/v1",
        commit: "c2",
        sha: "c2s",
        session_key: "console:sess-b",
      }),
    ]);
    const { itemData, itemKey } = listSpy.current;
    expect(itemKey(0, itemData)).toBe("refs/heads/main");
    expect(itemKey(1, itemData)).toBe("refs/tags/v1");
  });

  it("renders one row button per node", () => {
    setSize(760, 480);
    renderGraph([
      makeNode({ commit: "c1", sha: "s1", ref: "r1" }),
      makeNode({
        commit: "c2",
        sha: "s2",
        ref: "r2",
        session_key: "console:sess-b",
      }),
      makeNode({
        commit: "c3",
        sha: "s3",
        ref: "r3",
        session_key: "console:sess-c",
      }),
    ]);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(3);
    expect(listSpy.current.itemCount).toBe(3);
  });
});

describe("CheckpointGraph — lane width clamping", () => {
  const widthOf = (laneCount: number) => {
    setSize(900, 500);
    const { container } = renderGraph([makeNode()], { laneCount });
    const header = container.querySelector(
      `.${styles.graphHeader} > span`,
    ) as HTMLElement;
    return Number(header.style.width.replace("px", ""));
  };

  it("clamps a single lane up to the 72px floor", () => {
    // 15*2 + 1*18 = 48, below the floor.
    expect(widthOf(1)).toBe(72);
  });

  it("keeps a zero lane count at the floor", () => {
    expect(widthOf(0)).toBe(72);
  });

  it("uses the computed width inside the clamp band", () => {
    // 15*2 + 6*18 = 138.
    expect(widthOf(6)).toBe(138);
  });

  it("clamps a very wide lane count down to the 224px ceiling", () => {
    // 15*2 + 40*18 = 750, above the ceiling.
    expect(widthOf(40)).toBe(224);
  });

  it("lands exactly on the ceiling at the band boundary", () => {
    // 15*2 + 10*18 = 210 (inside), 15*2 + 11*18 = 228 (clamped to 224).
    expect(widthOf(10)).toBe(210);
    expect(widthOf(11)).toBe(224);
  });

  it("applies the same width to the graph cell and the svg", () => {
    setSize(900, 500);
    const { container } = renderGraph([makeNode()], { laneCount: 6 });
    const cell = container.querySelector(`.${styles.graphCell}`) as HTMLElement;
    expect(cell.style.width).toBe("138px");
    const svg = graphSvg(container);
    expect(svg?.getAttribute("width")).toBe("138");
    expect(svg?.getAttribute("height")).toBe(String(ROW_HEIGHT));
  });
});

describe("CheckpointGraph — column header", () => {
  it("renders the five translated column labels in order", () => {
    setSize(900, 500);
    const { container } = renderGraph([makeNode()], { laneCount: 2 });
    const header = container.querySelector(
      `.${styles.graphHeader}`,
    ) as HTMLElement;
    const spans = Array.from(header.children);
    expect(spans).toHaveLength(5);
    expect(spans[0].textContent).toContain("checkpoints.graph");
    expect(spans[1].textContent).toBe("checkpoints.checkpoint");
    expect(spans[2].textContent).toBe("checkpoints.type");
    expect(spans[3].textContent).toBe("checkpoints.commit");
    expect(spans[4].textContent).toBe("checkpoints.createdAt");
    expect(spans[1].className).toContain(styles.messageHeader);
    expect(spans[0].querySelector("svg")).not.toBeNull();
  });
});

describe("CheckpointGraph — row content and fallback chains", () => {
  beforeEach(() => setSize(900, 500));

  it("prefers the query as the row title", () => {
    renderGraph([
      makeNode({ query: "what changed?", name: "snap name", subject: "subj" }),
    ]);
    expect(screen.getByText("what changed?")).toBeInTheDocument();
    expect(screen.queryByText("snap name")).not.toBeInTheDocument();
    expect(screen.queryByText("subj")).not.toBeInTheDocument();
  });

  it("falls back to the snapshot name when there is no query", () => {
    renderGraph([
      makeNode({ query: null, name: "snap name", subject: "subj" }),
    ]);
    expect(screen.getByText("snap name")).toBeInTheDocument();
    expect(screen.queryByText("subj")).not.toBeInTheDocument();
  });

  it("falls back to the commit subject when neither query nor name exist", () => {
    renderGraph([makeNode({ query: null, name: "", subject: "subj" })]);
    expect(screen.getByText("subj")).toBeInTheDocument();
  });

  it("builds the row accessible name from the title and the kind label", () => {
    renderGraph([
      makeNode({ query: null, name: "", subject: "subj", kind: "snap" }),
    ]);
    expect(
      screen.getByRole("button", { name: "subj, checkpoints.kind.snapshot" }),
    ).toBeInTheDocument();
  });

  it("shows the session title in the meta line together with the channel", () => {
    const { container } = renderGraph([
      makeNode({ channel: "dingtalk", session_title: "Release chat" }),
    ]);
    const meta = container.querySelector(
      `.${styles.messageMeta}`,
    ) as HTMLElement;
    expect(meta.textContent).toContain("dingtalk");
    expect(meta.textContent).toContain("Release chat");
  });

  it("falls back to the session id when the session has no title", () => {
    const { container } = renderGraph([
      makeNode({
        session_title: "",
        session_id: "sid-9",
        session_key: "console:k",
      }),
    ]);
    const meta = container.querySelector(
      `.${styles.messageMeta}`,
    ) as HTMLElement;
    expect(meta.textContent).toContain("sid-9");
    expect(meta.textContent).not.toContain("console:k");
  });

  it("falls back to the session key when neither title nor id exist", () => {
    const { container } = renderGraph([
      makeNode({
        session_title: "",
        session_id: "",
        session_key: "console:last",
      }),
    ]);
    const meta = container.querySelector(
      `.${styles.messageMeta}`,
    ) as HTMLElement;
    expect(meta.textContent).toContain("console:last");
  });

  it("renders the message title inside the message cell", () => {
    const { container } = renderGraph([makeNode({ subject: "a subject" })]);
    const cell = container.querySelector(
      `.${styles.messageCell}`,
    ) as HTMLElement;
    expect(cell.querySelector(`.${styles.messageTitle}`)?.textContent).toBe(
      "a subject",
    );
  });

  it("renders the short sha in the code cell and the full commit in the tooltip", async () => {
    const { container } = renderGraph([
      makeNode({ sha: "abc1234", commit: "abc1234567890" }),
    ]);
    const code = container.querySelector(
      `code.${styles.shaCell}`,
    ) as HTMLElement;
    expect(code.textContent).toBe("abc1234");
    // antd renders the tooltip into a portal on hover, it does not wrap the
    // trigger element, so the full commit is only observable after entering.
    expect(document.querySelectorAll(".ant-tooltip")).toHaveLength(0);
    fireEvent.mouseEnter(code);
    await waitFor(() =>
      expect(document.querySelectorAll(".ant-tooltip").length).toBeGreaterThan(
        0,
      ),
    );
    expect(document.querySelector(".ant-tooltip")?.textContent).toBe(
      "abc1234567890",
    );
  });

  it("renders an ISO timestamp on the time element", () => {
    const { container } = renderGraph([
      makeNode({ timestamp_ms: 1700000000000 }),
    ]);
    const time = container.querySelector(
      `time.${styles.timeCell}`,
    ) as HTMLElement;
    expect(time.getAttribute("datetime")).toBe("2023-11-14T22:13:20.000Z");
    expect(time.textContent?.trim().length).toBeGreaterThan(0);
  });

  it("formats another instant to its own ISO timestamp", () => {
    const { container } = renderGraph([makeNode({ timestamp_ms: 0 })]);
    const time = container.querySelector(
      `time.${styles.timeCell}`,
    ) as HTMLElement;
    expect(time.getAttribute("datetime")).toBe("1970-01-01T00:00:00.000Z");
  });

  it("passes the resolved language through to the row data", () => {
    i18nState.resolvedLanguage = "zh-CN";
    renderGraph([makeNode()]);
    expect(listSpy.current.itemData.locale).toBe("zh-CN");
  });

  it("falls back to English when the resolved language is absent", () => {
    i18nState.resolvedLanguage = undefined;
    renderGraph([makeNode()]);
    expect(listSpy.current.itemData.locale).toBe("en");
  });
});

describe("CheckpointGraph — kind glyph and labels", () => {
  beforeEach(() => setSize(900, 500));

  const kinds: Array<[string, string]> = [
    ["auto", "checkpoints.kind.auto"],
    ["snap", "checkpoints.kind.snapshot"],
    ["pre-restore", "checkpoints.kind.safety"],
    ["sha", "checkpoints.kind.commit"],
  ];

  it.each(kinds)("labels a %s node with its translated kind", (kind, label) => {
    renderGraph([makeNode({ kind })]);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("tags the row with the kind tag class", () => {
    const { container } = renderGraph([makeNode({ kind: "auto" })]);
    const tag = container.querySelector(`.${styles.kindTag}`);
    expect(tag).not.toBeNull();
    expect(tag?.textContent).toBe("checkpoints.kind.auto");
  });

  it("falls back to the raw kind when the backend sends an unknown one", () => {
    // The label map only knows the four declared kinds; anything else coming
    // from the API has to be shown verbatim instead of rendering blank.
    renderGraph([makeNode({ kind: "future-kind" })]);
    expect(screen.getByText("future-kind")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "initial subject, future-kind" }),
    ).toBeInTheDocument();
    // The unknown kind still renders as a circle, not as a snapshot square.
    expect(
      screen.queryByText("checkpoints.kind.snapshot"),
    ).not.toBeInTheDocument();
  });

  it("maps the dashed kind onto its underscored style key", () => {
    const { container } = renderGraph([makeNode({ kind: "pre-restore" })]);
    const tag = container.querySelector(`.${styles.kindTag}`);
    expect(tag?.className).toContain(styles.kind_pre_restore);
  });

  it("draws a rounded square for a snapshot node", () => {
    const { container } = renderGraph([makeNode({ kind: "snap" })]);
    const svg = graphSvg(container) as SVGSVGElement;
    const rect = svg.querySelector(`rect.${styles.snapshotNode}`);
    expect(rect).not.toBeNull();
    expect(rect?.getAttribute("width")).toBe("10");
    expect(rect?.getAttribute("height")).toBe("10");
    expect(rect?.getAttribute("rx")).toBe("1");
    expect(rect?.getAttribute("x")).toBe(String(LANE_X[0] - 5));
    expect(rect?.getAttribute("y")).toBe(String(CENTER - 5));
    expect(PALETTE).toContain(rect?.getAttribute("fill"));
    expect(svg.querySelectorAll("circle")).toHaveLength(0);
  });

  it("draws a hollow ring node for a pre-restore checkpoint", () => {
    const { container } = renderGraph([makeNode({ kind: "pre-restore" })]);
    const circles = Array.from(graphSvg(container)!.querySelectorAll("circle"));
    expect(circles).toHaveLength(1);
    expect(circles[0].getAttribute("r")).toBe("5.5");
    expect(circles[0].getAttribute("fill")).toBe("var(--checkpoint-surface)");
    expect(circles[0].getAttribute("stroke-width")).toBe("2.5");
    expect(circles[0].getAttribute("cx")).toBe(String(LANE_X[0]));
    expect(circles[0].getAttribute("cy")).toBe(String(CENTER));
  });

  it("draws a small filled node for an automatic checkpoint", () => {
    const { container } = renderGraph([makeNode({ kind: "auto" })]);
    const circles = Array.from(graphSvg(container)!.querySelectorAll("circle"));
    expect(circles).toHaveLength(1);
    expect(circles[0].getAttribute("r")).toBe("4.5");
    expect(circles[0].getAttribute("stroke-width")).toBe("2");
    expect(PALETTE).toContain(circles[0].getAttribute("fill"));
    expect(circles[0].getAttribute("fill")).toBe(
      circles[0].getAttribute("stroke"),
    );
  });

  it("draws the same filled node for a sha checkpoint", () => {
    const { container } = renderGraph([makeNode({ kind: "sha" })]);
    const circles = Array.from(graphSvg(container)!.querySelectorAll("circle"));
    expect(circles).toHaveLength(1);
    expect(circles[0].getAttribute("r")).toBe("4.5");
    expect(circles[0].getAttribute("fill")).not.toBe(
      "var(--checkpoint-surface)",
    );
  });

  it("adds the HEAD badge and halo only for the head node", () => {
    const { container } = renderGraph([
      makeNode({ commit: "c1", is_head: true, sha: "s1", ref: "r1" }),
      makeNode({
        commit: "c2",
        sha: "s2",
        ref: "r2",
        session_key: "console:sess-b",
        is_head: false,
      }),
    ]);
    const badges = container.querySelectorAll(`.${styles.headTag}`);
    expect(badges).toHaveLength(1);
    expect(badges[0].textContent).toContain("HEAD");
    expect(badges[0].querySelector("svg")).not.toBeNull();
    const halos = container.querySelectorAll(`circle.${styles.headHalo}`);
    expect(halos).toHaveLength(1);
    expect(halos[0].getAttribute("r")).toBe("9");
    expect(halos[0].getAttribute("fill")).toBe("none");
    expect(PALETTE).toContain(halos[0].getAttribute("stroke"));
  });

  it("omits the halo and badge for a non-head snapshot", () => {
    const { container } = renderGraph([
      makeNode({ kind: "snap", is_head: false }),
    ]);
    expect(
      container.querySelectorAll(`circle.${styles.headHalo}`),
    ).toHaveLength(0);
    expect(container.querySelectorAll(`.${styles.headTag}`)).toHaveLength(0);
  });

  it("keeps the node glyph and the halo in the same lane for a head node", () => {
    const { container } = renderGraph([makeNode({ is_head: true })]);
    const svg = graphSvg(container) as SVGSVGElement;
    const halo = svg.querySelector(`circle.${styles.headHalo}`);
    const node = Array.from(svg.querySelectorAll("circle")).find(
      (c) => !c.classList.contains(styles.headHalo),
    );
    expect(halo?.getAttribute("cx")).toBe(node?.getAttribute("cx"));
    expect(halo?.getAttribute("cy")).toBe(node?.getAttribute("cy"));
  });
});

describe("CheckpointGraph — svg lane drawing", () => {
  beforeEach(() => setSize(900, 500));

  it("draws the top segment for its own commit but no bottom one when the lane ends", () => {
    // An isolated commit still owns a lane while it is being drawn, because
    // buildGraphRows snapshots lanesBefore after assigning the commit.
    const { container, rows } = renderGraph([makeNode()]);
    expect(rows[0].lanesBefore).toEqual(["c1"]);
    expect(rows[0].lanesAfter).toEqual([]);
    const svg = graphSvg(container) as SVGSVGElement;
    const tops = lanesOf(svg, "top");
    expect(tops).toHaveLength(1);
    expect(tops[0].getAttribute("x1")).toBe(String(LANE_X[0]));
    expect(tops[0].getAttribute("x2")).toBe(String(LANE_X[0]));
    expect(tops[0].getAttribute("y2")).toBe(String(CENTER));
    expect(lanesOf(svg, "bottom")).toHaveLength(0);
    expect(svg.querySelectorAll("path")).toHaveLength(0);
  });

  it("draws a segment per occupied lane across a branching history", () => {
    const { container, rows } = renderGraph([
      makeNode({
        commit: "c1",
        sha: "s1",
        ref: "r1",
        session_key: "console:a",
      }),
      makeNode({
        commit: "c2",
        sha: "s2",
        ref: "r2",
        session_key: "console:b",
        parent_commit: "c1",
      }),
      makeNode({
        commit: "c3",
        sha: "s3",
        ref: "r3",
        session_key: "console:c",
        parent_commit: "c1",
      }),
    ]);
    // The third row sits on its own lane while the first lane stays occupied.
    expect(rows[2].lane).toBe(1);
    expect(rows[2].lanesBefore).toEqual(["c1", "c3"]);
    expect(rows[2].lanesAfter).toEqual(["c1"]);
    const svg = graphSvg(container, 2) as SVGSVGElement;
    const tops = lanesOf(svg, "top");
    expect(tops).toHaveLength(2);
    expect(tops.map((l) => l.getAttribute("x1"))).toEqual([
      String(LANE_X[0]),
      String(LANE_X[1]),
    ]);
    const bottoms = lanesOf(svg, "bottom");
    expect(bottoms).toHaveLength(1);
    expect(bottoms[0].getAttribute("x1")).toBe(String(LANE_X[0]));
    expect(bottoms[0].getAttribute("y1")).toBe(String(CENTER));
  });

  it("skips null lane slots when drawing segments", () => {
    // GraphRow.lanesBefore is typed Array<string | null> and GraphLines guards
    // each slot with `commit &&`, so a null slot draws nothing. buildGraphRows
    // does not emit interior nulls for ordinary histories, so the row is built
    // by hand to exercise the guard.
    const rows: GraphRow[] = [
      {
        node: makeNode({ commit: "c1", sha: "s1" }),
        lane: 0,
        lanesBefore: ["c1", null, "c9"],
        lanesAfter: [null, null, "c9"],
        parentLane: null,
      },
    ];
    const { container } = renderGraph([], { rows, laneCount: 3 });
    const svg = graphSvg(container) as SVGSVGElement;
    const tops = lanesOf(svg, "top");
    expect(tops).toHaveLength(2);
    expect(tops.map((l) => l.getAttribute("x1"))).toEqual([
      String(LANE_X[0]),
      String(LANE_X[2]),
    ]);
    const bottoms = lanesOf(svg, "bottom");
    expect(bottoms).toHaveLength(1);
    expect(bottoms[0].getAttribute("x1")).toBe(String(LANE_X[2]));
  });

  it("draws the parent lane curve only when the parent sits on another lane", () => {
    const { container, rows } = renderGraph([
      makeNode({
        commit: "c1",
        sha: "s1",
        ref: "r1",
        session_key: "console:a",
      }),
      makeNode({
        commit: "c2",
        sha: "s2",
        ref: "r2",
        session_key: "console:b",
        parent_commit: "c1",
      }),
      makeNode({
        commit: "c3",
        sha: "s3",
        ref: "r3",
        session_key: "console:c",
        parent_commit: "c1",
      }),
    ]);
    expect(rows[2].lane).toBe(1);
    expect(rows[2].parentLane).toBe(0);
    const path = graphSvg(container, 2)?.querySelector("path");
    expect(path).not.toBeNull();
    expect(path?.getAttribute("fill")).toBe("none");
    expect(path?.getAttribute("d")).toBe(
      `M ${LANE_X[1]} ${CENTER} C ${LANE_X[1]} ${CENTER + 13}, ${LANE_X[0]} ${
        CENTER + 13
      }, ${LANE_X[0]} ${ROW_HEIGHT}`,
    );
    // Rows whose parent stays on their own lane draw no curve.
    expect(graphSvg(container, 1)?.querySelector("path")).toBeNull();
    expect(graphSvg(container, 0)?.querySelector("path")).toBeNull();
  });

  it("draws no curve when the row has no parent lane at all", () => {
    const { container, rows } = renderGraph([
      makeNode({ parent_commit: null }),
    ]);
    expect(rows[0].parentLane).toBeNull();
    expect(graphSvg(container)?.querySelector("path")).toBeNull();
  });

  it("draws no curve when a single lane history keeps the parent in place", () => {
    const { container, rows } = renderGraph([
      makeNode({ commit: "c1", sha: "s1", ref: "r1" }),
      makeNode({
        commit: "c2",
        sha: "s2",
        ref: "r2",
        parent_commit: "c1",
        session_key: "console:b",
      }),
    ]);
    expect(rows[1].lane).toBe(0);
    expect(rows[1].parentLane).toBe(0);
    expect(graphSvg(container, 1)?.querySelector("path")).toBeNull();
  });

  it("colours each segment with the owning session colour from the map", () => {
    const { container } = renderGraph([
      makeNode({
        commit: "c1",
        sha: "s1",
        ref: "r1",
        session_key: "console:a",
      }),
      makeNode({
        commit: "c2",
        sha: "s2",
        ref: "r2",
        session_key: "console:b",
        parent_commit: "c1",
      }),
      makeNode({
        commit: "c3",
        sha: "s3",
        ref: "r3",
        session_key: "console:c",
        parent_commit: "c1",
      }),
    ]);
    const colors: Map<string, string> = listSpy.current.itemData.colors;
    expect(colors.size).toBe(3);
    expect(colors.get("c1")).not.toBe(colors.get("c3"));
    const svg = graphSvg(container, 2) as SVGSVGElement;
    const tops = lanesOf(svg, "top");
    expect(tops[0].getAttribute("stroke")).toBe(colors.get("c1"));
    expect(tops[1].getAttribute("stroke")).toBe(colors.get("c3"));
    expect(lanesOf(svg, "bottom")[0].getAttribute("stroke")).toBe(
      colors.get("c1"),
    );
  });

  it("falls back to the row colour for a lane holding an unknown commit", () => {
    // A parent that is not itself a listed node ends up occupying a lane
    // without an entry in the colour map.
    const { container, rows } = renderGraph([
      makeNode({
        commit: "c1",
        sha: "s1",
        ref: "r1",
        session_key: "console:a",
        parent_commit: "ghostcommit",
      }),
    ]);
    expect(rows[0].lanesAfter).toEqual(["ghostcommit"]);
    const colors: Map<string, string> = listSpy.current.itemData.colors;
    expect(colors.has("ghostcommit")).toBe(false);
    const svg = graphSvg(container) as SVGSVGElement;
    const bottoms = lanesOf(svg, "bottom");
    expect(bottoms).toHaveLength(1);
    // Without the fallback the stroke would be missing entirely.
    expect(bottoms[0].getAttribute("stroke")).toBe(colors.get("c1"));
    expect(PALETTE).toContain(bottoms[0].getAttribute("stroke"));
  });

  it("gives every listed session a colour from the palette", () => {
    const keys = [
      "console:a",
      "console:b",
      "console:cccc",
      "dingtalk:x",
      "telegram:long-key",
      "cli:1",
    ];
    const { container } = renderGraph(
      keys.map((k, i) =>
        makeNode({
          commit: `c${i}`,
          sha: `s${i}`,
          ref: `refs/heads/b${i}`,
          session_key: k,
          parent_commit: null,
        }),
      ),
      { laneCount: keys.length },
    );
    const colors: Map<string, string> = listSpy.current.itemData.colors;
    expect(colors.size).toBe(keys.length);
    colors.forEach((c) => expect(PALETTE).toContain(c));
    // Each row's own glyph is filled with its session colour.
    const svgs = container.querySelectorAll(`svg.${styles.graphSvg}`);
    expect(svgs).toHaveLength(keys.length);
    Array.from(svgs).forEach((svg, i) => {
      const circle = svg.querySelector("circle:not([class])");
      expect(circle?.getAttribute("fill")).toBe(colors.get(`c${i}`));
    });
  });

  it("reuses one colour for two nodes of the same session", () => {
    renderGraph([
      makeNode({
        commit: "c1",
        sha: "s1",
        ref: "r1",
        session_key: "console:same",
      }),
      makeNode({
        commit: "c2",
        sha: "s2",
        ref: "r2",
        session_key: "console:same",
        parent_commit: "c1",
      }),
    ]);
    const colors: Map<string, string> = listSpy.current.itemData.colors;
    expect(colors.get("c1")).toBe(colors.get("c2"));
  });

  it("hides the decorative svg from assistive technology", () => {
    const { container } = renderGraph([makeNode()]);
    expect(graphSvg(container)?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("CheckpointGraph — selection and activation", () => {
  beforeEach(() => setSize(900, 500));

  it("marks the row whose commit is selected", () => {
    const { container } = renderGraph(
      [
        makeNode({ commit: "c1", sha: "s1", ref: "r1" }),
        makeNode({
          commit: "c2",
          sha: "s2",
          ref: "r2",
          session_key: "console:b",
        }),
      ],
      { selectedCommit: "c2" },
    );
    const rows = Array.from(
      container.querySelectorAll(`button.${styles.graphRow}`),
    );
    expect(rows).toHaveLength(2);
    expect(rows[0].className).not.toContain(styles.selectedRow);
    expect(rows[1].className).toContain(styles.selectedRow);
  });

  it("marks the first row when the oldest commit is selected", () => {
    const { container } = renderGraph(
      [
        makeNode({ commit: "c1", sha: "s1", ref: "r1" }),
        makeNode({
          commit: "c2",
          sha: "s2",
          ref: "r2",
          session_key: "console:b",
        }),
      ],
      { selectedCommit: "c1" },
    );
    const rows = Array.from(
      container.querySelectorAll(`button.${styles.graphRow}`),
    );
    expect(rows[0].className).toContain(styles.selectedRow);
    expect(rows[1].className).not.toContain(styles.selectedRow);
  });

  it("marks nothing when no commit is selected", () => {
    const { container } = renderGraph([makeNode({ commit: "c1" })], {
      selectedCommit: null,
    });
    expect(container.querySelectorAll(`.${styles.selectedRow}`)).toHaveLength(
      0,
    );
  });

  it("marks nothing when the selected commit is not in the list", () => {
    const { container } = renderGraph([makeNode({ commit: "c1" })], {
      selectedCommit: "somewhere-else",
    });
    expect(container.querySelectorAll(`.${styles.selectedRow}`)).toHaveLength(
      0,
    );
  });

  it("reports the clicked node back to the page", () => {
    const onSelect = vi.fn();
    renderGraph(
      [
        makeNode({ commit: "c1", sha: "s1", ref: "r1" }),
        makeNode({
          commit: "c2",
          sha: "s2",
          ref: "r2",
          session_key: "console:b",
        }),
      ],
      { onSelect },
    );
    const buttons = screen.getAllByRole("button");
    fireEvent.click(buttons[1]);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].commit).toBe("c2");
    expect(onSelect.mock.calls[0][0].sha).toBe("s2");
  });

  it("reports the first row when it is the one clicked", () => {
    const onSelect = vi.fn();
    renderGraph([makeNode({ commit: "c1" })], { onSelect });
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].commit).toBe("c1");
  });

  it("does not report anything before a row is clicked", () => {
    const onSelect = vi.fn();
    renderGraph([makeNode()], { onSelect });
    expect(onSelect).not.toHaveBeenCalled();
    // Negative control for the assertion above: clicking does fire it.
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("declares the row button as a plain button element", () => {
    const { container } = renderGraph([
      makeNode({ commit: "c1", sha: "s1", ref: "r1" }),
      makeNode({
        commit: "c2",
        sha: "s2",
        ref: "r2",
        session_key: "console:b",
      }),
    ]);
    const buttons = container.querySelectorAll(`button.${styles.graphRow}`);
    expect(buttons[0].getAttribute("type")).toBe("button");
    // The offset handed down by the list is applied to the row element, which
    // is what keeps the virtualised rows stacked instead of overlapping.
    expect((buttons[1] as HTMLElement).style.top).toBe(`${ROW_HEIGHT}px`);
  });
});

describe("CheckpointGraph — container size observation", () => {
  function stubObserver() {
    const observe = vi.fn();
    const disconnect = vi.fn();
    const unobserve = vi.fn();
    const ctor = vi.fn().mockImplementation(function () {
      return { observe, unobserve, disconnect };
    });
    vi.stubGlobal("ResizeObserver", ctor);
    return { observe, disconnect, unobserve, ctor };
  }

  it("observes the body element and disconnects on unmount", () => {
    setSize(0, 0);
    const { observe, disconnect, ctor } = stubObserver();
    const { container, unmount } = renderGraph([makeNode()]);
    const body = container.querySelector(`.${styles.graphBody}`);
    expect(ctor).toHaveBeenCalledTimes(1);
    expect(observe).toHaveBeenCalledTimes(1);
    expect(observe.mock.calls[0][0]).toBe(body);
    expect(disconnect).not.toHaveBeenCalled();
    unmount();
    expect(disconnect).toHaveBeenCalledTimes(1);
  });

  it("does not observe when the body element is missing", () => {
    // The empty arm still mounts the body element, so the observer always has
    // a target; this pins that the effect does not bail out for empty rows.
    setSize(0, 0);
    const { observe, disconnect } = stubObserver();
    renderGraph([]);
    expect(observe).toHaveBeenCalledTimes(1);
    expect(disconnect).not.toHaveBeenCalled();
  });

  it("picks up a box that only becomes measurable after mount", async () => {
    setSize(0, 0);
    // The observer callback is assigned asynchronously, so it is kept in an
    // object slot; a bare `let` stays narrowed to `null` at the call site and
    // tsc would reject `trigger?.()` as not callable.
    const triggerRef = { current: null as (() => void) | null };
    vi.stubGlobal(
      "ResizeObserver",
      vi.fn().mockImplementation(function (cb: () => void) {
        triggerRef.current = cb;
        return { observe: vi.fn(), unobserve: vi.fn(), disconnect: vi.fn() };
      }),
    );
    const rows = buildGraphRows([makeNode()]);
    const props = {
      rows,
      laneCount: 1,
      selectedCommit: null,
      onSelect: vi.fn(),
      emptyDescription: "no checkpoints yet",
    };
    const { rerender } = render(<CheckpointGraph {...props} />);
    expect(screen.queryByTestId("virtual-list")).not.toBeInTheDocument();
    setSize(700, 420);
    triggerRef.current?.();
    await screen.findByTestId("virtual-list");
    expect(listSpy.current.width).toBe(700);
    expect(listSpy.current.height).toBe(420);
    rerender(<CheckpointGraph {...props} />);
    expect(screen.getByTestId("virtual-list")).toBeInTheDocument();
  });

  it("keeps rendering the list across a re-render with new rows", async () => {
    setSize(700, 420);
    const { rerender } = renderGraph([makeNode({ commit: "c1", sha: "s1" })]);
    expect(listSpy.current.itemCount).toBe(1);
    rerender(
      <CheckpointGraph
        rows={buildGraphRows([
          makeNode({ commit: "c1", sha: "s1", ref: "r1" }),
          makeNode({
            commit: "c2",
            sha: "s2",
            ref: "r2",
            session_key: "console:b",
          }),
        ])}
        laneCount={2}
        selectedCommit="c2"
        onSelect={vi.fn()}
        emptyDescription="no checkpoints yet"
      />,
    );
    expect(listSpy.current.itemCount).toBe(2);
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });
});
