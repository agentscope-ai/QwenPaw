/**
 * CloudPaw frontend plugin for QwenPaw
 *
 * Registers custom tool renderers for:
 * - proposal_choice: interactive resource proposal tables with confirm/adjust
 * - manage_prd: interactive PRD display (auto-rendered after each manage_prd call)
 *
 * Uses window.QwenPaw plugin API (PR #3512+)
 */

function buildPlugin() {
  const { React, antd, antdIcons, getApiUrl, getApiToken } = (window as any)
    .QwenPaw.host;
  const {
    Card,
    Table,
    Tag,
    Typography,
    Space,
    Button,
    Input,
    Radio,
    Collapse,
    Descriptions,
    Tooltip,
    Spin,
    message: antdMessage,
  } = antd;
  const { Text } = Typography;
  const { TextArea } = Input;
  const { useState, useMemo, useCallback, useRef } = React;
  const {
    InfoCircleOutlined,
    DownOutlined,
    RightOutlined,
    CheckCircleOutlined,
    FieldTimeOutlined,
    FileTextOutlined,
  } = antdIcons || {};

  // ── Helpers ──────────────────────────────────────────────────────────

  function parseToolArgs(data: any): Record<string, any> {
    const firstData = data?.content?.[0]?.data;
    const rawArgs = firstData?.arguments;
    if (typeof rawArgs === "string") {
      try {
        return JSON.parse(rawArgs);
      } catch {
        return {};
      }
    }
    return rawArgs ?? {};
  }

  function getSessionId(): string | null {
    return (window as any).currentSessionId ?? null;
  }

  function getCellString(value: any): string {
    if (typeof value === "string") return value;
    if (value && typeof value === "object" && "text" in value)
      return value.text;
    return String(value ?? "");
  }

  function isEmptyCost(value: any): boolean {
    if (value === null || value === undefined) return true;
    const str = getCellString(value).trim();
    if (!str) return true;
    if (/^[¥$]?0+(\.0+)?$/.test(str) || /^[-–—]+$/.test(str)) return true;
    return false;
  }

  async function resolveInteraction(
    sessionId: string,
    result: string,
  ): Promise<boolean> {
    try {
      const token = getApiToken();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(getApiUrl("/interaction"), {
        method: "POST",
        headers,
        body: JSON.stringify({ session_id: sessionId, result }),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  function extractOutputText(output: any): string | null {
    if (!output) return null;
    if (typeof output === "string") {
      try {
        const parsed = JSON.parse(output);
        if (Array.isArray(parsed)) {
          const textBlock = parsed.find(
            (b: any) => b?.type === "text" && b?.text,
          );
          return textBlock?.text ?? null;
        }
        if (typeof parsed === "string") return parsed;
      } catch {
        return output;
      }
    }
    if (Array.isArray(output)) {
      const textBlock = output.find((b: any) => b?.type === "text" && b?.text);
      return textBlock?.text ?? null;
    }
    return null;
  }

  function parseCompletedResult(content: any[]): string | null {
    if (!content || content.length < 2) return null;
    const output = content[1]?.data?.output;
    const text = extractOutputText(output);
    if (!text) return null;
    if (text.startsWith("Error:")) return text;
    const confirmMatch = text.match(/^用户选择了「(.+?)」并确认部署$/);
    if (confirmMatch) return `已确认部署「${confirmMatch[1]}」`;
    const adjustWithChoice = text.match(
      /^用户选择「(.+?)」并要求调整[：:](.+)$/,
    );
    if (adjustWithChoice)
      return `已选择「${adjustWithChoice[1]}」并调整：${adjustWithChoice[2]}`;
    if (text === "用户确认部署") return "已确认部署";
    const adjustLegacy = text.match(/^用户要求调整资源[：:](.+)$/);
    if (adjustLegacy) return `已反馈调整意见：${adjustLegacy[1]}`;
    return "已确认";
  }

  // ── proposal_choice renderer ─────────────────────────────────────────

  const TABLE_HEADERS = [
    "资源类型",
    "资源用途",
    "规格",
    "地域",
    "数量",
    "计费方式",
    "时长",
    "原价",
    "优惠",
    "预估算费用",
  ];

  const HEADER_KEYWORDS = new Set(
    TABLE_HEADERS.map((h: string) => h.toLowerCase()),
  );

  function isHeaderRow(row: any[]): boolean {
    if (!Array.isArray(row) || row.length !== 10) return false;
    const first = getCellString(row[0]).trim().toLowerCase();
    return HEADER_KEYWORDS.has(first);
  }

  function isSummaryRowCheck(row: any[]): boolean {
    if (!Array.isArray(row) || row.length !== 10) return false;
    const first = getCellString(row[0]).trim();
    return /^(合计|总计|total)/i.test(first);
  }

  function splitFlatRowsIntoProposals(rows: any[][]): any[][][] {
    const proposals: any[][][] = [];
    let current: any[][] = [];
    for (const row of rows) {
      current.push(row);
      if (isSummaryRowCheck(row)) {
        proposals.push(current);
        current = [];
      }
    }
    if (current.length > 0) {
      if (proposals.length > 0) {
        proposals[proposals.length - 1].push(...current);
      } else {
        proposals.push(current);
      }
    }
    return proposals.length > 0 ? proposals : [rows];
  }

  function renderCellValue(cell: any) {
    if (typeof cell === "string") return cell;
    if (cell && typeof cell === "object" && cell.text) {
      if (cell.url) {
        return React.createElement(
          "a",
          {
            href: cell.url,
            target: "_blank",
            rel: "noopener noreferrer",
          },
          cell.text,
        );
      }
      return cell.text;
    }
    return String(cell ?? "");
  }

  function ProposalChoiceRender({ data }: { data: any }) {
    const [actionType, setActionType] = useState("confirm");
    const [adjustText, setAdjustText] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
    const [expandedCards, setExpandedCards] = useState<Record<number, boolean>>(
      {},
    );
    // Use ref to survive re-renders from SSE data updates
    const submittedRef = React.useRef(false);
    const submitResultRef = React.useRef<string | null>(null);
    const [, forceUpdate] = useState(0);

    const content = data?.content;
    const hasOutput =
      content && content.length >= 2 && content[1]?.data?.output;

    const completedFromServer = useMemo(
      () => parseCompletedResult(content),
      [content],
    );

    const isCompleted =
      submittedRef.current || hasOutput || completedFromServer !== null;

    const parsed = useMemo(() => {
      const args = parseToolArgs(data);
      const rawData = args?.data;
      if (!rawData) return null;

      try {
        const inner =
          typeof rawData === "string" ? JSON.parse(rawData) : rawData;

        // Parse strategy_names first — needed for split heuristics
        let names: string[];
        if (args.strategy_names) {
          try {
            const sn =
              typeof args.strategy_names === "string"
                ? JSON.parse(args.strategy_names)
                : args.strategy_names;
            names = Array.isArray(sn) ? sn : [];
          } catch {
            names = [];
          }
        } else if (inner?.proposal_names) {
          names = inner.proposal_names;
        } else {
          names = [];
        }

        const expectedCount = names.length >= 2 ? names.length : 0;

        let proposals: any[][][];
        if (Array.isArray(inner) && inner.length > 0) {
          const isFlat =
            Array.isArray(inner[0]) &&
            inner[0].length === 10 &&
            !Array.isArray(inner[0][0]);
          if (isFlat) {
            const cleaned = (inner as any[][]).filter(
              (r: any[]) => !isHeaderRow(r),
            );
            const summaryCount = cleaned.filter((r: any[]) =>
              isSummaryRowCheck(r),
            ).length;
            if (summaryCount >= 2) {
              proposals = splitFlatRowsIntoProposals(cleaned);
            } else if (
              expectedCount >= 2 &&
              cleaned.length >= expectedCount * 2
            ) {
              // strategy_names says N proposals but no summary rows to split on:
              // divide rows evenly into N groups
              const chunkSize = Math.ceil(cleaned.length / expectedCount);
              proposals = [];
              for (let i = 0; i < cleaned.length; i += chunkSize) {
                proposals.push(cleaned.slice(i, i + chunkSize));
              }
            } else {
              proposals = [cleaned];
            }
          } else {
            proposals = (inner as any[][][]).map((p: any[][]) =>
              p.filter(
                (r: any[]) =>
                  Array.isArray(r) && r.length === 10 && !isHeaderRow(r),
              ),
            );
          }
        } else if (inner?.proposals) {
          proposals = (inner.proposals as any[][][]).map((p: any[][]) =>
            p.filter((r: any[]) => !isHeaderRow(r)),
          );
        } else {
          return null;
        }

        proposals = proposals.filter((p: any[][]) => p.length > 0);
        if (proposals.length === 0) return null;

        const defaultNames = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (names.length < proposals.length) {
          for (let i = names.length; i < proposals.length; i++) {
            names.push(defaultNames[i] || `方案${i + 1}`);
          }
        }

        return { proposals, names };
      } catch {
        return null;
      }
    }, [data]);

    const sessionId = getSessionId();
    const isMulti = (parsed?.proposals?.length ?? 0) > 1;

    const handleSubmit = useCallback(async () => {
      if (!sessionId || isCompleted || !parsed) return;
      const chosenIdx = isMulti ? selectedIndex : 0;
      const chosenName =
        parsed.names[chosenIdx ?? 0] || `方案${(chosenIdx ?? 0) + 1}`;

      let resultText: string;
      if (actionType === "confirm") {
        resultText = `用户选择了「${chosenName}」并确认部署`;
      } else {
        resultText = `用户选择「${chosenName}」并要求调整：${
          adjustText.trim() || "未填写具体要求"
        }`;
      }

      setSubmitting(true);
      const ok = await resolveInteraction(sessionId, resultText);
      setSubmitting(false);
      if (ok) {
        submittedRef.current = true;
        if (actionType === "confirm") {
          submitResultRef.current = `已确认部署「${chosenName}」`;
        } else {
          submitResultRef.current = `已选择「${chosenName}」并调整：${adjustText.trim()}`;
        }
        forceUpdate((n: number) => n + 1);
        antdMessage.success(
          actionType === "confirm" ? "已确认部署方案" : "已提交调整意见",
        );
      } else {
        antdMessage.error("操作失败，请重试");
      }
    }, [
      sessionId,
      isCompleted,
      parsed,
      actionType,
      adjustText,
      selectedIndex,
      isMulti,
    ]);

    const isLoading =
      data?.status === "in_progress" || data?.status === "created";

    if (!parsed) {
      if (isLoading) {
        return React.createElement(
          "div",
          {
            style: {
              width: "100%",
              borderRadius: 10,
              border: "1px solid #f0f0f0",
              background: "#fff",
              padding: "24px 16px",
              margin: "4px 0",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 12,
            },
          },
          React.createElement(Spin, { size: "default" }),
          React.createElement(
            Text,
            { type: "secondary", style: { fontSize: 13 } },
            "正在生成资源方案...",
          ),
        );
      }
      return React.createElement(
        Card,
        { size: "small", style: { margin: "4px 0" } },
        React.createElement(Text, { type: "secondary" }, "无法解析方案数据"),
      );
    }

    const { proposals, names } = parsed;

    const columns = TABLE_HEADERS.map((header: string, idx: number) => ({
      title: header,
      dataIndex: `col_${idx}`,
      key: `col_${idx}`,
      render: (val: any) => renderCellValue(val),
      ellipsis: idx < 3,
    }));

    // Determine status label text
    let statusText = "待确认";
    let statusColor = "processing";
    if (isCompleted) {
      statusColor = "success";
      statusText = submitResultRef.current || completedFromServer || "已确认";
    }

    const statusTag = React.createElement(
      Tag,
      {
        color: statusColor,
        style: { marginLeft: 4 },
      },
      statusText,
    );

    const titleEl = React.createElement(
      Space,
      { size: 8 },
      React.createElement("span", null, "☁️"),
      React.createElement(
        Text,
        { strong: true, style: { fontSize: 14 } },
        isCompleted ? "资源配置方案" : "请确认您的资源配置方案",
      ),
      statusTag,
    );

    const proposalCards = proposals.map((proposal: any[][], pIdx: number) => {
      const isSelected = isMulti ? selectedIndex === pIdx : true;
      const expanded = expandedCards[pIdx] || false;

      const isSummaryRow = (row: any[]) => {
        const type = getCellString(row[0] || "").trim();
        return /^合计|^总计|^total/i.test(type);
      };

      const summaryRow = proposal.find(isSummaryRow);
      const displayRows = proposal.filter((row: any[]) => !isSummaryRow(row));

      const resources = displayRows.map((row: any[]) => ({
        type: getCellString(row[0] || ""),
        purpose: getCellString(row[1] || ""),
        spec: getCellString(row[2] || ""),
        cost: row[9] ?? null,
      }));

      const totalCostDisplay = summaryRow
        ? getCellString(summaryRow[9] ?? "")
        : "";

      const tableData = proposal.map((row: any[], rIdx: number) => {
        const record: Record<string, any> = { key: rIdx };
        row.forEach((cell: any, cIdx: number) => {
          record[`col_${cIdx}`] = cell;
        });
        return record;
      });

      const cardBorder = isSelected ? "2px solid #1677ff" : "1px solid #e8e8e8";
      const cardShadow = isSelected ? "0 0 0 2px #e6f4ff" : "none";

      return React.createElement(
        "div",
        {
          key: pIdx,
          style: {
            flex: 1,
            minWidth: 240,
            border: cardBorder,
            borderRadius: 8,
            cursor: isMulti ? "pointer" : "default",
            transition: "all 0.2s ease",
            boxShadow: cardShadow,
            background: "#fff",
          },
          onClick: isMulti ? () => setSelectedIndex(pIdx) : undefined,
        },
        React.createElement(
          "div",
          { style: { padding: "10px 12px" } },
          // Proposal name
          React.createElement(
            Text,
            {
              strong: true,
              style: { fontSize: 14, display: "block", marginBottom: 8 },
            },
            names[pIdx],
          ),
          // Resource list
          ...resources.map((r: any, idx: number) =>
            React.createElement(
              "div",
              {
                key: idx,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom:
                    idx < resources.length - 1 ? "1px solid #f5f5f5" : "none",
                },
              },
              React.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                React.createElement(
                  "span",
                  { style: { fontSize: 12, color: "#262626" } },
                  r.type,
                ),
                r.spec &&
                  React.createElement(
                    "span",
                    {
                      style: { fontSize: 11, color: "#8c8c8c", marginLeft: 6 },
                    },
                    r.spec,
                  ),
              ),
              !isEmptyCost(r.cost) &&
                React.createElement(
                  "span",
                  {
                    style: {
                      fontSize: 12,
                      color: "#595959",
                      flexShrink: 0,
                      marginLeft: 8,
                    },
                  },
                  getCellString(r.cost),
                ),
            ),
          ),
          // Total cost
          totalCostDisplay &&
            React.createElement(
              "div",
              {
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginTop: 6,
                  paddingTop: 6,
                  borderTop: "1px dashed #e8e8e8",
                },
              },
              React.createElement(
                "span",
                { style: { fontSize: 12, fontWeight: 500 } },
                "合计",
              ),
              React.createElement(
                "span",
                {
                  style: { fontSize: 14, fontWeight: 700, color: "#fa541c" },
                },
                totalCostDisplay,
              ),
            ),
          // Details toggle
          React.createElement(
            "div",
            {
              style: {
                display: "flex",
                alignItems: "center",
                gap: 4,
                color: "#8c8c8c",
                fontSize: 12,
                cursor: "pointer",
                marginTop: 6,
              },
              onClick: (e: any) => {
                e.stopPropagation();
                setExpandedCards((prev: Record<number, boolean>) => ({
                  ...prev,
                  [pIdx]: !prev[pIdx],
                }));
              },
            },
            React.createElement(
              expanded && DownOutlined ? DownOutlined : RightOutlined || "span",
              {
                style: { fontSize: 10 },
              },
            ),
            React.createElement(
              "span",
              null,
              `明细 · ${displayRows.length} 项`,
            ),
          ),
          expanded &&
            React.createElement(
              "div",
              {
                onClick: (e: any) => e.stopPropagation(),
                style: { marginTop: 4, maxHeight: 260, overflow: "auto" },
              },
              React.createElement(Table, {
                columns,
                dataSource: tableData,
                pagination: false,
                size: "small",
                scroll: { x: "max-content" },
              }),
            ),
        ),
      );
    });

    // Disclaimer
    const disclaimer = React.createElement(
      "div",
      {
        style: {
          background: "#fffbe6",
          border: "1px solid #ffe58f",
          borderRadius: 6,
          padding: "8px 12px",
          marginBottom: 10,
          display: "flex",
          alignItems: "flex-start",
          gap: 8,
        },
      },
      InfoCircleOutlined
        ? React.createElement(InfoCircleOutlined, {
            style: {
              color: "#faad14",
              fontSize: 14,
              flexShrink: 0,
              marginTop: 1,
            },
          })
        : React.createElement("span", null, "⚠️"),
      React.createElement(
        "span",
        {
          style: { fontSize: 12, color: "#8c6e00", lineHeight: 1.5 },
        },
        "在服务部署与配置过程中，可能因实际资源需求变化导致资源变配及费用调整，请及时关注实际资源使用情况与账单详情。",
      ),
    );

    // Action section (confirm or adjust)
    const actionSection =
      !isCompleted &&
      sessionId &&
      !(isMulti && selectedIndex === null) &&
      React.createElement(
        "div",
        null,
        React.createElement(
          "div",
          {
            style: {
              display: "flex",
              gap: 8,
              flexWrap: "wrap",
              marginBottom: 8,
            },
          },
          // Confirm option
          React.createElement(
            "div",
            {
              style: {
                flex: 1,
                minWidth: 140,
                border: `1px solid ${
                  actionType === "confirm" ? "#1677ff" : "#e8e8e8"
                }`,
                borderRadius: 6,
                padding: "8px 12px",
                cursor: "pointer",
                transition: "all 0.15s ease",
                display: "flex",
                alignItems: "center",
                gap: 8,
                background:
                  actionType === "confirm" ? "#e6f4ff" : "transparent",
              },
              onClick: () => setActionType("confirm"),
            },
            React.createElement(Radio, { checked: actionType === "confirm" }),
            React.createElement(
              "span",
              { style: { fontSize: 13 } },
              "确认部署",
            ),
          ),
          // Adjust option
          React.createElement(
            "div",
            {
              style: {
                flex: 1,
                minWidth: 140,
                border: `1px solid ${
                  actionType === "adjust" ? "#1677ff" : "#e8e8e8"
                }`,
                borderRadius: 6,
                padding: "8px 12px",
                transition: "all 0.15s ease",
                background: actionType === "adjust" ? "#e6f4ff" : "transparent",
              },
            },
            React.createElement(
              "div",
              {
                style: {
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                },
                onClick: () => setActionType("adjust"),
              },
              React.createElement(Radio, { checked: actionType === "adjust" }),
              React.createElement(
                "span",
                { style: { fontSize: 13 } },
                "调整资源",
              ),
            ),
            actionType === "adjust" &&
              React.createElement(TextArea, {
                value: adjustText,
                onChange: (e: any) => setAdjustText(e.target.value),
                placeholder: "请输入调整要求",
                autoSize: { minRows: 1, maxRows: 3 },
                style: { fontSize: 12, marginTop: 6 },
              }),
          ),
        ),
        // Footer
        React.createElement(
          "div",
          {
            style: {
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              paddingTop: 8,
            },
          },
          React.createElement(
            Text,
            { type: "secondary", style: { fontSize: 11 } },
            isMulti
              ? "一小时后未操作将自动选择第一个方案"
              : "一小时后未操作将自动确认部署",
          ),
          React.createElement(
            Button,
            {
              type: "primary",
              size: "small",
              loading: submitting,
              onClick: handleSubmit,
              disabled: actionType === "adjust" && !adjustText.trim(),
            },
            actionType === "confirm" ? "确认部署" : "提交调整",
          ),
        ),
      );

    // Multi-proposal hint
    const multiHint =
      isMulti &&
      selectedIndex === null &&
      !isCompleted &&
      React.createElement(
        "div",
        {
          style: {
            textAlign: "center",
            padding: "8px 0 4px",
            color: "rgba(0,0,0,0.45)",
            fontSize: 12,
          },
        },
        "请点击选择一个方案后继续操作",
      );

    return React.createElement(
      "div",
      {
        style: {
          width: "100%",
          borderRadius: 10,
          border: "1px solid #f0f0f0",
          overflow: "hidden",
          background: "#fff",
          padding: "12px 16px",
          margin: "4px 0",
        },
      },
      // Header
      React.createElement("div", { style: { marginBottom: 10 } }, titleEl),
      // Proposals grid
      React.createElement(
        "div",
        {
          style: {
            display: "flex",
            gap: 10,
            marginBottom: 12,
            flexWrap: "wrap",
          },
        },
        ...proposalCards,
      ),
      multiHint,
      disclaimer,
      !isCompleted && actionSection,
    );
  }

  // ── manage_prd renderer ───────────────────────────────────────────────

  function ManagePRDRender({ data }: { data: any }) {
    const [prd, setPrd] = useState<any>(null);
    const [fetchError, setFetchError] = useState(false);
    const isLoading =
      data?.status === "in_progress" || data?.status === "created";

    const loopDir = useMemo(() => {
      const args = parseToolArgs(data);
      return args?.loop_dir || null;
    }, [data]);

    const toolResult = useMemo(() => {
      const outputText = extractOutputText(data?.content?.[1]?.data?.output);
      if (!outputText) return null;
      try {
        return JSON.parse(outputText);
      } catch {
        return null;
      }
    }, [data]);

    const isSuccess = toolResult?.status === "ok";
    const isError = toolResult?.status === "error";
    const errorMessage = isError ? toolResult?.message || "未知错误" : null;

    const fetchPrd = useCallback(async () => {
      if (!loopDir) return;
      try {
        const token = getApiToken();
        const headers: Record<string, string> = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        const res = await fetch(
          getApiUrl(`/prd?loop_dir=${encodeURIComponent(loopDir)}`),
          { headers },
        );
        if (!res.ok) {
          setFetchError(true);
          return;
        }
        const json = await res.json();
        if (json && Array.isArray(json.userStories)) {
          setPrd(json);
          setFetchError(false);
        } else {
          setFetchError(true);
        }
      } catch {
        setFetchError(true);
      }
    }, [loopDir]);

    React.useEffect(() => {
      if (!isLoading && isSuccess && loopDir) fetchPrd();
    }, [isLoading, isSuccess, loopDir, fetchPrd]);

    if (isLoading) {
      return React.createElement(
        "div",
        {
          style: {
            width: "100%",
            borderRadius: 10,
            border: "1px solid #f0f0f0",
            background: "#fff",
            padding: "24px 16px",
            margin: "4px 0",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 12,
          },
        },
        React.createElement(Spin, { size: "default" }),
        React.createElement(
          Text,
          { type: "secondary", style: { fontSize: 13 } },
          "正在更新 PRD...",
        ),
      );
    }

    if (isError) {
      return React.createElement(
        "div",
        {
          style: {
            width: "100%",
            borderRadius: 10,
            border: "1px solid #fff1f0",
            background: "#fff1f0",
            padding: "12px 16px",
            margin: "4px 0",
            display: "flex",
            alignItems: "center",
            gap: 8,
          },
        },
        React.createElement(
          Text,
          { type: "danger", style: { fontSize: 13 } },
          `PRD 格式错误，将会修正：${errorMessage}`,
        ),
      );
    }

    if (!isSuccess || fetchError || !prd) return null;

    const stories = prd.userStories;
    const sortedStories = [...stories].sort(
      (a: any, b: any) => (a.priority || 99) - (b.priority || 99),
    );
    const passedCount = stories.filter((s: any) => s.passes).length;

    const storyColumns = [
      {
        title: "状态",
        key: "status",
        width: 50,
        align: "center" as const,
        render: (_: any, record: any) => {
          if (record.passes) {
            const icon = CheckCircleOutlined
              ? React.createElement(CheckCircleOutlined, {
                  style: { color: "#52c41a", fontSize: 18 },
                })
              : "✅";
            return React.createElement(Tooltip, { title: "已完成" }, icon);
          }
          const icon = FieldTimeOutlined
            ? React.createElement(FieldTimeOutlined, {
                style: { color: "#faad14", fontSize: 18 },
              })
            : "🕐";
          return React.createElement(Tooltip, { title: "待处理" }, icon);
        },
      },
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 85,
        render: (val: string) =>
          React.createElement(Tag, { color: "blue" }, val),
      },
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        render: (val: string) =>
          React.createElement(Text, { strong: true }, val),
      },
      {
        title: "优先级",
        key: "priority",
        width: 70,
        render: (_: any, record: any) => {
          const p = record.priority;
          return React.createElement(
            Tag,
            { color: "default" },
            p != null ? String(p) : "-",
          );
        },
      },
      {
        title: "描述",
        dataIndex: "description",
        key: "description",
        ellipsis: true,
      },
      {
        title: "验收标准",
        key: "acceptance",
        width: 200,
        render: (_: any, record: any) => {
          const criteria = record.acceptanceCriteria;
          if (typeof criteria === "string") {
            return React.createElement(
              "div",
              {
                style: { fontSize: 12, color: "#666", whiteSpace: "pre-wrap" },
              },
              criteria.length > 100 ? criteria.slice(0, 100) + "..." : criteria,
            );
          }
          if (Array.isArray(criteria)) {
            return React.createElement(
              "div",
              { style: { fontSize: 12, color: "#666" } },
              criteria.length > 2
                ? criteria.slice(0, 2).join(", ") + "..."
                : criteria.join(", "),
            );
          }
          return "-";
        },
      },
    ];

    const titleEl = React.createElement(
      Space,
      { size: 8 },
      FileTextOutlined
        ? React.createElement(FileTextOutlined, { style: { color: "#1677ff" } })
        : null,
      React.createElement(
        "span",
        { style: { fontSize: 14 } },
        React.createElement(Text, { strong: true }, prd.project || "PRD"),
      ),
    );

    const storyTable = React.createElement(Table, {
      columns: storyColumns,
      dataSource: sortedStories.map((s: any) => ({ ...s, key: s.id })),
      size: "small",
      pagination: false,
      scroll: { x: "max-content" },
      style: { marginBottom: 4 },
    });

    return React.createElement(
      "div",
      {
        style: {
          width: "100%",
          borderRadius: 10,
          border: "1px solid #f0f0f0",
          overflow: "hidden",
          background: "#fff",
          padding: "12px 16px",
          margin: "4px 0",
        },
      },
      React.createElement("div", { style: { marginBottom: 8 } }, titleEl),
      React.createElement(Descriptions, {
        size: "small",
        column: { xs: 1, sm: 2, md: 3 },
        style: { marginBottom: 12 },
        bordered: false,
        items: [
          {
            key: "progress",
            label: "进度",
            children: `${passedCount}/${stories.length} 完成`,
          },
        ],
      }),
      storyTable,
      React.createElement(
        "div",
        {
          style: {
            fontSize: 11,
            color: "#8c8c8c",
            display: "flex",
            alignItems: "center",
            gap: 8,
          },
        },
        CheckCircleOutlined
          ? React.createElement(CheckCircleOutlined, {
              style: { color: "#52c41a", fontSize: 14 },
            })
          : "✅",
        React.createElement("span", null, "已完成"),
        React.createElement("span", { style: { margin: "0 4px" } }, "·"),
        FieldTimeOutlined
          ? React.createElement(FieldTimeOutlined, {
              style: { color: "#faad14", fontSize: 14 },
            })
          : "🕐",
        React.createElement("span", null, "待处理"),
      ),
    );
  }

  // ── A2A Remote Agent Management Page ──────────────────────────────────

  const {
    Form,
    Select,
    Drawer,
    Modal,
    Empty,
    Badge,
    Divider,
    message: antdMsg,
  } = antd;
  const {
    ApiOutlined,
    PlusOutlined,
    ReloadOutlined,
    DeleteOutlined,
    LinkOutlined,
    DisconnectOutlined,
  } = antdIcons || {};
  const { useEffect } = React;

  const API_BASE = "/a2a/agents";

  function getSelectedAgentId(): string | null {
    try {
      const raw =
        sessionStorage.getItem("qwenpaw-agent-storage") ||
        localStorage.getItem("qwenpaw-agent-storage");
      if (raw) {
        const parsed = JSON.parse(raw);
        return parsed?.state?.selectedAgent || null;
      }
    } catch {}
    return null;
  }

  async function a2aFetch(path: string, opts?: RequestInit) {
    const url = getApiUrl(path);
    const token = getApiToken?.();
    const agentId = getSelectedAgentId();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(agentId ? { "X-Agent-Id": agentId } : {}),
    };
    const resp = await fetch(url, {
      ...opts,
      headers: { ...headers, ...(opts?.headers || {}) },
    });
    if (!resp.ok) {
      const body = await resp.text().catch(() => "");
      throw new Error(body || `HTTP ${resp.status}`);
    }
    if (resp.status === 204 || resp.headers.get("content-length") === "0")
      return null;
    return resp.json();
  }

  function A2ACard(props: { agent: any; onClick: () => void }) {
    const { agent, onClick } = props;
    const isConnected = agent.status === "connected";
    const statusColor = isConnected
      ? "#52c41a"
      : agent.status === "error"
      ? "#ff4d4f"
      : "#d9d9d9";
    const statusText = isConnected
      ? "已连接"
      : agent.status === "error"
      ? "错误"
      : "未连接";
    const authLabels: Record<string, string> = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key",
    };

    return React.createElement(
      Card,
      {
        hoverable: true,
        onClick,
        size: "small",
        style: { cursor: "pointer" },
        title: React.createElement(
          Space,
          null,
          React.createElement(Badge, { color: statusColor }),
          React.createElement(
            "span",
            null,
            agent.name || agent.alias || agent.url,
          ),
        ),
        extra: agent.auth_type
          ? React.createElement(
              Tag,
              { color: "blue" },
              authLabels[agent.auth_type] || agent.auth_type,
            )
          : null,
      },
      React.createElement(
        "div",
        { style: { fontSize: 12, color: "#666" } },
        React.createElement(
          "div",
          { style: { marginBottom: 4 } },
          LinkOutlined
            ? React.createElement(LinkOutlined, { style: { marginRight: 4 } })
            : null,
          agent.url,
        ),
        agent.description
          ? React.createElement(
              "div",
              { style: { marginBottom: 4, color: "#999" } },
              agent.description,
            )
          : null,
        agent.skills?.length > 0
          ? React.createElement(
              "div",
              null,
              agent.skills
                .slice(0, 3)
                .map((s: any, i: number) =>
                  React.createElement(
                    Tag,
                    { key: i, style: { fontSize: 11 } },
                    s.name,
                  ),
                ),
              agent.skills.length > 3
                ? React.createElement(
                    Tag,
                    { style: { fontSize: 11 } },
                    `+${agent.skills.length - 3}`,
                  )
                : null,
            )
          : null,
        React.createElement(
          "div",
          { style: { marginTop: 4, color: statusColor, fontSize: 11 } },
          statusText,
          agent.error ? ` - ${agent.error}` : "",
        ),
      ),
    );
  }

  function useCurrentAgentId(): string | null {
    const ref = React.useRef<string | null>(getSelectedAgentId());
    const [agentId, setAgentId] = useState<string | null>(ref.current);
    useEffect(() => {
      const check = () => {
        const current = getSelectedAgentId();
        if (current !== ref.current) {
          ref.current = current;
          setAgentId(current);
        }
      };
      const timer = setInterval(check, 200);
      window.addEventListener("storage", check);
      return () => {
        clearInterval(timer);
        window.removeEventListener("storage", check);
      };
    }, []);
    return agentId;
  }

  function A2APage() {
    const currentAgentId = useCurrentAgentId();
    const [agents, setAgents] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [activeAgent, setActiveAgent] = useState<any>(null);
    const [isCreateMode, setIsCreateMode] = useState(false);
    const [saving, setSaving] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const [form] = Form.useForm();

    const fetchAgents = useCallback(async () => {
      setLoading(true);
      try {
        const data = await a2aFetch(API_BASE);
        setAgents(data?.agents || []);
      } catch {
        setAgents([]);
      } finally {
        setLoading(false);
      }
    }, []);

    useEffect(() => {
      fetchAgents();
    }, [currentAgentId]);

    const handleCreateClick = useCallback(() => {
      setIsCreateMode(true);
      setActiveAgent(null);
      setDrawerOpen(true);
      form.resetFields();
      form.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: "",
      });
    }, [form]);

    const handleCardClick = useCallback((agent: any) => {
      setIsCreateMode(false);
      setActiveAgent(agent);
      setDrawerOpen(true);
    }, []);

    const handleClose = useCallback(() => {
      setDrawerOpen(false);
      setActiveAgent(null);
      setIsCreateMode(false);
      form.resetFields();
    }, [form]);

    const handleSubmit = useCallback(async () => {
      let values: any;
      try {
        values = await form.validateFields();
      } catch {
        return;
      }
      const body = {
        url: String(values.url || "").trim(),
        alias: String(values.alias || "").trim() || undefined,
        auth_type: String(values.auth_type || ""),
        auth_token: String(values.auth_token || ""),
      };
      if (!body.url) return;
      setSaving(true);
      try {
        await a2aFetch(API_BASE, {
          method: "POST",
          body: JSON.stringify(body),
        });
        antdMsg.success("A2A Agent 注册成功");
        await fetchAgents();
        handleClose();
      } catch (e: any) {
        antdMsg.error(e.message || "注册失败");
      } finally {
        setSaving(false);
      }
    }, [form, fetchAgents, handleClose]);

    const handleDelete = useCallback(async () => {
      if (!activeAgent) return;
      const alias = activeAgent.alias || activeAgent.url;
      Modal.confirm({
        title: `删除 ${alias}`,
        content: "确定删除该远程 A2A Agent 吗？此操作不可撤销。",
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: true },
        async onOk() {
          try {
            await a2aFetch(`${API_BASE}/${encodeURIComponent(alias)}`, {
              method: "DELETE",
            });
            antdMsg.success("A2A Agent 已删除");
            await fetchAgents();
            handleClose();
          } catch (e: any) {
            antdMsg.error(e.message || "删除失败");
          }
        },
      });
    }, [activeAgent, fetchAgents, handleClose]);

    const handleRefresh = useCallback(async () => {
      if (!activeAgent) return;
      const alias = activeAgent.alias || activeAgent.url;
      setRefreshing(true);
      try {
        const updated = await a2aFetch(
          `${API_BASE}/${encodeURIComponent(alias)}/refresh`,
          {
            method: "POST",
          },
        );
        antdMsg.success("Agent Card 已刷新");
        await fetchAgents();
        if (updated) setActiveAgent(updated);
      } catch (e: any) {
        antdMsg.error(e.message || "刷新失败");
      } finally {
        setRefreshing(false);
      }
    }, [activeAgent, fetchAgents]);

    const authTypeValue = Form.useWatch?.("auth_type", form) ?? "";

    // Create form view
    const createFormEl = React.createElement(
      Form,
      { form, layout: "vertical" },
      React.createElement(
        Form.Item,
        {
          name: "url",
          label: "Agent URL",
          rules: [{ required: true, message: "请输入 Agent URL" }],
        },
        React.createElement(Input, {
          placeholder: "https://agent.example.com",
        }),
      ),
      React.createElement(
        Form.Item,
        { name: "alias", label: "别名" },
        React.createElement(Input, { placeholder: "输入别名（可选）" }),
      ),
      React.createElement(
        Form.Item,
        { name: "auth_type", label: "认证类型" },
        React.createElement(
          Select,
          { allowClear: true, placeholder: "无认证" },
          React.createElement(
            Select.Option,
            { value: "bearer" },
            "Bearer Token",
          ),
          React.createElement(Select.Option, { value: "api_key" }, "API Key"),
          React.createElement(
            Select.Option,
            { value: "gateway" },
            "阿里云Agent Hub",
          ),
        ),
      ),
      authTypeValue === "gateway"
        ? React.createElement(
            "div",
            {
              style: {
                marginBottom: 16,
                padding: "8px 12px",
                background: "#f6ffed",
                border: "1px solid #b7eb8f",
                borderRadius: 6,
                fontSize: 12,
                color: "#52c41a",
              },
            },
            "阿里云Agent Hub 模式将自动使用环境变量中的 AK-SK 换取 Bearer Token",
          )
        : null,
      authTypeValue && authTypeValue !== "gateway"
        ? React.createElement(
            Form.Item,
            { name: "auth_token", label: "认证凭证" },
            React.createElement(Input.Password, {
              placeholder: "Bearer Token 或 API Key",
            }),
          )
        : null,
    );

    // Detail view for existing agent
    const detailEl = activeAgent
      ? React.createElement(
          "div",
          null,
          React.createElement(
            Descriptions,
            { column: 1, bordered: true, size: "small" },
            React.createElement(
              Descriptions.Item,
              { label: "URL" },
              activeAgent.url,
            ),
            React.createElement(
              Descriptions.Item,
              { label: "别名" },
              activeAgent.alias || "-",
            ),
            React.createElement(
              Descriptions.Item,
              { label: "Agent 名称" },
              activeAgent.name || "-",
            ),
            React.createElement(
              Descriptions.Item,
              { label: "状态" },
              React.createElement(Badge, {
                color:
                  activeAgent.status === "connected"
                    ? "#52c41a"
                    : activeAgent.status === "error"
                    ? "#ff4d4f"
                    : "#d9d9d9",
                text:
                  activeAgent.status === "connected"
                    ? "已连接"
                    : activeAgent.status === "error"
                    ? "错误"
                    : "未连接",
              }),
            ),
            React.createElement(
              Descriptions.Item,
              { label: "认证类型" },
              activeAgent.auth_type
                ? React.createElement(
                    Tag,
                    { color: "blue" },
                    (
                      {
                        gateway: "阿里云Agent Hub",
                        bearer: "Bearer Token",
                        api_key: "API Key",
                      } as any
                    )[activeAgent.auth_type] || activeAgent.auth_type,
                  )
                : "无认证",
            ),
            React.createElement(
              Descriptions.Item,
              { label: "描述" },
              activeAgent.description || "-",
            ),
            React.createElement(
              Descriptions.Item,
              { label: "版本" },
              activeAgent.version || "-",
            ),
          ),
          activeAgent.skills?.length > 0
            ? React.createElement(
                "div",
                { style: { marginTop: 16 } },
                React.createElement("h4", null, "技能"),
                ...activeAgent.skills.map((s: any, i: number) =>
                  React.createElement(
                    Card,
                    { key: i, size: "small", style: { marginBottom: 8 } },
                    React.createElement("strong", null, s.name),
                    s.description
                      ? React.createElement(
                          "div",
                          { style: { color: "#666", fontSize: 12 } },
                          s.description,
                        )
                      : null,
                  ),
                ),
              )
            : null,
          activeAgent.capabilities
            ? React.createElement(
                "div",
                { style: { marginTop: 16 } },
                React.createElement("h4", null, "能力"),
                React.createElement(
                  Space,
                  null,
                  React.createElement(
                    Tag,
                    {
                      color: activeAgent.capabilities.streaming
                        ? "green"
                        : "default",
                    },
                    "Streaming",
                  ),
                  React.createElement(
                    Tag,
                    {
                      color: activeAgent.capabilities.push_notifications
                        ? "green"
                        : "default",
                    },
                    "Push Notifications",
                  ),
                ),
              )
            : null,
          activeAgent.error
            ? React.createElement(
                "div",
                {
                  style: {
                    marginTop: 16,
                    padding: "8px 12px",
                    background: "#fff2f0",
                    border: "1px solid #ffccc7",
                    borderRadius: 6,
                    fontSize: 12,
                    color: "#ff4d4f",
                  },
                },
                activeAgent.error,
              )
            : null,
          React.createElement(Divider, null),
          React.createElement(
            Space,
            null,
            React.createElement(
              Button,
              {
                type: "primary",
                icon: ReloadOutlined
                  ? React.createElement(ReloadOutlined)
                  : null,
                loading: refreshing,
                onClick: handleRefresh,
              },
              "刷新 Agent Card",
            ),
            React.createElement(
              Button,
              {
                danger: true,
                icon: DeleteOutlined
                  ? React.createElement(DeleteOutlined)
                  : null,
                onClick: handleDelete,
              },
              "删除",
            ),
          ),
        )
      : null;

    const drawerEl = React.createElement(
      Drawer,
      {
        title: isCreateMode
          ? "注册远程 A2A Agent"
          : activeAgent?.name || activeAgent?.alias || "Agent 详情",
        open: drawerOpen,
        onClose: handleClose,
        width: 480,
        footer: isCreateMode
          ? React.createElement(
              Space,
              { style: { float: "right" } },
              React.createElement(Button, { onClick: handleClose }, "取消"),
              React.createElement(
                Button,
                { type: "primary", loading: saving, onClick: handleSubmit },
                "注册",
              ),
            )
          : null,
      },
      isCreateMode ? createFormEl : detailEl,
    );

    const headerEl = React.createElement(
      "div",
      { style: { marginBottom: 16 } },
      React.createElement(
        "div",
        {
          style: {
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          },
        },
        React.createElement("h2", { style: { margin: 0 } }, "A2A 远程 Agent"),
        React.createElement(
          Space,
          null,
          React.createElement(
            Button,
            {
              icon: ReloadOutlined ? React.createElement(ReloadOutlined) : null,
              onClick: fetchAgents,
              loading,
            },
            "刷新列表",
          ),
          React.createElement(
            Button,
            {
              type: "primary",
              icon: PlusOutlined ? React.createElement(PlusOutlined) : null,
              onClick: handleCreateClick,
            },
            "注册 Agent",
          ),
        ),
      ),
      React.createElement(
        "div",
        {
          style: {
            marginTop: 8,
            fontSize: 12,
            color: "#8c8c8c",
            lineHeight: 1.6,
          },
        },
        InfoCircleOutlined
          ? React.createElement(InfoCircleOutlined, {
              style: { marginRight: 4, color: "#faad14" },
            })
          : null,
        "当前 A2A 功能仅支持 CloudPaw 插件连接阿里云 Skills 门户 Agent，连接其他 Agent 可能存在不兼容问题。",
      ),
    );

    const bodyEl = loading
      ? React.createElement(
          "div",
          { style: { textAlign: "center", padding: 60 } },
          React.createElement(Spin, { size: "large" }),
        )
      : agents.length === 0
      ? React.createElement(Empty, { description: "暂无注册的远程 A2A Agent" })
      : React.createElement(
          "div",
          {
            style: {
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
              gap: 12,
            },
          },
          ...agents.map((agent: any) =>
            React.createElement(A2ACard, {
              key: agent.alias || agent.url,
              agent,
              onClick: () => handleCardClick(agent),
            }),
          ),
        );

    return React.createElement(
      "div",
      { style: { padding: 24 } },
      headerEl,
      bodyEl,
      drawerEl,
    );
  }

  // ── a2a_call tool renderer ───────────────────────────────────────────

  function A2ACallRender({ data }: { data: any }) {
    const scrollRef = React.useRef<HTMLDivElement>(null);
    const [collapsed, setCollapsed] = useState<Record<number, boolean>>({});

    const toolArgs = useMemo(() => {
      const argsStr = data?.content?.[0]?.data?.arguments;
      if (!argsStr) return null;
      try {
        return JSON.parse(argsStr);
      } catch {
        return null;
      }
    }, [data?.content?.[0]?.data?.arguments]);

    const { toolResult, rawErrorText } = useMemo(() => {
      const content = data?.content;
      if (!Array.isArray(content))
        return { toolResult: null, rawErrorText: "" };
      for (const item of content) {
        const rawOutput = item?.data?.output;
        if (!rawOutput) continue;
        let textContent = "";
        if (Array.isArray(rawOutput)) {
          const textBlock = rawOutput.find(
            (b: any) => b?.type === "text" && b?.text,
          );
          textContent = textBlock?.text || "";
        } else if (typeof rawOutput === "string") {
          try {
            const parsed = JSON.parse(rawOutput);
            if (
              typeof parsed === "object" &&
              (parsed?.steps || parsed?.response_text)
            )
              return { toolResult: parsed, rawErrorText: "" };
            if (Array.isArray(parsed)) {
              const tb = parsed.find((b: any) => b?.type === "text" && b?.text);
              if (tb?.text) textContent = tb.text;
            }
          } catch {
            textContent = rawOutput;
          }
        }
        if (!textContent) continue;
        try {
          const result = JSON.parse(textContent);
          return { toolResult: result, rawErrorText: "" };
        } catch {
          return { toolResult: null, rawErrorText: textContent };
        }
      }
      return { toolResult: null, rawErrorText: "" };
    }, [data?.content]);

    const steps: any[] = toolResult?.steps || [];
    const taskState = toolResult?.task_state || "";
    const errorText = toolResult?.error || "";
    const responseText = toolResult?.response_text || "";

    React.useEffect(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }, [steps.length, responseText, rawErrorText]);

    // Auto-collapse finished thinking and tool_call steps
    React.useEffect(() => {
      const newCollapsed: Record<number, boolean> = { ...collapsed };
      let changed = false;
      steps.forEach((step: any, idx: number) => {
        if (collapsed[idx] !== undefined) return;
        if (step.type === "thinking" && step.done) {
          newCollapsed[idx] = true;
          changed = true;
        } else if (step.type === "tool_call" && step.status !== "running") {
          newCollapsed[idx] = true;
          changed = true;
        }
      });
      if (changed) setCollapsed(newCollapsed);
    }, [steps]);

    const agentAlias = toolArgs?.agent_alias || "";
    const agentUrl = toolArgs?.agent_url || "";
    const displayName = agentAlias || agentUrl || "远程 Agent";

    const finishedTaskStates: Record<string, { color: string; text: string }> =
      {
        completed: { color: "#52c41a", text: "已完成" },
        TASK_STATE_COMPLETED: { color: "#52c41a", text: "已完成" },
        failed: { color: "#ff4d4f", text: "失败" },
        TASK_STATE_FAILED: { color: "#ff4d4f", text: "失败" },
        error: { color: "#ff4d4f", text: "出错" },
        canceled: { color: "#faad14", text: "已取消" },
        TASK_STATE_CANCELED: { color: "#faad14", text: "已取消" },
        AWAITING_USER_INPUT: { color: "#1677ff", text: "等待输入" },
        input_required: { color: "#1677ff", text: "等待输入" },
      };

    const hasResult = toolResult !== null || !!rawErrorText;
    const isWorking =
      taskState === "working" || taskState === "TASK_STATE_WORKING";
    const isFinished = hasResult && !isWorking;

    let tagColor = "#1677ff";
    let tagLabel = "执行中...";
    if (isFinished) {
      if (finishedTaskStates[taskState]) {
        tagColor = finishedTaskStates[taskState].color;
        tagLabel = finishedTaskStates[taskState].text;
      } else if (rawErrorText) {
        tagColor = "#ff4d4f";
        tagLabel = "出错";
      } else {
        tagColor = "#52c41a";
        tagLabel = "已完成";
      }
    }

    const headerEl = React.createElement(
      Space,
      { size: 6 },
      React.createElement("span", { style: { fontSize: 13 } }, "🔗"),
      React.createElement(
        Text,
        { style: { fontSize: 12, color: "#595959" } },
        `A2A: ${displayName}`,
      ),
      React.createElement(
        Tag,
        { color: tagColor, style: { fontSize: 11, lineHeight: "18px" } },
        tagLabel,
      ),
    );

    const noStepsYet = steps.length === 0 && !rawErrorText && !errorText;

    const loadingSpinner =
      !isFinished && noStepsYet
        ? React.createElement(
            "div",
            {
              style: {
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 10px",
                marginBottom: 8,
                background: "#f6ffed",
                border: "1px solid #b7eb8f",
                borderRadius: 6,
              },
            },
            React.createElement(Spin, { size: "small" }),
            React.createElement(
              Text,
              { style: { fontSize: 12, color: "#52c41a" } },
              `正在连接 ${displayName}...`,
            ),
          )
        : null;

    function toggleCollapse(idx: number) {
      setCollapsed((prev: Record<number, boolean>) => ({
        ...prev,
        [idx]: !prev[idx],
      }));
    }

    function renderStep(step: any, idx: number) {
      const isCollapsed = !!collapsed[idx];

      if (step.type === "thinking") {
        const isDone = !!step.done;
        const icon = isDone ? "💭" : "🧠";
        const label = isDone ? "思考完成" : "思考中...";
        const headerRow = React.createElement(
          "div",
          {
            key: `step-${idx}`,
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 0",
              cursor: isDone ? "pointer" : "default",
              fontSize: 12,
              color: "#8c8c8c",
            },
            onClick: isDone ? () => toggleCollapse(idx) : undefined,
          },
          isDone &&
            React.createElement(
              "span",
              { style: { fontSize: 10, color: "#bfbfbf" } },
              isCollapsed ? "▶" : "▼",
            ),
          React.createElement("span", null, icon),
          React.createElement("span", null, label),
          !isDone &&
            React.createElement(Spin, {
              size: "small",
              style: { marginLeft: 4 },
            }),
        );
        if (isCollapsed) return headerRow;
        return React.createElement(
          "div",
          { key: `step-${idx}` },
          headerRow,
          React.createElement(
            "div",
            {
              style: {
                marginLeft: 20,
                padding: "4px 8px",
                background: "#fafafa",
                borderRadius: 4,
                fontSize: 12,
                color: "#595959",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                maxHeight: 120,
                overflowY: "auto" as const,
                lineHeight: "1.5",
              },
            },
            step.text || "",
          ),
        );
      }

      if (step.type === "tool_call") {
        const isRunning = step.status === "running";
        const isError = step.status === "error";
        const statusIcon = isRunning ? "⚙️" : isError ? "❌" : "✅";
        const statusLabel = isRunning
          ? `正在执行: ${step.name}`
          : isError
          ? `执行失败: ${step.name}`
          : `执行完成: ${step.name}`;
        const statusColor = isRunning
          ? "#1677ff"
          : isError
          ? "#ff4d4f"
          : "#52c41a";

        const headerRow = React.createElement(
          "div",
          {
            key: `step-${idx}`,
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 0",
              cursor: !isRunning ? "pointer" : "default",
              fontSize: 12,
              color: statusColor,
            },
            onClick: !isRunning ? () => toggleCollapse(idx) : undefined,
          },
          !isRunning &&
            React.createElement(
              "span",
              { style: { fontSize: 10, color: "#bfbfbf" } },
              isCollapsed ? "▶" : "▼",
            ),
          React.createElement("span", null, statusIcon),
          React.createElement("span", null, statusLabel),
          isRunning &&
            React.createElement(Spin, {
              size: "small",
              style: { marginLeft: 4 },
            }),
        );

        if (isCollapsed || (!step.desc && !isRunning)) return headerRow;

        return React.createElement(
          "div",
          { key: `step-${idx}` },
          headerRow,
          step.desc &&
            React.createElement(
              "div",
              {
                style: {
                  marginLeft: 20,
                  padding: "2px 8px",
                  fontSize: 11,
                  color: "#8c8c8c",
                },
              },
              step.desc,
            ),
        );
      }

      if (step.type === "text") {
        return React.createElement(
          "div",
          {
            key: `step-${idx}`,
            style: {
              padding: "4px 0",
              fontSize: 12,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              lineHeight: "1.6",
              color: "#262626",
            },
          },
          step.text || "",
        );
      }

      return null;
    }

    const stepsEl =
      steps.length > 0
        ? React.createElement(
            "div",
            {
              ref: scrollRef,
              style: {
                background: "#fafafa",
                border: "1px solid #e8e8e8",
                borderRadius: 6,
                padding: "6px 10px",
                maxHeight: 200,
                overflowY: "auto" as const,
              },
            },
            ...steps.map(renderStep),
          )
        : null;

    const errorEl =
      rawErrorText || errorText
        ? React.createElement(
            "div",
            {
              style: {
                background: "#fff2f0",
                border: "1px solid #ffccc7",
                borderRadius: 6,
                padding: "8px 12px",
                fontSize: 12,
                color: "#ff4d4f",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              },
            },
            errorText ? `错误: ${errorText}` : rawErrorText,
          )
        : null;

    // Fallback: if no steps but has response_text (legacy format)
    const legacyTextEl =
      !steps.length && responseText && !rawErrorText
        ? React.createElement(
            "div",
            {
              ref: scrollRef,
              style: {
                background: "#fafafa",
                border: "1px solid #e8e8e8",
                borderRadius: 6,
                padding: "10px 12px",
                maxHeight: 200,
                overflowY: "auto" as const,
              },
            },
            React.createElement(
              Text,
              {
                style: {
                  fontSize: 12,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  lineHeight: "1.6",
                },
              },
              responseText,
            ),
          )
        : null;

    return React.createElement(
      "div",
      {
        style: {
          width: "100%",
          borderRadius: 8,
          border: "1px solid #f0f0f0",
          overflow: "hidden",
          background: "#fff",
          padding: "8px 12px",
          margin: "4px 0",
        },
      },
      React.createElement("div", { style: { marginBottom: 6 } }, headerEl),
      loadingSpinner,
      stepsEl,
      legacyTextEl,
      errorEl,
    );
  }

  // ── A2A command stream interceptor (control-command path) ──────────────
  // Detects messages containing the __A2A_STREAM_START__ marker and
  // replaces them with an SSE-powered streaming display.

  const A2A_STREAM_MARKER = "__A2A_STREAM_START__";
  // Markdown may transform __TEXT__ into <strong>TEXT</strong>
  const A2A_STREAM_MARKER_ALT = "A2A_STREAM_START";
  const processedMsgIds = new Set<string>();

  function containsMarker(text: string | null): boolean {
    if (!text) return false;
    return (
      text.includes(A2A_STREAM_MARKER) || text.includes(A2A_STREAM_MARKER_ALT)
    );
  }

  function extractMsgId(el: Element): string | null {
    return (
      el.getAttribute("data-msg-id") ||
      el.getAttribute("data-message-id") ||
      el.closest("[data-msg-id]")?.getAttribute("data-msg-id") ||
      el.closest("[data-message-id]")?.getAttribute("data-message-id") ||
      null
    );
  }

  function findMarkerContainer(node: Element): HTMLElement | null {
    // Check innerHTML first (handles cases where text is inside React components)
    if (containsMarker(node.innerHTML)) {
      return node as HTMLElement;
    }
    if (containsMarker(node.textContent)) {
      return node as HTMLElement;
    }
    // Search descendants
    const walker = document.createTreeWalker(
      node,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    );
    while (walker.nextNode()) {
      const n = walker.currentNode;
      const text =
        n.nodeType === Node.TEXT_NODE
          ? n.textContent
          : (n as Element).innerHTML;
      if (containsMarker(text)) {
        const parent =
          n.nodeType === Node.TEXT_NODE ? n.parentElement : (n as Element);
        if (parent) return parent as HTMLElement;
      }
    }
    return null;
  }

  async function subscribeSSE(container: HTMLElement) {
    const QP = (window as any).QwenPaw;
    if (!QP?.host) {
      console.warn("[a2a] QwenPaw.host not available");
      return;
    }
    const { getApiUrl, getApiToken } = QP.host;
    const url = getApiUrl("/a2a/call/stream");
    const token = getApiToken();

    console.log("[a2a] Subscribing to SSE stream:", url);

    const box = document.createElement("div");
    box.style.cssText =
      "background:#f6ffed;border:1px solid #b7eb8f;border-radius:8px;" +
      "padding:12px 16px;margin:4px 0;font-size:13px;white-space:pre-wrap;" +
      "word-break:break-word;color:#262626;min-height:24px;";
    box.textContent = "正在连接远程 Agent...";

    container.textContent = "";
    container.appendChild(box);

    const controller = new AbortController();

    try {
      const headers: Record<string, string> = {
        Accept: "text/event-stream",
      };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      try {
        const raw =
          sessionStorage.getItem("qwenpaw-agent-storage") ||
          localStorage.getItem("qwenpaw-agent-storage");
        const agentId = JSON.parse(raw || "{}")?.state?.selectedAgent;
        if (agentId) headers["X-Agent-Id"] = agentId;
      } catch {}

      console.log("[a2a] Fetching SSE with headers:", headers);
      const resp = await fetch(url, { headers, signal: controller.signal });
      console.log("[a2a] SSE response status:", resp.status);

      if (!resp.ok) {
        const errText = await resp.text().catch(() => "");
        box.textContent = `SSE 连接失败 (${resp.status}): ${errText.slice(
          0,
          100,
        )}`;
        box.style.borderColor = "#ff4d4f";
        box.style.background = "#fff1f0";
        return;
      }

      if (!resp.body) {
        box.textContent = "SSE 连接失败：无响应体";
        box.style.borderColor = "#ff4d4f";
        box.style.background = "#fff1f0";
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          console.log("[a2a] SSE stream ended (done)");
          break;
        }

        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            console.log("[a2a] SSE event:", evt);
            if (evt.done) {
              if (evt.error) {
                box.textContent = `错误: ${evt.error}`;
                box.style.borderColor = "#ff4d4f";
                box.style.background = "#fff1f0";
              }
              console.log("[a2a] SSE done signal received");
              return;
            }
            if (typeof evt.response_text === "string" && evt.response_text) {
              box.textContent = evt.response_text;
            }
          } catch (e) {
            console.warn("[a2a] SSE parse error:", e, "line:", line);
          }
        }
      }
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        console.error("[a2a] SSE subscription error:", err);
        box.textContent = `连接出错: ${err?.message || err}`;
        box.style.borderColor = "#ff4d4f";
        box.style.background = "#fff1f0";
      }
    }
  }

  function initA2AStreamInterceptor() {
    console.log("[a2a] Initializing stream interceptor");

    function tryProcessNode(node: Node) {
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const el = node as Element;

      const msgId = extractMsgId(el);
      if (msgId && processedMsgIds.has(msgId)) return;

      const container = findMarkerContainer(el);
      if (!container) return;

      console.log("[a2a] Marker detected in DOM, msgId:", msgId);
      if (msgId) processedMsgIds.add(msgId);
      subscribeSSE(container);
    }

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        // Check added nodes
        for (const node of mutation.addedNodes) {
          tryProcessNode(node);
        }
        // Also check the target node itself (for attribute/characterData changes)
        if (mutation.target.nodeType === Node.ELEMENT_NODE) {
          tryProcessNode(mutation.target);
        }
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      characterDataOldValue: true,
    });

    // Periodic scan as fallback (handles cases where MutationObserver misses)
    const scanInterval = setInterval(() => {
      const allTextNodes = document.evaluate(
        "//text()[contains(., 'A2A_STREAM_START')]",
        document.body,
        null,
        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
        null,
      );
      for (let i = 0; i < allTextNodes.snapshotLength; i++) {
        const textNode = allTextNodes.snapshotItem(i) as Text;
        const parent = textNode.parentElement;
        if (parent) {
          const msgId = extractMsgId(parent);
          if (msgId && processedMsgIds.has(msgId)) continue;
          console.log("[a2a] Marker found in periodic scan, msgId:", msgId);
          if (msgId) processedMsgIds.add(msgId);
          subscribeSSE(parent);
        }
      }
    }, 500);

    // Clean up interval on page unload
    window.addEventListener("beforeunload", () => clearInterval(scanInterval));

    // Scan existing DOM on init
    const allTextNodes = document.evaluate(
      "//text()[contains(., 'A2A_STREAM_START')]",
      document.body,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null,
    );
    for (let i = 0; i < allTextNodes.snapshotLength; i++) {
      const textNode = allTextNodes.snapshotItem(i) as Text;
      const parent = textNode.parentElement;
      if (parent) {
        const msgId = extractMsgId(parent);
        if (msgId) processedMsgIds.add(msgId);
        console.log("[a2a] Marker found in existing DOM, msgId:", msgId);
        subscribeSSE(parent);
      }
    }
  }

  // ── Register plugin ──────────────────────────────────────────────────

  (window as any).QwenPaw.registerToolRender?.("cloudpaw", {
    proposal_choice: ProposalChoiceRender,
    manage_prd: ManagePRDRender,
    a2a_call: A2ACallRender,
  });

  (window as any).QwenPaw.registerRoutes?.("cloudpaw", [
    {
      path: "/a2a",
      component: A2APage,
      label: "A2A",
      icon: "🔗",
      priority: 10,
    },
  ]);

  // ── Ensure CloudPaw-Master is selected on first install ───────────

  ensureDefaultAgent();

  // ── Patchable module overrides (QwenPaw ≥ 1.1.4b1) ─────────────────

  patchWelcomeAndTheme();

  // ── Activate A2A command stream interceptor ────────────────────────

  initA2AStreamInterceptor();
}

// ── First-install default agent selection ────────────────────────────

function ensureDefaultAgent() {
  const LAST_USED_KEY = "qwenpaw-last-used-agent";
  const STORAGE_KEY = "qwenpaw-agent-storage";
  const FIRST_INSTALL_KEY = "cloudpaw-first-install";
  const CLOUDPAW_MASTER_AGENT_ID = "cloud-orchestrator";

  if (localStorage.getItem(FIRST_INSTALL_KEY)) return;

  localStorage.setItem(FIRST_INSTALL_KEY, "true");

  function writeAgentToStorage() {
    localStorage.setItem(LAST_USED_KEY, CLOUDPAW_MASTER_AGENT_ID);
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        parsed.state = parsed.state || {};
        parsed.state.selectedAgent = CLOUDPAW_MASTER_AGENT_ID;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
      } else {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: CLOUDPAW_MASTER_AGENT_ID,
              agents: [],
              lastChatIdByAgent: {},
            },
          }),
        );
      }
    } catch {
      /* ignore */
    }
    try {
      const sessionRaw = sessionStorage.getItem(STORAGE_KEY);
      if (sessionRaw) {
        const parsed = JSON.parse(sessionRaw);
        parsed.state = parsed.state || {};
        parsed.state.selectedAgent = CLOUDPAW_MASTER_AGENT_ID;
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
      } else {
        sessionStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: CLOUDPAW_MASTER_AGENT_ID,
              agents: [],
              lastChatIdByAgent: {},
            },
          }),
        );
      }
    } catch {
      /* ignore */
    }
  }

  writeAgentToStorage();

  // Zustand persist middleware may overwrite storage with its in-memory
  // state (selectedAgent="default") between now and the actual page unload.
  // Re-apply our write right before the page unloads to win the race.
  window.addEventListener(
    "beforeunload",
    () => {
      writeAgentToStorage();
    },
    { once: true },
  );

  console.info(
    "[cloudpaw] Set default agent to cloud-orchestrator for first-time user",
  );
  window.location.reload();
}

// ── Welcome & Theme customisation via configProvider monkey-patch ──────

function patchWelcomeAndTheme() {
  const modules = (window as any).QwenPaw?.modules;
  if (!modules) return;

  const configModule = modules["Chat/OptionsPanel/defaultConfig"];
  if (!configModule?.configProvider) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch",
    );
    return;
  }

  const provider = configModule.configProvider;
  const originalGetConfig = provider.getConfig.bind(provider);

  const CLOUDPAW_LOGO_URL =
    "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png";

  const greetings: Record<string, string> = {
    zh: "CloudPaw 插件提示",
    en: "CloudPaw Plugin Tips",
    ja: "CloudPaw プラグインのヒント",
    ru: "Подсказки плагина CloudPaw",
  };
  const descriptions: Record<string, string> = {
    zh: "告诉 CloudPaw 你想做什么，它会自动帮你完成云资源管理、基础设施编排与应用创建上云等任务。\n⚠️ 使用前请在左上角下拉框切换到「CloudPaw-Master」，否则功能无法正常使用！\n对于复杂的长程任务，建议使用 /mission 命令启动 Mission Mode 来自动拆解和执行。",
    en: "Tell CloudPaw what you want to do — it will automatically handle cloud resource management, infrastructure orchestration, and application deployment.\n⚠️ Please switch to 'CloudPaw-Master' from the dropdown in the top-left corner before use — features won't work otherwise!\nFor complex, multi-step tasks, use /mission to start Mission Mode for automated decomposition and execution.",
    ja: "CloudPaw にやりたいことを伝えるだけで、クラウドリソース管理、インフラ構成、アプリケーションのデプロイなどを自動で行います。\n⚠️ 使用前に左上のドロップダウンから「CloudPaw-Master」に切り替えてください。切り替えないと機能が正常に動作しません！\n複雑なタスクには /mission コマンドで Mission Mode を起動し、自動分解・実行できます。",
    ru: "Расскажите CloudPaw, что вы хотите сделать — он автоматически выполнит управление облачными ресурсами, оркестрацию инфраструктуры и развёртывание приложений.\n⚠️ Перед началом переключитесь на 'CloudPaw-Master' в выпадающем списке в левом верхнем углу — иначе функции не будут работать!\nДля сложных задач используйте /mission для автоматической декомпозиции и выполнения.",
  };
  const promptSets: Record<string, Array<{ label: string; value: string }>> = {
    zh: [
      {
        label: "创建个人主页并部署到云端",
        value:
          "/mission 帮我创建一个个人主页并上线到云端。页面包含：个人介绍、技能展示、项目经历、联系方式，所有个人信息请先用占位符代替。风格简洁清爽，适配手机和电脑。请使用阿里云 ECS 部署。",
      },
      {
        label: "快速发布 API 服务到云端",
        value:
          "/mission 帮我把一个 API 服务快速发布到云端。我希望默认提供 /health 和 /hello 两个接口，并给我可直接调用的地址和示例请求，配置尽量简单清晰。",
      },
    ],
    en: [
      {
        label: "Create a personal homepage and deploy to the cloud",
        value:
          "/mission Help me create a personal homepage and deploy it to the cloud. The page should include: personal introduction, skills, project experience, and contact info — please use placeholders for all personal information. The style should be clean and minimal, responsive for mobile and desktop. Please deploy using Alibaba Cloud ECS.",
      },
      {
        label: "Deploy an API service to the cloud",
        value:
          "/mission Help me quickly deploy an API service to the cloud. I want it to provide /health and /hello endpoints by default, and give me a callable URL with example requests. Keep the configuration as simple and clean as possible.",
      },
    ],
  };

  function detectLang(): string {
    const stored = localStorage.getItem("language") || "";
    if (stored) return stored.split("-")[0];
    const nav = navigator.language || "";
    return nav.split("-")[0] || "en";
  }

  provider.getGreeting = () => greetings[detectLang()] || greetings.en;
  provider.getDescription = () => descriptions[detectLang()] || descriptions.en;
  provider.getPrompts = () => promptSets[detectLang()] || promptSets.en;

  provider.getConfig = function (t: any) {
    const base = originalGetConfig(t);
    return {
      ...base,
      theme: {
        ...base.theme,
        leftHeader: {
          ...base.theme?.leftHeader,
          title: "Work with CloudPaw",
        },
      },
      welcome: {
        ...base.welcome,
        avatar: CLOUDPAW_LOGO_URL,
      },
    };
  };

  // Inject style so \n in the description renders as a line break
  if (!document.getElementById("cloudpaw-welcome-style")) {
    const style = document.createElement("style");
    style.id = "cloudpaw-welcome-style";
    style.textContent = `
      [class*="chat-anywhere-welcome-default"] [class*="description"],
      [class*="message-list-welcome"] [class*="description"] {
        white-space: pre-line !important;
        text-align: center !important;
      }
    `;
    document.head.appendChild(style);
  }

  console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}

buildPlugin();
