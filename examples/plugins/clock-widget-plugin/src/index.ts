/**
 * clock-widget-plugin — QwenPaw frontend plugin
 *
 * Demonstrates bundling TWO third-party libraries inside a single plugin:
 *
 *   | Library  | Bundled? | Purpose                                          |
 *   |----------|----------|--------------------------------------------------|
 *   | dayjs    | ✅ yes   | Analog clock, digital time, mini calendar        |
 *   | echarts  | ✅ yes   | Bar chart + pie chart (static mock data)         |
 *   | React    | ❌ no    | From host via window.QwenPaw.host            |
 *   | antd     | ❌ no    | From host via window.QwenPaw.host            |
 *
 * ECharts uses static mock datasets here — no setInterval, no backend calls —
 * to keep the demo focused on the dependency-bundling pattern.
 *
 * Build & Install:
 *   npm install && npm run build
 *   cp -r . ~/.qwenpaw/plugins/clock-widget-plugin
 */

// ── Bundled third-party libs ──────────────────────────────────────────────────
import dayjs from "dayjs";
import * as echarts from "echarts";

// ── Host dependencies (NOT bundled) ──────────────────────────────────────────
const { React, antd } = (window as any).QwenPaw.host;
const { Card, Typography, Row, Col, Tabs, Tag } = antd;
const { Title, Text } = Typography;
const { useState, useEffect, useRef } = React;

// ═════════════════════════════════════════════════════════════════════════════
// SECTION 1 — Analog clock + Calendar (dayjs)
// ═════════════════════════════════════════════════════════════════════════════

const CLOCK_SIZE = 200;
const CENTER = CLOCK_SIZE / 2;
const RADIUS = CENTER - 12;

function drawClock(ctx: CanvasRenderingContext2D, now: dayjs.Dayjs) {
  ctx.clearRect(0, 0, CLOCK_SIZE, CLOCK_SIZE);

  // Face
  ctx.beginPath();
  ctx.arc(CENTER, CENTER, RADIUS, 0, Math.PI * 2);
  ctx.fillStyle = "#1a1b2e";
  ctx.fill();
  ctx.strokeStyle = "#4c8bf5";
  ctx.lineWidth = 3;
  ctx.stroke();

  // Hour marks
  for (let i = 0; i < 12; i++) {
    const angle = (i * Math.PI) / 6 - Math.PI / 2;
    const inner = i % 3 === 0 ? RADIUS - 14 : RADIUS - 8;
    ctx.beginPath();
    ctx.moveTo(
      CENTER + inner * Math.cos(angle),
      CENTER + inner * Math.sin(angle),
    );
    ctx.lineTo(
      CENTER + RADIUS * Math.cos(angle),
      CENTER + RADIUS * Math.sin(angle),
    );
    ctx.strokeStyle = i % 3 === 0 ? "#a0b4e8" : "#4a5080";
    ctx.lineWidth = i % 3 === 0 ? 2.5 : 1.2;
    ctx.stroke();
  }

  const h = now.hour() % 12;
  const m = now.minute();
  const s = now.second();
  drawHand(
    ctx,
    ((h + m / 60) / 12) * Math.PI * 2 - Math.PI / 2,
    RADIUS * 0.52,
    5,
    "#e0e8ff",
  );
  drawHand(
    ctx,
    ((m + s / 60) / 60) * Math.PI * 2 - Math.PI / 2,
    RADIUS * 0.75,
    3.5,
    "#a0c4ff",
  );
  drawHand(
    ctx,
    (s / 60) * Math.PI * 2 - Math.PI / 2,
    RADIUS * 0.82,
    1.5,
    "#f38ba8",
  );

  ctx.beginPath();
  ctx.arc(CENTER, CENTER, 5, 0, Math.PI * 2);
  ctx.fillStyle = "#f38ba8";
  ctx.fill();
}

function drawHand(
  ctx: CanvasRenderingContext2D,
  angle: number,
  length: number,
  width: number,
  color: string,
) {
  ctx.beginPath();
  ctx.moveTo(CENTER, CENTER);
  ctx.lineTo(
    CENTER + length * Math.cos(angle),
    CENTER + length * Math.sin(angle),
  );
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.stroke();
}

function AnalogClock() {
  const canvasRef = useRef(null as HTMLCanvasElement | null);
  const rafRef = useRef(0 as number);

  useEffect(() => {
    const tick = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (ctx) drawClock(ctx, dayjs());
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return React.createElement("canvas", {
    ref: canvasRef,
    width: CLOCK_SIZE,
    height: CLOCK_SIZE,
    style: { borderRadius: "50%", display: "block", margin: "0 auto" },
  });
}

function DigitalTime() {
  const [time, setTime] = useState(() => dayjs().format("HH:mm:ss"));
  useEffect(() => {
    const id = setInterval(() => setTime(dayjs().format("HH:mm:ss")), 1000);
    return () => clearInterval(id);
  }, []);
  return React.createElement(
    "div",
    {
      style: {
        textAlign: "center",
        fontFamily: "'SF Mono', Consolas, monospace",
        fontSize: 26,
        fontWeight: 700,
        color: "#a0c4ff",
        letterSpacing: 3,
        margin: "12px 0 4px",
      },
    },
    time,
  );
}

const CAL_DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function MiniCalendar() {
  const [current, setCurrent] = useState(() => dayjs());
  const today = dayjs();
  const firstDay = current.startOf("month").day();
  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: current.daysInMonth() }, (_, i) => i + 1),
  ];
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  const navBtn = (label: string, onClick: () => void) =>
    React.createElement(
      "button",
      {
        style: {
          background: "none",
          border: "none",
          color: "#4c8bf5",
          fontSize: 18,
          cursor: "pointer",
          padding: "0 6px",
        },
        onClick,
      },
      label,
    );

  return React.createElement(
    "div",
    null,
    React.createElement(
      "div",
      {
        style: {
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        },
      },
      navBtn("‹", () => setCurrent((c: any) => c.subtract(1, "month"))),
      React.createElement(
        Text,
        { strong: true, style: { color: "#cdd6f4" } },
        current.format("MMMM YYYY"),
      ),
      navBtn("›", () => setCurrent((c: any) => c.add(1, "month"))),
    ),
    React.createElement(
      "table",
      {
        style: {
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 13,
          textAlign: "center",
        },
      },
      React.createElement(
        "thead",
        null,
        React.createElement(
          "tr",
          null,
          ...CAL_DAYS.map((d) =>
            React.createElement(
              "th",
              {
                key: d,
                style: {
                  color: "#6c7086",
                  fontWeight: 600,
                  padding: "4px 0",
                  width: "14.28%",
                },
              },
              d,
            ),
          ),
        ),
      ),
      React.createElement(
        "tbody",
        null,
        ...weeks.map((week, wi) =>
          React.createElement(
            "tr",
            { key: wi },
            ...week.map((day, di) => {
              const isToday =
                day !== null &&
                current.year() === today.year() &&
                current.month() === today.month() &&
                day === today.date();
              const isWeekend = di === 0 || di === 6;
              return React.createElement(
                "td",
                {
                  key: di,
                  style: {
                    padding: "4px 0",
                    borderRadius: 4,
                    color:
                      day === null
                        ? "transparent"
                        : isToday
                        ? "#1e1e2e"
                        : isWeekend
                        ? "#f38ba8"
                        : "#cdd6f4",
                    background: isToday ? "#4c8bf5" : "transparent",
                    fontWeight: isToday ? 700 : 400,
                  },
                },
                day ?? "",
              );
            }),
          ),
        ),
      ),
    ),
  );
}

function ClockPanel() {
  const cardStyle = {
    background: "#1e1e2e",
    border: "1px solid #313244",
    borderRadius: 12,
  };
  const headStyle = {
    background: "#181825",
    borderBottom: "1px solid #313244",
  };
  return React.createElement(
    Row,
    { gutter: 16 },
    React.createElement(
      Col,
      { span: 10 },
      React.createElement(
        Card,
        { style: cardStyle, bodyStyle: { padding: "20px 16px" } },
        React.createElement(AnalogClock),
        React.createElement(DigitalTime),
        React.createElement(
          "div",
          {
            style: {
              textAlign: "center",
              fontSize: 11,
              color: "#6c7086",
              marginTop: 4,
            },
          },
          "dayjs v",
          React.createElement(
            "span",
            { style: { color: "#a6e3a1" } },
            (dayjs as any).version ?? "1.x",
          ),
          " — bundled",
        ),
      ),
    ),
    React.createElement(
      Col,
      { span: 14 },
      React.createElement(
        Card,
        {
          style: cardStyle,
          bodyStyle: { padding: "20px 16px" },
          title: React.createElement(
            "span",
            { style: { color: "#cdd6f4" } },
            "📅 " + dayjs().format("YYYY"),
          ),
          headStyle,
        },
        React.createElement(MiniCalendar),
      ),
    ),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// SECTION 2 — ECharts (static mock data)
// ═════════════════════════════════════════════════════════════════════════════

// Mock datasets — fixed, no live ticking
const MOCK_BAR = {
  months: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
  requests: [1200, 1900, 1500, 2400, 1800, 2700],
  errors: [45, 30, 60, 20, 55, 15],
};

const MOCK_PIE = [
  { name: "Provider A", value: 38 },
  { name: "Provider B", value: 27 },
  { name: "Provider C", value: 19 },
  { name: "Provider D", value: 11 },
  { name: "Others", value: 5 },
];

const DARK_BG = "#1e1e2e";
const GRID_COLOR = "#313244";
const TEXT_COLOR = "#a6adc8";

function barOption() {
  return {
    backgroundColor: DARK_BG,
    color: ["#89b4fa", "#f38ba8"],
    grid: { top: 48, bottom: 36, left: 52, right: 16 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#313244",
      borderColor: "#45475a",
      textStyle: { color: "#cdd6f4" },
    },
    legend: { top: 8, textStyle: { color: TEXT_COLOR } },
    xAxis: {
      type: "category",
      data: MOCK_BAR.months,
      axisLine: { lineStyle: { color: GRID_COLOR } },
      axisLabel: { color: TEXT_COLOR },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: GRID_COLOR } },
      axisLabel: { color: TEXT_COLOR },
      splitLine: { lineStyle: { color: GRID_COLOR, type: "dashed" } },
    },
    series: [
      {
        name: "Requests",
        type: "bar",
        data: MOCK_BAR.requests,
        barMaxWidth: 32,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "Errors",
        type: "bar",
        data: MOCK_BAR.errors,
        barMaxWidth: 32,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
      },
    ],
  };
}

function pieOption() {
  return {
    backgroundColor: DARK_BG,
    color: ["#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8", "#cba6f7"],
    tooltip: {
      trigger: "item",
      backgroundColor: "#313244",
      borderColor: "#45475a",
      textStyle: { color: "#cdd6f4" },
      formatter: "{b}: {d}%",
    },
    legend: {
      orient: "vertical",
      right: 16,
      top: "center",
      textStyle: { color: TEXT_COLOR },
    },
    series: [
      {
        name: "Share",
        type: "pie",
        radius: ["38%", "68%"],
        center: ["36%", "50%"],
        itemStyle: { borderRadius: 6, borderColor: DARK_BG, borderWidth: 2 },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 14,
            fontWeight: "bold",
            color: "#cdd6f4",
          },
        },
        data: MOCK_PIE,
      },
    ],
  };
}

function EChart({ option, height = 260 }: { option: object; height?: number }) {
  const ref = useRef(null as HTMLDivElement | null);
  const chartRef = useRef(null as echarts.ECharts | null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, null, { renderer: "canvas" });
    chart.setOption(option);
    chartRef.current = chart;
    return () => {
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // Re-apply if option changes
  useEffect(() => {
    chartRef.current?.setOption(option);
  }, [option]);

  return React.createElement("div", { ref, style: { width: "100%", height } });
}

function ChartsPanel() {
  const cardStyle = {
    background: "#1e1e2e",
    border: "1px solid #313244",
    borderRadius: 12,
  };
  const headStyle = {
    background: "#181825",
    borderBottom: "1px solid #313244",
  };
  const titleText = (t: string) =>
    React.createElement(
      "span",
      { style: { color: "#cdd6f4", fontSize: 13 } },
      t,
    );

  return React.createElement(
    Row,
    { gutter: 16 },
    React.createElement(
      Col,
      { span: 14 },
      React.createElement(
        Card,
        {
          style: cardStyle,
          bodyStyle: { padding: "8px 4px 4px" },
          title: titleText("Monthly Requests vs Errors (mock)"),
          headStyle,
        },
        React.createElement(EChart, { option: barOption() }),
      ),
    ),
    React.createElement(
      Col,
      { span: 10 },
      React.createElement(
        Card,
        {
          style: cardStyle,
          bodyStyle: { padding: "8px 4px 4px" },
          title: titleText("Provider Share (mock)"),
          headStyle,
        },
        React.createElement(EChart, { option: pieOption() }),
      ),
    ),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// SECTION 3 — Dependency info panel
// ═════════════════════════════════════════════════════════════════════════════

function DepInfo() {
  const row = (name: string, source: string, color: string, note: string) =>
    React.createElement(
      "div",
      {
        style: {
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          marginBottom: 4,
          fontSize: 13,
        },
      },
      React.createElement("code", { style: { color, minWidth: 90 } }, name),
      React.createElement(
        Tag,
        { color: source === "bundled" ? "green" : "blue" },
        source,
      ),
      React.createElement("span", { style: { color: "#6c7086" } }, note),
    );

  return React.createElement(
    "div",
    {
      style: {
        background: "#181825",
        border: "1px solid #313244",
        borderRadius: 8,
        padding: "12px 18px",
        marginBottom: 20,
      },
    },
    React.createElement(
      Text,
      {
        strong: true,
        style: { color: "#89b4fa", display: "block", marginBottom: 8 },
      },
      "Dependency contract",
    ),
    row(
      "dayjs",
      "bundled",
      "#a6e3a1",
      "date/time utilities — pure JS, bundled into dist/index.js",
    ),
    row(
      "echarts",
      "bundled",
      "#f9e2af",
      "chart library — pure JS, bundled into dist/index.js",
    ),
    row(
      "React",
      "host",
      "#cba6f7",
      "from window.QwenPaw.host — never duplicated",
    ),
    row(
      "antd",
      "host",
      "#cba6f7",
      "from window.QwenPaw.host — never duplicated",
    ),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// SECTION 4 — Main page
// ═════════════════════════════════════════════════════════════════════════════

function ChartWidgetPage() {
  return React.createElement(
    "div",
    { style: { padding: "28px 32px", maxWidth: 980, margin: "0 auto" } },
    React.createElement(
      Title,
      { level: 3, style: { color: "#cdd6f4", marginBottom: 16 } },
      "🧩 Clock + Chart Widget Plugin",
    ),
    React.createElement(DepInfo),
    React.createElement(Tabs, {
      defaultActiveKey: "clock",
      style: { color: "#cdd6f4" },
      items: [
        {
          key: "clock",
          label: "🕐 Clock & Calendar",
          children: React.createElement(ClockPanel),
        },
        {
          key: "charts",
          label: "📊 ECharts (mock data)",
          children: React.createElement(ChartsPanel),
        },
      ],
    }),
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Plugin registration
// ═════════════════════════════════════════════════════════════════════════════

class ClockWidgetPlugin {
  readonly id = "clock-widget-plugin";

  setup(): void {
    (window as any).QwenPaw.registerRoutes?.(this.id, [
      {
        path: "/plugin/clock-widget-plugin",
        component: ChartWidgetPage,
        label: "Widget Demo",
        icon: "🧩",
        priority: 30,
      },
    ]);
  }
}

new ClockWidgetPlugin().setup();
