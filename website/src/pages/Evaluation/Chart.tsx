import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Download,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { bestRows, frontier } from "./metrics";
import Dot from "./Dot";
import HarnessMark from "./HarnessMark";
import { harnessLabel, logo, money, type Row } from "./types";

export default function Chart({
  rows,
  title,
  compareHarnesses,
  history,
  markerStyle,
  onSelect,
}: {
  rows: Row[];
  title: string;
  compareHarnesses: boolean;
  history: boolean;
  markerStyle: "dots" | "logos";
  onSelect: (row: Row) => void;
}) {
  const { t, i18n } = useTranslation("evaluation");
  const container = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(1000);
  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState({ zoom: 1, offset: 0 });
  const [panning, setPanning] = useState(false);
  const drag = useRef<{
    pointerId: number;
    x: number;
    offset: number;
  } | null>(null);
  const dragged = useRef(false);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.observe(container.current!);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    setView({ zoom: 1, offset: 0 });
    drag.current = null;
    setPanning(false);
    setHovered(null);
  }, [rows, history, compareHarnesses]);
  const mobile = width < 700;
  const height = mobile ? 380 : 520;
  const left = mobile ? 48 : 78,
    right = width - (mobile ? 18 : 46);
  const top = mobile ? 116 : 66,
    bottom = height - 64;
  const best = bestRows(rows, compareHarnesses);
  const shown = rows
    .filter((r) => r.score !== null && (history || best.has(r.id)))
    .sort((a, b) => Number(best.has(a.id)) - Number(best.has(b.id)));
  const sdkVersions = shown
    .map((row) => row.sdk_version)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const latestVersion = sdkVersions[sdkVersions.length - 1];
  const known = shown.filter((r) => r.cost !== null && r.cost > 0);
  const missing = shown.filter((r) => r.cost === null || r.cost === 0);
  const end = missing.length ? left + (right - left) * 0.87 : right;
  const min = known.length
    ? Math.log10(Math.min(...known.map((r) => r.cost!)))
    : -2;
  const max = known.length
    ? Math.log10(Math.max(...known.map((r) => r.cost!)))
    : 1;
  const { zoom } = view;
  const range = (max - min + (known.length ? 0.44 : 0)) / zoom;
  const maxOffset = ((max - min) * (1 - 1 / zoom)) / 2;
  const offset = Math.max(-maxOffset, Math.min(maxOffset, view.offset));
  const center = (min + max) / 2 + offset,
    low = center - range / 2,
    high = center + range / 2;
  const updateView = (nextZoom: number, nextOffset = offset) => {
    const zoom = Math.max(1, Math.min(8, nextZoom));
    const limit = ((max - min) * (1 - 1 / zoom)) / 2;
    setView({ zoom, offset: Math.max(-limit, Math.min(limit, nextOffset)) });
  };
  const finishPan = () => {
    drag.current = null;
    setPanning(false);
  };
  const floor = shown.length
    ? Math.max(
        0,
        Math.floor((Math.min(...shown.map((r) => r.score!)) - 8) / 10) * 10,
      )
    : 0;
  const x = (cost: number) =>
    left + ((Math.log10(cost) - low) / (high - low)) * (end - left);
  const y = (score: number) =>
    bottom - ((score - floor) / (103 - floor)) * (bottom - top);
  const position = (r: Row) =>
    r.cost !== null && r.cost > 0
      ? x(r.cost)
      : end + (right - end) * (0.4 + (missing.indexOf(r) % 4) * 0.18);
  const pareto = frontier(shown).filter((r) => r.cost! > 0);
  const ticks: number[] = [];
  for (
    let exponent = Math.floor(low);
    exponent <= Math.ceil(high);
    exponent++
  ) {
    for (const n of [1, 2, 3, 5]) {
      const cost = n * 10 ** exponent;
      if (Math.log10(cost) >= low && Math.log10(cost) <= high) ticks.push(cost);
    }
  }
  const number = (value: number) =>
    new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 3 }).format(
      value,
    );
  const active = shown.find((r) => r.id === hovered);
  const pointAt = (event: { clientX: number; clientY: number }) => {
    const bounds = svg.current!.getBoundingClientRect();
    const pointerX = ((event.clientX - bounds.left) * width) / bounds.width;
    const pointerY = ((event.clientY - bounds.top) * height) / bounds.height;
    let nearest: Row | undefined;
    let distance = 22;
    for (const row of shown) {
      if (position(row) < left - 16 || position(row) > right + 16) continue;
      const dx = pointerX - position(row);
      const dy = pointerY - y(row.score!);
      const next =
        markerStyle === "dots"
          ? Math.hypot(dx, dy)
          : Math.min(Math.hypot(dx, dy + 16), Math.hypot(dx, dy - 15));
      if (next < distance) {
        nearest = row;
        distance = next;
      }
    }
    return nearest;
  };
  const marker = (row: Row) =>
    markerStyle === "dots" ? (
      <Dot model={row.model} harness={row.harness} />
    ) : (
      <g pointerEvents="none">
        <image href={logo(row.model)} x={-16} y={-32} width={32} height={32} />
        <HarnessMark
          row={row}
          historical={row.sdk_version !== latestVersion}
          className="evaluation-plot-harness"
          x={-14}
          y={1}
          size={28}
        />
      </g>
    );
  const exportImage = async () => {
    const copy = svg.current!.cloneNode(true) as SVGSVGElement;
    const style = getComputedStyle(container.current!);
    copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    copy.style.color = style.getPropertyValue("--eval-text");
    copy.style.background = style.getPropertyValue("--eval-surface");
    for (const name of ["--eval-border", "--eval-accent", "--eval-surface"])
      copy.style.setProperty(name, style.getPropertyValue(name));
    await Promise.all(
      Array.from(copy.querySelectorAll("image")).map(async (image) => {
        const response = await fetch(image.getAttribute("href")!);
        const blob = await response.blob();
        const data = await new Promise<string>((resolve) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result as string);
          reader.readAsDataURL(blob);
        });
        image.setAttribute("href", data);
      }),
    );
    const url = URL.createObjectURL(
      new Blob([new XMLSerializer().serializeToString(copy)], {
        type: "image/svg+xml",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "qwenpaw-evaluation.svg";
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div
      className="evaluation-plot evaluation-svg-chart"
      ref={container}
      data-zoomed={zoom > 1}
      data-panning={panning}
    >
      <div className="evaluation-chart-tools">
        <button
          aria-label={t("zoomIn")}
          title={t("zoomIn")}
          disabled={zoom === 8}
          onClick={() => updateView(zoom * 1.5)}
        >
          <ZoomIn size={16} />
        </button>
        <button
          aria-label={t("zoomOut")}
          title={t("zoomOut")}
          disabled={zoom === 1}
          onClick={() => updateView(zoom / 1.5)}
        >
          <ZoomOut size={16} />
        </button>
        <button
          aria-label={t("panLeft")}
          title={t("panLeft")}
          disabled={offset <= -maxOffset}
          onClick={() => updateView(zoom, offset - range / 4)}
        >
          <ArrowLeft size={16} />
        </button>
        <button
          aria-label={t("panRight")}
          title={t("panRight")}
          disabled={offset >= maxOffset}
          onClick={() => updateView(zoom, offset + range / 4)}
        >
          <ArrowRight size={16} />
        </button>
        <button
          aria-label={t("resetChart")}
          title={t("resetChart")}
          onClick={() => updateView(1, 0)}
        >
          <RotateCcw size={16} />
        </button>
        <button
          aria-label={t("exportChart")}
          title={t("exportChart")}
          onClick={() => void exportImage()}
        >
          <Download size={16} />
        </button>
      </div>
      <svg
        ref={svg}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={t("chartAlt", { title })}
        onDoubleClick={() => updateView(1, 0)}
        onPointerDown={(event) => {
          if (!event.isPrimary || event.button !== 0) return;
          dragged.current = false;
          setHovered(pointAt(event)?.id ?? null);
          if (zoom === 1) return;
          drag.current = {
            pointerId: event.pointerId,
            x: event.clientX,
            offset,
          };
          (event.target as Element).setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const start = drag.current;
          if (!start || start.pointerId !== event.pointerId) {
            setHovered(pointAt(event)?.id ?? null);
            return;
          }
          const delta = event.clientX - start.x;
          if (!dragged.current && Math.abs(delta) < 4) {
            setHovered(pointAt(event)?.id ?? null);
            return;
          }
          dragged.current = true;
          setPanning(true);
          setHovered(null);
          const scale =
            width / event.currentTarget.getBoundingClientRect().width;
          updateView(
            zoom,
            start.offset - (delta * scale * range) / (end - left),
          );
        }}
        onPointerLeave={() => setHovered(null)}
        onClick={(event) => {
          const row = pointAt(event);
          if (row) onSelect(row);
        }}
        onPointerUp={finishPan}
        onPointerCancel={finishPan}
        onLostPointerCapture={finishPan}
        onClickCapture={(event) => {
          if (!dragged.current) return;
          event.preventDefault();
          event.stopPropagation();
          dragged.current = false;
        }}
      >
        <text x={mobile ? 16 : 28} y={28} fontSize={mobile ? 13 : 16}>
          {mobile ? (
            <>
              <tspan x={16}>QwenPaw {title}</tspan>
              <tspan x={16} dy={18}>
                {t("chartMeasure")}
              </tspan>
            </>
          ) : (
            t("chartTitle", { title })
          )}
        </text>
        {ticks.map((cost) => (
          <g key={cost}>
            <line
              x1={x(cost)}
              x2={x(cost)}
              y1={top}
              y2={bottom}
              stroke="var(--eval-border)"
            />
            <text x={x(cost)} y={bottom + 22} textAnchor="middle" fontSize={11}>
              {money(cost, i18n.language, t("unknown"))}
            </text>
          </g>
        ))}
        {Array.from(
          { length: (100 - floor) / 10 + 1 },
          (_, i) => floor + i * 10,
        ).map((score) => (
          <g key={score}>
            <line
              x1={left}
              x2={right}
              y1={y(score)}
              y2={y(score)}
              stroke="var(--eval-border)"
            />
            <text x={left - 12} y={y(score) + 4} textAnchor="end" fontSize={12}>
              {score}
            </text>
          </g>
        ))}
        <text
          x={(left + end) / 2}
          y={height - 12}
          textAnchor="middle"
          fontSize={mobile ? 11 : 14}
        >
          {t("xAxis")}
        </text>
        <text
          transform={`translate(18 ${(top + bottom) / 2}) rotate(-90)`}
          textAnchor="middle"
          fontSize={mobile ? 11 : 14}
        >
          {t("averageScore")}
        </text>
        {missing.length > 0 && (
          <>
            <line
              x1={end + 12}
              x2={end + 12}
              y1={top}
              y2={bottom}
              stroke="var(--eval-border)"
              strokeDasharray="3 4"
            />
            <text x={right} y={top - 14} textAnchor="end" fontSize={10}>
              {t("noCost")}
            </text>
          </>
        )}
        <svg
          x={left - 16}
          y={top - 30}
          width={right - left + 32}
          height={bottom - top + 46}
          viewBox={`${left - 16} ${top - 30} ${right - left + 32} ${
            bottom - top + 46
          }`}
        >
          <polyline
            points={pareto.map((r) => `${x(r.cost!)},${y(r.score!)}`).join(" ")}
            fill="none"
            stroke="var(--eval-accent)"
            strokeWidth={1.5}
            strokeDasharray="7 6"
          />
          {shown.map((r) => (
            <g
              key={r.id}
              className="evaluation-chart-point"
              tabIndex={0}
              role="button"
              aria-label={`${r.model} · ${t(harnessLabel(r.harness))} · v${
                r.sdk_version
              }: ${number(r.score!)}`}
              data-mode={r.harness}
              data-sdk={r.sdk_version}
              opacity={best.has(r.id) ? 1 : 0.55}
              onFocus={() => setHovered(r.id)}
              onBlur={() => setHovered(null)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  if (!e.repeat) onSelect(r);
                } else if (e.key === "Escape") setHovered(null);
              }}
            >
              <circle
                className="evaluation-point-hit"
                cx={position(r)}
                cy={y(r.score!)}
                r={22}
                fill="transparent"
              />
              <g
                transform={`translate(${position(r)},${y(r.score!)})`}
                opacity={active?.id === r.id ? 0 : 1}
                pointerEvents="none"
              >
                {marker(r)}
              </g>
            </g>
          ))}
          {active && (
            <g
              transform={`translate(${position(active)},${y(active.score!)})`}
              pointerEvents="none"
              aria-hidden="true"
            >
              <g className="evaluation-marker-raised">{marker(active)}</g>
            </g>
          )}
        </svg>
        {!shown.length && (
          <text x={width / 2} y={height / 2} textAnchor="middle">
            {t("noComplete")}
          </text>
        )}
      </svg>
      {active && (
        <div
          role="tooltip"
          className="evaluation-point-tooltip"
          style={{
            left: Math.max(
              8,
              Math.min(
                width - Math.min(330, width - 16) - 8,
                position(active) + 20,
              ),
            ),
            top: Math.max(82, Math.min(y(active.score!) - 80, height - 160)),
          }}
        >
          <div className="evaluation-tooltip-record">
            <div className="evaluation-tooltip-heading">
              <img src={logo(active.model)} alt="" />
              <div>
                <strong>{active.model}</strong>
                <small>
                  {t(harnessLabel(active.harness))} · v{active.sdk_version}
                </small>
              </div>
              <HarnessMark
                row={active}
                historical={active.sdk_version !== latestVersion}
                className="evaluation-tooltip-harness"
              />
            </div>
            <div>
              {t("score")}: {number(active.score!)} · {t("cost")}:{" "}
              {money(active.cost, i18n.language, t("unknown"))}
              {active.upperBound ? ` (${t("upperBound")})` : ""}
            </div>
            {active.partialCost && (
              <div>
                {t("costCoverage", {
                  known: active.costKnown,
                  total: active.costTotal,
                })}
              </div>
            )}
            <small>
              {active.runtime === null
                ? t("unknown")
                : t("seconds", { value: number(Math.round(active.runtime)) })}
              {" · "}
              {new Intl.DateTimeFormat(i18n.language, {
                dateStyle: "medium",
                timeZone: "UTC",
              }).format(new Date(active.run.date))}
            </small>
          </div>
        </div>
      )}
    </div>
  );
}
