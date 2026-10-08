import { useTranslation } from "react-i18next";
import { useEffect, useRef } from "react";
import Plotly from "plotly.js-basic-dist-min";
import type { Data, Layout, PlotlyHTMLElement } from "plotly.js";
import { logo, money as formatMoney, type Row } from "./types";

const escape = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
const group = (row: Row, privateView: boolean) =>
  privateView ? `${row.model}/${row.harness}` : row.model;
export function bestRows(rows: Row[], privateView: boolean): Set<string> {
  const best = new Map<string, Row>();
  for (const row of rows.filter((r) => r.score !== null)) {
    const key = group(row, privateView),
      previous = best.get(key);
    if (
      !previous ||
      row.score! > previous.score! ||
      (row.score === previous.score &&
        (row.cost ?? Infinity) < (previous.cost ?? Infinity)) ||
      (row.score === previous.score &&
        row.cost === previous.cost &&
        row.run.date > previous.run.date)
    )
      best.set(key, row);
  }
  return new Set([...best.values()].map((row) => row.id));
}
export function frontier(rows: Row[]): Row[] {
  return rows
    .filter(
      (r) => r.score !== null && r.cost !== null && r.cost > 0 && !r.upperBound,
    )
    .filter(
      (r, _, candidates) =>
        !candidates.some(
          (other) =>
            other.cost! <= r.cost! &&
            other.score! >= r.score! &&
            (other.cost! < r.cost! || other.score! > r.score!),
        ),
    )
    .sort((a, b) => a.cost! - b.cost!);
}
export default function Chart({
  rows,
  title,
  privateView,
  history,
  demo,
  onSelect,
}: {
  rows: Row[];
  title: string;
  privateView: boolean;
  history: boolean;
  demo: boolean;
  onSelect: (row: Row) => void;
}) {
  const { t, i18n } = useTranslation("evaluation");
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = container.current!;
    const money = (value: number | null) =>
      formatMoney(value, i18n.language, t("unknown"));
    const number = (value: number) =>
      new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 3 }).format(
        value,
      );
    const best = bestRows(rows, privateView);
    const shown = rows.filter(
      (r) => r.score !== null && (history || best.has(r.id)),
    );
    const known = shown.filter((r) => r.cost !== null && r.cost > 0);
    const missing = shown.filter((r) => r.cost === null || r.cost === 0);
    const pareto = frontier(shown.filter((r) => best.has(r.id)));
    const low = known.length
      ? Math.log10(Math.min(...known.map((r) => r.cost!))) - 0.22
      : -2;
    const high = known.length
      ? Math.log10(Math.max(...known.map((r) => r.cost!))) + 0.22
      : 1;
    const mobile = element.clientWidth < 700;
    const tip = (r: Row) =>
      `<b>${escape(r.model)}</b><br>${escape(r.harness)} · SDK ${escape(
        r.sdk_version,
      )}` +
      `<br>${escape(t("score"))}: ${number(r.score!)}<br>${escape(
        t("averageCost"),
      )}: ${money(r.cost)}${
        r.upperBound ? ` (${escape(t("upperBound"))})` : ""
      }` +
      `<br>${escape(t("averageRuntime"))}: ${
        r.runtime === null
          ? t("unknown")
          : t("seconds", { value: number(Math.round(r.runtime)) })
      }` +
      `<br>${escape(
        new Intl.DateTimeFormat(i18n.language, {
          dateStyle: "medium",
          timeZone: "UTC",
        }).format(new Date(r.run.date)),
      )} · ${best.has(r.id) ? t("bestShort") : t("history")}` +
      `${demo ? `<br>${escape(t("mockShort"))}` : ""}`;
    const traces: Data[] = [];
    const images: Partial<Plotly.Image>[] = [];
    for (const [points, missingCost] of [
      [known, false],
      [missing, true],
    ] as const) {
      traces.push({
        type: "scatter",
        mode: "markers",
        xaxis: missingCost ? "x2" : "x",
        x: points.map((r, i) => (missingCost ? 0.2 + (i % 4) * 0.19 : r.cost!)),
        y: points.map((r) => r.score!),
        text: points.map(tip),
        customdata: points.map((r) => r.id),
        hovertemplate: "%{text}<extra></extra>",
        marker: { size: 27, color: "rgba(0,0,0,0)" },
        showlegend: false,
      });
      points.forEach((r, i) =>
        images.push({
          source: logo(r.model),
          xref: missingCost ? "x2" : "x",
          yref: "y",
          x: missingCost ? 0.2 + (i % 4) * 0.19 : Math.log10(r.cost!),
          y: r.score!,
          sizex: missingCost ? 0.2 : (high - low) * (mobile ? 0.055 : 0.027),
          sizey: 3,
          xanchor: "center",
          yanchor: "middle",
          sizing: "contain",
          layer: "above",
          opacity: best.has(r.id) ? 1 : 0.23,
        }),
      );
    }
    traces.unshift({
      type: "scatter",
      mode: "lines",
      x: pareto.map((r) => r.cost!),
      y: pareto.map((r) => r.score!),
      hoverinfo: "skip",
      line: { color: "#e3be54", width: 2, dash: "dash" },
      showlegend: false,
    });
    const layout: Partial<Layout> = {
      autosize: true,
      paper_bgcolor: "#fff",
      plot_bgcolor: "#fff",
      margin: { l: mobile ? 48 : 78, r: mobile ? 18 : 46, t: 92, b: 100 },
      title: {
        text: escape(t("chartTitle", { title })),
        x: 0.035,
        y: 0.955,
        font: { size: mobile ? 16 : 23 },
      },
      font: {
        family: "Geist Variable, Arial, sans-serif",
        color: "#242832",
        size: 12,
      },
      xaxis: {
        type: "log",
        range: [low, high],
        domain: [0, missing.length ? 0.87 : 1],
        title: { text: t("xAxis"), standoff: 22 },
        tickprefix: "$",
        gridcolor: "#e8edf5",
        zeroline: false,
      },
      xaxis2: {
        domain: [0.92, 1],
        range: [0, 1],
        visible: false,
        anchor: "y",
        fixedrange: true,
      },
      yaxis: {
        range: [
          shown.length
            ? Math.max(
                0,
                Math.floor((Math.min(...shown.map((r) => r.score!)) - 8) / 10) *
                  10,
              )
            : 0,
          103,
        ],
        title: { text: t("averageScore"), standoff: 18 },
        gridcolor: "#e8edf5",
        dtick: 10,
        zeroline: false,
      },
      images,
      hovermode: "closest",
      hoverdistance: 25,
      hoverlabel: {
        bgcolor: "#242832",
        bordercolor: "#242832",
        font: { color: "white", size: 13 },
        align: "left",
      },
      showlegend: false,
      dragmode: "zoom",
      annotations: [
        ...pareto.map((row) => ({
          text: escape(row.model),
          xref: "x" as const,
          yref: "y" as const,
          x: Math.log10(row.cost!),
          y: row.score!,
          yshift: 24,
          showarrow: false,
          font: { size: mobile ? 9 : 11 },
        })),
        {
          text: "QwenPaw",
          xref: "paper",
          yref: "paper",
          x: 0,
          y: mobile ? -0.3 : -0.15,
          showarrow: false,
          xanchor: "left",
          font: { size: 18 },
        },
        {
          text: demo ? t("mockShort") : t("sdkHistory"),
          xref: "paper",
          yref: "paper",
          x: 1,
          y: mobile ? -0.3 : -0.15,
          showarrow: false,
          xanchor: "right",
          font: { color: "#8c929d", size: 10 },
        },
        ...(missing.length
          ? [
              {
                text: t("noCost"),
                xref: "paper" as const,
                yref: "paper" as const,
                x: 1,
                y: 1.05,
                showarrow: false,
                xanchor: "right" as const,
                font: { size: 10 },
              },
            ]
          : []),
        ...(!shown.length
          ? [
              {
                text: t("noComplete"),
                xref: "paper" as const,
                yref: "paper" as const,
                x: 0.5,
                y: 0.5,
                showarrow: false,
                font: { size: 18, color: "#9196a1" },
              },
            ]
          : []),
      ],
      shapes: missing.length
        ? [
            {
              type: "line",
              xref: "paper",
              yref: "paper",
              x0: 0.895,
              x1: 0.895,
              y0: 0,
              y1: 1,
              line: { color: "#bcc4d1", dash: "dot" },
            },
          ]
        : [],
    };
    let disposed = false;
    void Plotly.newPlot(element, traces, layout, {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["select2d", "lasso2d"],
      toImageButtonOptions: {
        filename: "qwenpaw-evaluation",
        format: "png",
        height: 800,
        width: 1600,
        scale: 2,
      },
    }).then((plot: PlotlyHTMLElement) => {
      if (disposed) return;
      plot.on("plotly_click", (event) => {
        const row = shown.find((r) => r.id === event.points[0]?.customdata);
        if (row) onSelect(row);
      });
    });
    const observer = new ResizeObserver(() => {
      if (!disposed) void Plotly.Plots.resize(element);
    });
    observer.observe(element);
    return () => {
      disposed = true;
      observer.disconnect();
      Plotly.purge(element);
    };
  }, [rows, title, privateView, history, demo, onSelect, t, i18n.language]);
  return (
    <div
      className="evaluation-plot"
      ref={container}
      role="img"
      aria-label={t("chartAlt", { title })}
    />
  );
}
