/**
 * Agent Kanban — frontend (runtime-loaded plugin module).
 *
 * Loaded by the host via usePluginLoader (same-origin Blob URL + dynamic
 * import). Self-registers a React route at /apps/agent-kanban. React and
 * antd come from window.QwenPaw.host (no bundler in this context).
 *
 * Light, Linear-style board:
 * - 5 columns with soft per-status vertical gradient tints
 * - clean white cards: status dot + key, title, description,
 *   assignee avatar + name, updated time
 * - drag by the card header to move between columns
 * - assign an agent, "运行" dispatches to the assignee, 4s polling
 */
(function () {
  var QwenPaw = window.QwenPaw;
  if (!QwenPaw || !QwenPaw.host || !QwenPaw.registerRoutes) {
    console.error("[agent-kanban] window.QwenPaw not ready — cannot register.");
    return;
  }

  var host = QwenPaw.host;
  var React = host.React;
  var antd = host.antd;
  var h = React.createElement;
  var useHostLocale = typeof host.useLocale === "function"
    ? host.useLocale
    : function () { return "en"; };

  var Button = antd.Button;
  var Select = antd.Select;
  var Modal = antd.Modal;
  var Input = antd.Input;
  var Empty = antd.Empty;
  var message = antd.message;

  var MESSAGES = {
    zh: {
      backlog: "待规划", todo: "等待调度", inProgress: "进行中", review: "审核中", done: "已完成",
      justNow: "刚刚", minutesAgo: "{count} 分钟前", hoursAgo: "{count} 小时前", daysAgo: "{count} 天前",
      fetchResultFailed: "获取结果失败", executionFailed: "执行失败: {error}", toolCompleted: "调用 `{name}` 工具完成",
      toolStarted: "调用 `{name}` 工具", unassigned: "未指派", dragHint: "拖动此处移动到其他列", awaitingApproval: "等待授权",
      runningEllipsis: "运行中…", queued: "排队中 #{position}", edit: "编辑", collapse: "收起", expandAll: "展开全部",
      assigneeLocked: "仅待办/待规划状态可切换智能体", updatedAt: "更新于 {time}", liveResult: "▾ 实时结果", hide: "▾ 隐藏",
      viewLiveResult: "▸ 查看实时结果", viewAgentResult: "▸ 查看 agent 结果", waitingOutput: "等待 agent 输出...",
      toolNeedsApproval: "工具需要授权", approve: "批准", deny: "拒绝", reopen: "重新打开", cancelSchedule: "取消调度",
      running: "运行中", rerun: "重新运行", markDone: "标记完成", schedule: "调度", run: "运行", stop: "停止", delete: "删除",
      issueBoard: "🗂 Issue 看板", agentView: "🤖 智能体视角", complete: "完成", tasks: "{count} 个任务", busy: "忙碌",
      idle: "空闲", more: "+{count} 更多", noAgents: "暂无智能体", assignBeforeTodo: "请先为该 issue 指派一个 agent 才能移入待办",
      onlyDoneToReview: "只允许从已完成状态拖动到审核中", assignBeforeRun: "请先为该 issue 指派一个 agent",
      runFailed: "运行失败: {error}", stopped: "已停止运行", titleRequired: "请填写标题", createFailed: "创建失败: {error}",
      editFailed: "编辑失败: {error}", refresh: "刷新", noIssues: "无 issue", approved: "已批准", approveFailed: "批准失败",
      denied: "已拒绝", denyFailed: "拒绝失败", editIssue: "编辑 issue", newIssue: "新建 issue · {column}", save: "保存",
      create: "创建", cancel: "取消", title: "标题", descriptionOptional: "描述（可选）", assigneeOptional: "指派 agent（可选）"
    },
    en: {
      backlog: "Backlog", todo: "Queued", inProgress: "In Progress", review: "In Review", done: "Done",
      justNow: "just now", minutesAgo: "{count} min ago", hoursAgo: "{count} hr ago", daysAgo: "{count} day(s) ago",
      fetchResultFailed: "Failed to fetch result", executionFailed: "Execution failed: {error}", toolCompleted: "Completed tool `{name}`",
      toolStarted: "Called tool `{name}`", unassigned: "Unassigned", dragHint: "Drag here to move to another column", awaitingApproval: "Awaiting approval",
      runningEllipsis: "Running…", queued: "Queued #{position}", edit: "Edit", collapse: "Collapse", expandAll: "Show all",
      assigneeLocked: "The agent can only be changed in Backlog or Queued", updatedAt: "Updated {time}", liveResult: "▾ Live result", hide: "▾ Hide",
      viewLiveResult: "▸ View live result", viewAgentResult: "▸ View agent result", waitingOutput: "Waiting for agent output...",
      toolNeedsApproval: "Tool approval required", approve: "Approve", deny: "Deny", reopen: "Reopen", cancelSchedule: "Cancel",
      running: "Running", rerun: "Run again", markDone: "Mark done", schedule: "Queue", run: "Run", stop: "Stop", delete: "Delete",
      issueBoard: "🗂 Issue Board", agentView: "🤖 Agent View", complete: "Complete", tasks: "{count} task(s)", busy: "Busy",
      idle: "Idle", more: "+{count} more", noAgents: "No agents", assignBeforeTodo: "Assign an agent before moving this issue to Queued",
      onlyDoneToReview: "Only Done issues can be moved to In Review", assignBeforeRun: "Assign an agent before running this issue",
      runFailed: "Run failed: {error}", stopped: "Run stopped", titleRequired: "Enter a title", createFailed: "Create failed: {error}",
      editFailed: "Edit failed: {error}", refresh: "Refresh", noIssues: "No issues", approved: "Approved", approveFailed: "Approval failed",
      denied: "Denied", denyFailed: "Denial failed", editIssue: "Edit issue", newIssue: "New issue · {column}", save: "Save",
      create: "Create", cancel: "Cancel", title: "Title", descriptionOptional: "Description (optional)", assigneeOptional: "Assign agent (optional)"
    }
  };

  function normalizeLocale(value) {
    return String(value || "").toLowerCase().split("-")[0] === "zh" ? "zh" : "en";
  }

  function tr(locale, key, values) {
    var template = (MESSAGES[locale] && MESSAGES[locale][key]) || MESSAGES.en[key] || key;
    return template.replace(/\{(\w+)\}/g, function (_, name) {
      return values && values[name] !== undefined ? String(values[name]) : "{" + name + "}";
    });
  }

  // Light palette
  var C = {
    text: "#1f2937",
    sub: "#6b7280",
    muted: "#9ca3af",
    cardBg: "#ffffff",
    cardBorder: "rgba(15,23,42,0.08)",
    boardBg: "#fafafb",
  };

  var COLUMNS = [
    { key: "backlog", labelKey: "backlog", dot: "#9ca3af", tint: "rgba(148,163,184,0.20)" },
    { key: "todo", labelKey: "todo", dot: "#94a3b8", tint: "rgba(148,163,184,0.12)" },
    { key: "in_progress", labelKey: "inProgress", dot: "#f59e0b", tint: "rgba(245,158,11,0.18)" },
    { key: "review", labelKey: "review", dot: "#22c55e", tint: "rgba(34,197,94,0.16)" },
    { key: "done", labelKey: "done", dot: "#3b82f6", tint: "rgba(59,130,246,0.16)" },
  ];
  var COLUMN_DOT = {};
  COLUMNS.forEach(function (c) {
    COLUMN_DOT[c.key] = c.dot;
  });

  // ── API helpers ────────────────────────────────────────────────────────
  function apiFetch(path, opts) {
    opts = opts || {};
    var url = host.getApiUrl(path);
    var token = host.getApiToken ? host.getApiToken() : "";
    var headers = opts.headers || {};
    headers["Content-Type"] = "application/json";
    if (token) headers["Authorization"] = "Bearer " + token;
    return fetch(url, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.status === 204 ? null : res.json();
    });
  }

  // Build a same-origin EventSource URL with the auth token as a query param
  // (EventSource cannot set an Authorization header; backend accepts ?token=).
  function apiStreamUrl(path) {
    var url = host.getApiUrl(path);
    var token = host.getApiToken ? host.getApiToken() : "";
    if (token) {
      url += (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(token);
    }
    return url;
  }

  var api = {
    listIssues: function () {
      return apiFetch("/agent-kanban/issues");
    },
    createIssue: function (data) {
      return apiFetch("/agent-kanban/issues", { method: "POST", body: data });
    },
    patchIssue: function (id, data) {
      return apiFetch("/agent-kanban/issues/" + id, { method: "PATCH", body: data });
    },
    deleteIssue: function (id) {
      return apiFetch("/agent-kanban/issues/" + id, { method: "DELETE" });
    },
    runIssue: function (id, assignee) {
      var q = assignee ? "?agent_id=" + encodeURIComponent(assignee) : "";
      return apiFetch("/agent-kanban/issues/" + id + "/run" + q, { method: "POST" });
    },
    stopIssue: function (id) {
      return apiFetch("/agent-kanban/issues/" + id + "/stop", { method: "POST" });
    },
    listAgents: function () {
      return apiFetch("/agents");
    },
    listApprovals: function () {
      return apiFetch("/agent-kanban/approvals");
    },
    approveRequest: function (requestId) {
      return apiFetch("/agent-kanban/approvals/" + requestId + "/approve", { method: "POST" });
    },
    denyRequest: function (requestId) {
      return apiFetch("/agent-kanban/approvals/" + requestId + "/deny", { method: "POST" });
    },
  };

  function relTime(ts, locale) {
    if (!ts) return "";
    var diff = Date.now() / 1000 - ts;
    if (diff < 60) return tr(locale, "justNow");
    if (diff < 3600) return tr(locale, "minutesAgo", { count: Math.floor(diff / 60) });
    if (diff < 86400) return tr(locale, "hoursAgo", { count: Math.floor(diff / 3600) });
    return tr(locale, "daysAgo", { count: Math.floor(diff / 86400) });
  }

  function agentName(agents, id) {
    if (!id) return "";
    for (var i = 0; i < agents.length; i++) {
      if (agents[i].id === id) return agents[i].name || id;
    }
    return id;
  }

  // Simple markdown renderer
  function renderMarkdown(text) {
    if (!text) return "";

    // Preserve code blocks and inline code first
    var codeBlocks = [];
    var inlineCodes = [];

    // Extract code blocks
    var html = text.replace(/```([^`]*?)```/g, function(match, code) {
      codeBlocks.push(code);
      return "\x00CODEBLOCK" + (codeBlocks.length - 1) + "\x00";
    });

    // Extract inline code
    html = html.replace(/`([^`]+)`/g, function(match, code) {
      inlineCodes.push(code);
      return "\x00INLINECODE" + (inlineCodes.length - 1) + "\x00";
    });

    // Escape HTML
    html = html.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    // Bold (must come before italic)
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/_(.+?)_/g, '<em>$1</em>');

    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:#4f46e5;text-decoration:underline">$1</a>');

    // Headers
    html = html.replace(/^### (.+)$/gm, '<div style="font-size:13px;font-weight:600;margin:8px 0 4px 0">$1</div>');
    html = html.replace(/^## (.+)$/gm, '<div style="font-size:14px;font-weight:600;margin:8px 0 4px 0">$1</div>');
    html = html.replace(/^# (.+)$/gm, '<div style="font-size:15px;font-weight:600;margin:8px 0 4px 0">$1</div>');

    // Lists
    html = html.replace(/^[*-] (.+)$/gm, '<div style="margin-left:16px">• $1</div>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    // Restore inline code
    for (var i = 0; i < inlineCodes.length; i++) {
      html = html.replace("\x00INLINECODE" + i + "\x00", '<code style="background:#f1f5f9;padding:2px 4px;border-radius:3px;font-family:monospace;font-size:11px">' + inlineCodes[i] + '</code>');
    }

    // Restore code blocks
    for (var i = 0; i < codeBlocks.length; i++) {
      html = html.replace("\x00CODEBLOCK" + i + "\x00", '<pre style="background:#f1f5f9;padding:8px;border-radius:4px;margin:4px 0;overflow-x:auto"><code>' + codeBlocks[i].trim() + '</code></pre>');
    }

    return html;
  }

  // ── Issue card ──────────────────────────────────────────────────────────
  function IssueCard(props) {
    var issue = props.issue;
    var agents = props.agents;
    var t = props.t;
    var running = issue.status === "in_progress";
    var pendingApprovals = props.pendingApprovals || [];
    var waitingApproval = running && pendingApprovals.length > 0;
    var expandState = React.useState(false);
    var expanded = expandState[0];
    var setExpanded = expandState[1];

    // State for fetched result from API
    var resultState = React.useState(null);
    var fetchedResult = resultState[0];
    var setFetchedResult = resultState[1];

    // Live streamed text (agent output) while the issue is running.
    var liveText = props.streamText;
    var hasLive = running && typeof liveText === "string" && liveText.length > 0;

    // Fetch result from API when expanded and not running
    React.useEffect(
      function () {
        if (expanded && !running && !fetchedResult) {
          var url = host.getApiUrl("/agent-kanban/issues/" + issue.id + "/result");
          var token = host.getApiToken ? host.getApiToken() : "";
          var headers = {};
          if (token) headers["Authorization"] = "Bearer " + token;
          fetch(url, { headers: headers })
            .then(function (res) {
              if (!res.ok) throw new Error("HTTP " + res.status);
              return res.json();
            })
            .then(function (data) {
              setFetchedResult(data);
            })
            .catch(function () {
              setFetchedResult({ error: t("fetchResultFailed") });
            });
        }
      },
      [expanded, running, issue.id, fetchedResult]
    );

    // Clear fetched result when issue changes status
    React.useEffect(
      function () {
        setFetchedResult(null);
      },
      [issue.status, issue.updated_at]
    );

    // Display priority: live stream > fetched result > error in issue
    var displayResult = "";
    if (hasLive) {
      displayResult = liveText;
    } else if (fetchedResult) {
      if (fetchedResult.error) {
        displayResult = t("executionFailed", { error: fetchedResult.error });
      } else if (fetchedResult.messages && Array.isArray(fetchedResult.messages)) {
        // Extract tool calls and text from all messages
        var summary = [];
        for (var m = 0; m < fetchedResult.messages.length; m++) {
          var msg = fetchedResult.messages[m];
          var msgType = msg.type || "";
          if (typeof msgType === "object" && msgType.value) {
            msgType = msgType.value;
          }
          msgType = String(msgType);

          // Skip reasoning messages
          if (msgType === "reasoning") {
            continue;
          }

          // Tool calls: check message.type, extract name from content[].data
          if (
            msgType.indexOf("plugin_call") >= 0 ||
            msgType.indexOf("function_call") >= 0 ||
            msgType.indexOf("mcp_tool_call") >= 0
          ) {
            var toolName = "";
            if (msg.content && Array.isArray(msg.content)) {
              for (var i = 0; i < msg.content.length; i++) {
                var item = msg.content[i];
                if (item.data && item.data.name) {
                  toolName = item.data.name;
                  break;
                }
              }
            }
            if (toolName && toolName !== "assistant") {
              // Check if it's an output (completion) or call (start)
              // Wrap tool name in backticks to preserve underscores in markdown
              if (msgType.indexOf("_output") >= 0) {
                summary.push(t("toolCompleted", { name: toolName }));
              } else {
                summary.push(t("toolStarted", { name: toolName }));
              }
            }
          }
          // Text messages: extract text from content
          else if (msgType === "message" && msg.role === "assistant") {
            if (msg.content && Array.isArray(msg.content)) {
              for (var i = 0; i < msg.content.length; i++) {
                var item = msg.content[i];
                if (item.type === "text" && item.text) {
                  summary.push(item.text);
                }
              }
            }
          }
        }
        displayResult = summary.join("\n") || "";
      } else {
        displayResult = "";
      }
    } else if (issue.error) {
      displayResult = t("executionFailed", { error: issue.error });
    }

    var showBody = expanded;

    var agentOptions = [{ label: t("unassigned"), value: "" }].concat(
      agents.map(function (a) {
        return { label: a.name || a.id, value: a.id };
      }),
    );
    var assignedName = agentName(agents, issue.assignee);
    var reviewing = issue.status === "review";
    var done = issue.status === "done";
    var queued = issue.status === "todo";
    // Agent can only be (re)assigned while the issue is still 待办/待规划.
    var canAssign = issue.status === "todo" || issue.status === "backlog";
    var lockAssignee = !canAssign;
    var descExpandState = React.useState(false);
    var descExpanded = descExpandState[0];
    var setDescExpanded = descExpandState[1];
    var longDesc = (issue.description || "").length > 100;

    // Dragging state for visual feedback
    var draggingState = React.useState(false);
    var isDragging = draggingState[0];
    var setIsDragging = draggingState[1];

    // Create ref for drag image
    var cardRef = React.useRef(null);

    return h(
      "div",
      {
        ref: cardRef,
        style: {
          background: C.cardBg,
          border: "1px solid " + C.cardBorder,
          borderRadius: 10,
          padding: "10px 12px",
          marginBottom: 10,
          boxShadow: isDragging
            ? "0 4px 6px rgba(15,23,42,0.15)"
            : "0 1px 2px rgba(15,23,42,0.05)",
          opacity: isDragging ? 0.4 : 1,
          transition: "opacity 0.2s ease, box-shadow 0.2s ease",
        },
      },
      // Header: drag handle (status dot + key). Only this row is draggable so
      // the Select / buttons below stay fully interactive.
      h(
        "div",
        {
          draggable: true,
          onDragStart: function (e) {
            e.dataTransfer.setData("text/plain", issue.id);
            e.dataTransfer.effectAllowed = "move";
            // Use the entire card as drag image
            if (cardRef.current) {
              e.dataTransfer.setDragImage(cardRef.current, 0, 0);
            }
            // Set dragging state for visual feedback
            setIsDragging(true);
          },
          onDragEnd: function (e) {
            // Reset dragging state
            setIsDragging(false);
          },
          title: t("dragHint"),
          style: {
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 6,
            cursor: isDragging ? "grabbing" : "grab",
          },
        },
        h(
          "span",
          { style: { display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: C.muted } },
          h("span", {
            style: {
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: COLUMN_DOT[issue.status] || C.muted,
              display: "inline-block",
            },
          }),
          "PAW-" + issue.id,
        ),
        waitingApproval
          ? h("span", { style: { fontSize: 12, color: "#dc2626", fontWeight: 600 } }, t("awaitingApproval"))
          : running
            ? h("span", { style: { fontSize: 12, color: "#d97706" } }, t("runningEllipsis"))
            : props.queuePosition
              ? h("span", { style: { fontSize: 12, color: "#6366f1" } }, t("queued", { position: props.queuePosition }))
              : null,
      ),
      // Title + description
      h(
        "div",
        {
          style: {
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 2,
          },
        },
        h(
          "div",
          { style: { fontWeight: 600, color: C.text, fontSize: 14, flex: 1 } },
          issue.title,
        ),
        // Edit button (only show for backlog status)
        issue.status === "backlog"
          ? h(
              "a",
              {
                style: {
                  fontSize: 12,
                  color: "#4f46e5",
                  cursor: "pointer",
                  marginLeft: 8,
                  flexShrink: 0,
                },
                onClick: function (e) {
                  e.stopPropagation();
                  if (props.onEdit) props.onEdit(issue);
                },
                title: t("edit"),
              },
              "✏️",
            )
          : null,
      ),
      issue.description
        ? h(
            "div",
            { style: { marginBottom: 8 } },
            h(
              "div",
              {
                style: Object.assign(
                  {
                    fontSize: 12,
                    color: C.sub,
                    lineHeight: 1.5,
                    whiteSpace: "pre-wrap",
                    overflow: "hidden",
                  },
                  descExpanded
                    ? { maxHeight: 220, overflowY: "auto" }
                    : {
                        display: "-webkit-box",
                        WebkitLineClamp: 3,
                        WebkitBoxOrient: "vertical",
                      },
                ),
              },
              issue.description,
            ),
            longDesc
              ? h(
                  "a",
                  {
                    style: { fontSize: 12, color: "#4f46e5", cursor: "pointer" },
                    onClick: function () {
                      setDescExpanded(!descExpanded);
                    },
                  },
                  descExpanded ? t("collapse") : t("expandAll"),
                )
              : null,
          )
        : h("div", { style: { height: 6 } }),
      // Footer: assignee (avatar + select) | updated time
      h(
        "div",
        {
          style: {
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          },
        },
        h(
          "div",
          { style: { display: "flex", alignItems: "center", gap: 6, minWidth: 0, flex: 1 } },
          h(
            "span",
            {
              style: {
                width: 20,
                height: 20,
                borderRadius: "50%",
                background: issue.assignee ? "#eef2ff" : "#f1f5f9",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 11,
                flexShrink: 0,
              },
            },
            issue.assignee ? "🤖" : "○",
          ),
          h(Select, {
            size: "small",
            variant: "borderless",
            bordered: false,
            disabled: lockAssignee,
            title: lockAssignee ? t("assigneeLocked") : undefined,
            value: issue.assignee || "",
            style: { flex: 1, minWidth: 0, marginLeft: -4 },
            options: agentOptions,
            onChange: function (val) {
              props.onAssign(issue, val);
            },
          }),
        ),
        h(
          "span",
          { style: { fontSize: 11, color: C.muted, whiteSpace: "nowrap" } },
          t("updatedAt", { time: relTime(issue.updated_at, props.locale) }),
        ),
      ),
      // Result (agent output) — show for running/review/done states
      (running || reviewing || done)
        ? h(
            "div",
            { style: { marginTop: 6 } },
            h(
              "a",
              {
                style: { fontSize: 12, color: "#4f46e5" },
                onClick: function () {
                  var willExpand = !expanded;
                  setExpanded(willExpand);
                  if (willExpand && running && props.onSubscribe) {
                    props.onSubscribe(issue.id);
                  }
                },
              },
              showBody
                ? (hasLive ? t("liveResult") : t("hide"))
                : running
                  ? t("viewLiveResult")
                  : t("viewAgentResult"),
            ),
            showBody
              ? h(
                  "div",
                  {
                    ref: function (el) {
                      if (el && hasLive) {
                        el.scrollTop = el.scrollHeight;
                      }
                    },
                    style: {
                      fontSize: 12,
                      color: C.sub,
                      background: "#f8fafc",
                      border: "1px solid " + C.cardBorder,
                      borderRadius: 6,
                      padding: 8,
                      marginTop: 4,
                      maxHeight: 200,
                      overflowY: "auto",
                      lineHeight: "1.6",
                    },
                    dangerouslySetInnerHTML: {
                      __html: renderMarkdown(displayResult || (running ? t("waitingOutput") : ""))
                        + (hasLive ? '<span class="ak-pulse" style="margin-left:2px;color:#f59e0b;font-weight:700">▋</span>' : ''),
                    },
                  },
                )
              : null,
          )
        : null,
      // Approval panel
      waitingApproval
        ? h(
            "div",
            {
              style: {
                marginTop: 8,
                padding: "8px 10px",
                background: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: 8,
              },
            },
            pendingApprovals.map(function (ap) {
              return h(
                "div",
                {
                  key: ap.request_id,
                  style: {
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    marginBottom: pendingApprovals.length > 1 ? 6 : 0,
                  },
                },
                h(
                  "div",
                  { style: { fontSize: 12, color: "#991b1b", flex: 1, minWidth: 0 } },
                  h("div", { style: { fontWeight: 600 } }, t("toolNeedsApproval")),
                  h("div", { style: { color: "#b91c1c", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, ap.display_name || ap.tool_name),
                ),
                h(
                  "div",
                  { style: { display: "flex", gap: 4, flexShrink: 0 } },
                  h(
                    Button,
                    {
                      size: "small",
                      type: "primary",
                      onClick: function () {
                        props.onApprove(ap.request_id);
                      },
                    },
                    t("approve"),
                  ),
                  h(
                    Button,
                    {
                      size: "small",
                      danger: true,
                      onClick: function () {
                        props.onDeny(ap.request_id);
                      },
                    },
                    t("deny"),
                  ),
                ),
              );
            }),
          )
        : null,
      // Actions
      h(
        "div",
        {
          style: {
            display: "flex",
            alignItems: "center",
            gap: 4,
            marginTop: 8,
            paddingTop: 8,
            borderTop: "1px solid #f1f5f9",
          },
        },
        done
          ? h(
              Button,
              {
                size: "small",
                onClick: function () {
                  props.onMove(issue, "backlog");
                },
              },
              t("reopen"),
            )
          : queued
            ? h(
                Button,
                {
                  size: "small",
                  danger: true,
                  onClick: function () {
                    props.onMove(issue, "backlog");
                  },
                },
                t("cancelSchedule"),
              )
            : running
              ? h(
                  Button,
                  {
                    size: "small",
                    type: "primary",
                    loading: true,
                    disabled: true,
                  },
                  t("running"),
                )
              : reviewing
                ? h(React.Fragment, null,
                    h(
                      Button,
                      {
                        size: "small",
                        onClick: function () {
                          props.onRun(issue);
                        },
                      },
                      t("rerun"),
                    ),
                    h(
                      Button,
                      {
                        size: "small",
                        type: "primary",
                        onClick: function () {
                          props.onMove(issue, "done");
                        },
                      },
                      t("markDone"),
                    ),
                  )
                : h(
                    Button,
                    {
                      size: "small",
                      type: "primary",
                      disabled: !issue.assignee,
                      onClick: function () {
                        props.onRun(issue);
                      },
                    },
                    props.agentBusy ? t("schedule") : t("run"),
                  ),
        running
          ? h(
              Button,
              {
                size: "small",
                danger: true,
                onClick: function () {
                  props.onStop(issue);
                },
              },
              t("stop"),
            )
          : null,
        h(
          Button,
          {
            size: "small",
            type: "text",
            danger: true,
            style: { marginLeft: "auto" },
            onClick: function () {
              props.onDelete(issue);
            },
          },
          t("delete"),
        ),
      ),
    );
  }

  // ── View toggle + Agent office view ───────────────────────────────────
  function ViewToggle(props) {
    var opts = [
      { key: "issues", label: props.t("issueBoard") },
      { key: "agents", label: props.t("agentView") },
    ];
    return h(
      "div",
      { style: { display: "inline-flex", background: "#eef2f7", borderRadius: 10, padding: 3, gap: 2 } },
      opts.map(function (o) {
        var active = props.view === o.key;
        return h(
          "div",
          {
            key: o.key,
            onClick: function () { props.onChange(o.key); },
            style: {
              cursor: "pointer",
              fontSize: 13,
              fontWeight: active ? 600 : 500,
              padding: "4px 12px",
              borderRadius: 8,
              background: active ? "#ffffff" : "transparent",
              color: active ? C.text : C.sub,
              boxShadow: active ? "0 1px 2px rgba(15,23,42,0.12)" : "none",
              transition: "all .15s ease",
            },
          },
          o.label,
        );
      }),
    );
  }

  var AGENT_BUCKETS = [
    { key: "backlog", labelKey: "backlog", statuses: ["backlog"], dot: "#9ca3af" },
    { key: "todo", labelKey: "todo", statuses: ["todo"], dot: "#94a3b8", showQueue: true },
    { key: "running", labelKey: "running", statuses: ["in_progress"], dot: "#f59e0b" },
    { key: "review", labelKey: "review", statuses: ["review"], dot: "#22c55e" },
    { key: "done", labelKey: "complete", statuses: ["done"], dot: "#3b82f6" },
  ];

  function agentColor(id) {
    var palette = ["#6366f1", "#22c55e", "#f59e0b", "#3b82f6", "#ec4899", "#14b8a6", "#8b5cf6", "#ef4444"];
    var s = 0;
    var key = id || "x";
    for (var i = 0; i < key.length; i++) s = (s * 31 + key.charCodeAt(i)) >>> 0;
    return palette[s % palette.length];
  }

  function AgentLane(props) {
    var agent = props.agent;
    var items = props.items || [];
    var t = props.t;
    var col = agentColor(agent.id);
    var busy = items.some(function (i) { return i.status === "in_progress"; });
    var initial = (agent.name || agent.id || "?").slice(0, 1).toUpperCase();
    return h(
      "div",
      {
        className: "ak-lane",
        style: {
          background: "#ffffff",
          border: "1px solid " + C.cardBorder, borderRadius: 16, padding: 14,
          display: "flex", flexDirection: "column", gap: 12,
        },
      },
      h(
        "div",
        { style: { display: "flex", alignItems: "center", gap: 10 } },
        h(
          "span",
          {
            style: {
              width: 38, height: 38, borderRadius: "50%",
              background: "linear-gradient(135deg, " + col + ", " + col + "cc)",
              color: "#fff", fontWeight: 700, fontSize: 15,
              display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            },
          },
          initial,
        ),
        h(
          "div",
          { style: { minWidth: 0, flex: 1 } },
          h("div", { style: { fontWeight: 600, color: C.text, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, agent.name || agent.id),
          h("div", { style: { fontSize: 11, color: C.muted } }, t("tasks", { count: items.length })),
        ),
        h(
          "span",
          {
            className: busy ? "ak-pulse" : null,
            style: {
              display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, fontWeight: 500,
              color: busy ? "#15803d" : C.sub, background: busy ? "rgba(34,197,94,0.12)" : "#f1f5f9",
              borderRadius: 999, padding: "3px 9px",
            },
          },
          h("span", { style: { width: 7, height: 7, borderRadius: "50%", background: busy ? "#22c55e" : "#cbd5e1", display: "inline-block" } }),
          busy ? t("busy") : t("idle"),
        ),
      ),
      h(
        "div",
        { style: { display: "flex", flexDirection: "column", gap: 8 } },
        AGENT_BUCKETS.map(function (b) {
          var list = items.filter(function (i) { return b.statuses.indexOf(i.status) >= 0; });
          var hasBusy = busy;
          return h(
            "div",
            { key: b.key, style: { background: "#f8fafc", border: "1px solid #eef2f7", borderRadius: 10, padding: "8px 10px" } },
            h(
              "div",
              { style: { display: "flex", alignItems: "center", gap: 7, marginBottom: list.length ? 6 : 0 } },
              h("span", { style: { width: 8, height: 8, borderRadius: "50%", background: b.dot, display: "inline-block" } }),
              h("span", { style: { fontSize: 12, fontWeight: 600, color: C.text } }, t(b.labelKey)),
              h("span", { style: { marginLeft: "auto", fontSize: 11, color: C.sub, background: "#eef2f7", borderRadius: 999, padding: "1px 8px", fontWeight: 600 } }, list.length),
            ),
            list.length
              ? h(
                  "div",
                  { style: { display: "flex", flexDirection: "column", gap: 4 } },
                  list.slice(0, 5).map(function (it, idx) {
                    var queueLabel = (b.showQueue && hasBusy) ? "#" + (idx + 1) + " " : "";
                    return h(
                      "div",
                      { key: it.id, style: { fontSize: 12, color: C.sub, display: "flex", alignItems: "center", gap: 6, minWidth: 0 } },
                      it.status === "in_progress"
                        ? h("span", { className: "ak-spin", style: { width: 9, height: 9, borderRadius: "50%", border: "2px solid #f59e0b", borderTopColor: "transparent", display: "inline-block", flexShrink: 0 } })
                        : h("span", { style: { width: 5, height: 5, borderRadius: "50%", background: b.dot, display: "inline-block", flexShrink: 0 } }),
                      h("span", { style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, queueLabel + it.title),
                    );
                  }),
                  list.length > 5
                    ? h("div", { style: { fontSize: 11, color: C.muted } }, t("more", { count: list.length - 5 }))
                    : null,
                )
              : null,
          );
        }),
      ),
    );
  }

  function AgentBoard(props) {
    var agents = props.agents || [];
    var issues = props.issues || [];
    var t = props.t;
    var byAgent = {};
    agents.forEach(function (a) { byAgent[a.id] = []; });
    var unassigned = [];
    issues.forEach(function (i) {
      if (i.assignee) {
        if (!byAgent[i.assignee]) byAgent[i.assignee] = [];
        byAgent[i.assignee].push(i);
      } else {
        unassigned.push(i);
      }
    });
    var busyCount = 0;
    agents.forEach(function (a) {
      if ((byAgent[a.id] || []).some(function (i) { return i.status === "in_progress"; })) busyCount++;
    });
    var idleCount = agents.length - busyCount;
    var lanes = agents.map(function (a) {
      return h(AgentLane, { key: a.id, agent: a, items: byAgent[a.id] || [], t: t });
    });
    if (unassigned.length) {
      lanes.push(h(AgentLane, { key: "__unassigned__", agent: { id: "", name: t("unassigned") }, items: unassigned, t: t }));
    }
    var css =
      ".ak-lane{transition:transform .15s ease,box-shadow .15s ease}" +
      ".ak-lane:hover{transform:translateY(-2px);box-shadow:0 10px 26px rgba(15,23,42,0.10)}" +
      "@keyframes akPulse{0%,100%{box-shadow:0 0 0 0 rgba(34,197,94,0.45)}50%{box-shadow:0 0 0 6px rgba(34,197,94,0)}}" +
      ".ak-pulse{animation:akPulse 1.5s ease-in-out infinite}" +
      "@keyframes akSpin{to{transform:rotate(360deg)}}" +
      ".ak-spin{animation:akSpin .8s linear infinite}";
    return h(
      "div",
      { style: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" } },
      h("style", { dangerouslySetInnerHTML: { __html: css } }),
      h(
        "div",
        {
          style: {
            background: "linear-gradient(120deg,#eef2ff 0%,#ecfdf5 100%)",
            border: "1px solid rgba(99,102,241,0.15)", borderRadius: 16,
            padding: "16px 18px", marginBottom: 14, display: "flex",
            alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12,
          },
        },
        h(
          "div", { style: { display: "flex", gap: 10 } },
          h(
            "div", { style: { display: "inline-flex", alignItems: "center", gap: 6, background: "rgba(34,197,94,0.12)", borderRadius: 999, padding: "6px 12px" } },
            h("span", { className: busyCount ? "ak-pulse" : null, style: { width: 8, height: 8, borderRadius: "50%", background: "#22c55e", display: "inline-block" } }),
            h("span", { style: { fontSize: 13, fontWeight: 600, color: "#15803d" } }, t("busy") + " " + busyCount),
          ),
          h(
            "div", { style: { display: "inline-flex", alignItems: "center", gap: 6, background: "#f1f5f9", borderRadius: 999, padding: "6px 12px" } },
            h("span", { style: { width: 8, height: 8, borderRadius: "50%", background: "#cbd5e1", display: "inline-block" } }),
            h("span", { style: { fontSize: 13, fontWeight: 600, color: C.sub } }, t("idle") + " " + idleCount),
          ),
        ),
      ),
      lanes.length === 0
        ? h(Empty, { description: h("span", { style: { color: C.muted } }, t("noAgents")) })
        : h(
            "div",
            { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 14, overflowY: "auto", alignContent: "flex-start", alignItems: "start", flex: 1, paddingBottom: 4 } },
            lanes,
          ),
    );
  }

  // ── Main board ───────────────────────────────────────
  function KanbanBoard() {
    // Follow QwenPaw's live language setting. Unsupported host locales use
    // English, matching the host's own i18n fallback policy.
    var hostLocale = useHostLocale();
    var locale = normalizeLocale(hostLocale);
    function t(key, values) {
      return tr(locale, key, values);
    }
    var issuesState = React.useState([]);
    var issues = issuesState[0];
    var setIssues = issuesState[1];
    var agentsState = React.useState([]);
    var agents = agentsState[0];
    var setAgents = agentsState[1];
    var modalState = React.useState(null); // {status, editIssueId} or null
    var modal = modalState[0];
    var setModal = modalState[1];
    var formState = React.useState({ title: "", description: "", assignee: "" });
    var form = formState[0];
    var setForm = formState[1];
    var viewState = React.useState("issues");
    var view = viewState[0];
    var setView = viewState[1];

    // Drag over column state for visual feedback
    var dragOverColumnState = React.useState(null);
    var dragOverColumn = dragOverColumnState[0];
    var setDragOverColumn = dragOverColumnState[1];

    // Realtime agent output per issue: { issueId: partialText }.
    var streamState = React.useState({});
    var streams = streamState[0];
    var setStreams = streamState[1];
    var esRef = React.useRef({});

    // Pending approvals per issue: { issueId: [approval, ...] }
    var approvalsState = React.useState({});
    var approvals = approvalsState[0];
    var setApprovals = approvalsState[1];

    function load() {
      api
        .listIssues()
        .then(function (data) {
          var list = (data && data.issues) || [];
          setIssues(list);
        })
        .catch(function () {});
    }

    function loadApprovals() {
      api
        .listApprovals()
        .then(function (data) {
          setApprovals((data && data.approvals) || {});
        })
        .catch(function () {});
    }

    React.useEffect(function () {
      load();
      loadApprovals();
      api
        .listAgents()
        .then(function (data) {
          setAgents((data && data.agents) || []);
        })
        .catch(function () {});
      var timer = setInterval(load, 4000);
      var approvalTimer = setInterval(loadApprovals, 3000);
      return function () {
        clearInterval(timer);
        clearInterval(approvalTimer);
        Object.keys(esRef.current).forEach(function (k) {
          try { esRef.current[k].close(); } catch (e) {}
        });
        esRef.current = {};
      };
    }, []);

    function moveIssue(id, status) {
      var target = issues.find(function (i) { return i.id === id; });
      if (!target) return;

      if (status === "todo") {
        if (!target.assignee) {
          if (message) message.warning(t("assignBeforeTodo"));
          return;
        }
      }

      // Only allow moving to review from done status
      if (status === "review" && target.status !== "done") {
        if (message) message.warning(t("onlyDoneToReview"));
        return;
      }

      setIssues(function (prev) {
        return prev.map(function (i) {
          return i.id === id ? Object.assign({}, i, { status: status }) : i;
        });
      });
      api.patchIssue(id, { status: status, language: locale }).then(load).catch(load);
    }

    function onAssign(issue, assignee) {
      var patch = { assignee: assignee, language: locale };
      // Backend auto-promotes backlog->todo when assignee is set,
      // but we optimistically update the UI as well.
      var optimisticStatus = issue.status;
      if (issue.status === "backlog" && assignee) {
        optimisticStatus = "todo";
      }
      setIssues(function (prev) {
        return prev.map(function (i) {
          return i.id === issue.id
            ? Object.assign({}, i, { assignee: assignee, status: optimisticStatus })
            : i;
        });
      });
      api.patchIssue(issue.id, patch).then(load).catch(load);
    }

    function closeStream(id) {
      var es = esRef.current[id];
      if (es) {
        try { es.close(); } catch (e) {}
        delete esRef.current[id];
      }
      setStreams(function (prev) {
        if (!(id in prev)) return prev;
        var n = Object.assign({}, prev);
        delete n[id];
        return n;
      });
    }

    function subscribeStream(id) {
      if (typeof window.EventSource === "undefined") return;
      try {
        closeStream(id);
        setStreams(function (prev) {
          var n = Object.assign({}, prev);
          n[id] = "";
          return n;
        });
        var es = new EventSource(
          apiStreamUrl("/agent-kanban/issues/" + id + "/stream"),
        );
        esRef.current[id] = es;
        es.onmessage = function (e) {
          var msg;
          try { msg = JSON.parse(e.data); } catch (err) { return; }
          if (msg.type === "message" && msg.text) {
            setStreams(function (prev) {
              var n = Object.assign({}, prev);
              n[id] = (n[id] || "") + msg.text + "\n";
              return n;
            });
          } else if (msg.type === "tool_start") {
            setStreams(function (prev) {
              var n = Object.assign({}, prev);
              n[id] = (n[id] || "") + t("toolStarted", { name: msg.name }) + "\n";
              return n;
            });
          } else if (msg.type === "tool_done") {
            setStreams(function (prev) {
              var n = Object.assign({}, prev);
              n[id] = (n[id] || "") + t("toolCompleted", { name: msg.name }) + "\n";
              return n;
            });
          } else if (msg.type === "done" || msg.type === "error") {
            closeStream(id);
            load();
          }
        };
        es.onerror = function () {
          // Stream ended or errored; drop live view, polling refreshes result.
          closeStream(id);
        };
      } catch (e) {}
    }

    function onRun(issue) {
      if (!issue.assignee) {
        if (message) message.warning(t("assignBeforeRun"));
        return;
      }
      var url = host.getApiUrl("/agent-kanban/issues/" + issue.id + "/run?language=" + encodeURIComponent(locale));
      var token = host.getApiToken ? host.getApiToken() : "";
      var headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = "Bearer " + token;
      fetch(url, { method: "POST", headers: headers })
        .then(function (res) {
          if (!res.ok) throw new Error("HTTP " + res.status);
          return res.json();
        })
        .then(function (data) {
          load();
        })
        .catch(function (err) {
          if (message) message.error(t("runFailed", { error: err.message }));
          load();
        });
    }

    function onStop(issue) {
      closeStream(issue.id);
      api
        .stopIssue(issue.id)
        .then(function () {
          if (message) message.info(t("stopped"));
          load();
        })
        .catch(function () {
          load();
        });
    }

    function onDelete(issue) {
      setIssues(function (prev) {
        return prev.filter(function (i) {
          return i.id !== issue.id;
        });
      });
      api.deleteIssue(issue.id).then(load).catch(load);
    }

    function submitCreate() {
      if (!form.title.trim()) {
        if (message) message.warning(t("titleRequired"));
        return;
      }
      api
        .createIssue({
          title: form.title,
          description: form.description,
          assignee: form.assignee,
          status: modal.status,
          language: locale,
        })
        .then(function () {
          setModal(null);
          setForm({ title: "", description: "", assignee: "" });
          load();
        })
        .catch(function (err) {
          if (message) message.error(t("createFailed", { error: err.message }));
        });
    }

    function submitEdit() {
      if (!form.title.trim()) {
        if (message) message.warning(t("titleRequired"));
        return;
      }
      api
        .patchIssue(modal.editIssueId, {
          title: form.title,
          description: form.description,
          language: locale,
        })
        .then(function () {
          setModal(null);
          setForm({ title: "", description: "", assignee: "" });
          load();
        })
        .catch(function (err) {
          if (message) message.error(t("editFailed", { error: err.message }));
        });
    }

    function onEdit(issue) {
      setForm({
        title: issue.title,
        description: issue.description || "",
        assignee: issue.assignee || "",
      });
      setModal({ editIssueId: issue.id });
    }

    var working = issues.filter(function (i) {
      return i.status === "in_progress";
    }).length;

    // Build queue positions: for each agent that has a running
    // issue, number their todo issues sequentially.
    var busyAgents = {};
    issues.forEach(function (i) {
      if (i.status === "in_progress" && i.assignee) busyAgents[i.assignee] = true;
    });
    var queuePos = {};
    var agentCounter = {};
    issues.forEach(function (i) {
      if (i.status === "todo" && i.assignee && busyAgents[i.assignee]) {
        agentCounter[i.assignee] = (agentCounter[i.assignee] || 0) + 1;
        queuePos[i.id] = agentCounter[i.assignee];
      }
    });

    var agentOptions = [{ label: t("unassigned"), value: "" }].concat(
      agents.map(function (a) {
        return { label: a.name || a.id, value: a.id };
      }),
    );

    return h(
      "div",
      {
        style: {
          padding: 16,
          paddingTop: 24,
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: C.boardBg,
          color: C.text,
          boxSizing: "border-box",
        },
      },
      // Header
      h(
        "div",
        {
          style: {
            display: "flex",
            alignItems: "center",
            gap: 16,
            marginBottom: 14,
            marginRight: 100, // Reserve minimal space for floating capsule button
          },
        },
        h("div", { style: { fontSize: 18, fontWeight: 700, color: C.text } }, "📋 Agent Kanban"),
        h(ViewToggle, { view: view, onChange: setView, t: t }),
        h(
          "span",
          {
            style: {
              fontSize: 13,
              color: working ? "#d97706" : C.muted,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            },
          },
          h("span", {
            style: {
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: working ? "#f59e0b" : "#d1d5db",
              display: "inline-block",
            },
          }),
          working + " " + t("running"),
        ),
        h(Button, { size: "small", onClick: load }, t("refresh")),
      ),
      // Board area: issue columns or agent office
      view === "agents"
        ? h(AgentBoard, { agents: agents, issues: issues, t: t })
        : h(
        "div",
        {
          style: {
            display: "flex",
            gap: 14,
            flex: 1,
            overflowX: "auto",
            alignItems: "stretch",
            paddingBottom: 4,
          },
        },
        COLUMNS.map(function (col) {
          var colIssues = issues.filter(function (i) {
            return i.status === col.key;
          });
          var isHovered = dragOverColumn === col.key;
          return h(
            "div",
            {
              key: col.key,
              onDragOver: function (e) {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
              },
              onDragEnter: function (e) {
                e.preventDefault();
                setDragOverColumn(col.key);
              },
              onDragLeave: function (e) {
                // Only clear if leaving the column container itself
                if (e.currentTarget === e.target) {
                  setDragOverColumn(null);
                }
              },
              onDrop: function (e) {
                e.preventDefault();
                var id = e.dataTransfer.getData("text/plain");
                if (id) moveIssue(id, col.key);
                setDragOverColumn(null);
              },
              style: {
                flex: "1 1 260px",
                minWidth: 240,
                maxWidth: 420,
                background: isHovered
                  ? "linear-gradient(180deg, " + col.tint + " 0%, " + col.tint.replace('0.20', '0.35').replace('0.12', '0.25').replace('0.18', '0.30').replace('0.16', '0.28') + " 20%, rgba(255,255,255,0) 60%), #ffffff"
                  : "linear-gradient(180deg, " + col.tint + " 0%, rgba(255,255,255,0) 42%), #ffffff",
                border: isHovered ? "2px dashed " + col.dot : "1px solid rgba(15,23,42,0.05)",
                borderRadius: 14,
                padding: "12px 10px",
                maxHeight: "100%",
                display: "flex",
                flexDirection: "column",
                transition: "all 0.2s ease",
              },
            },
            // Column header
            h(
              "div",
              {
                style: {
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 12,
                  padding: "0 4px",
                },
              },
              h(
                "span",
                { style: { fontWeight: 600, color: C.text, display: "inline-flex", alignItems: "center", gap: 7 } },
                h("span", {
                  style: {
                    width: 9,
                    height: 9,
                    borderRadius: "50%",
                    background: col.dot,
                    display: "inline-block",
                  },
                }),
                t(col.labelKey),
                h("span", { style: { color: C.muted, marginLeft: 4, fontWeight: 400 } }, colIssues.length),
              ),
              col.key === "backlog"
                ? h(
                    Button,
                    {
                      type: "text",
                      size: "small",
                      style: { color: C.muted },
                      onClick: function () {
                        setForm({ title: "", description: "", assignee: "" });
                        setModal({ status: col.key });
                      },
                    },
                    "+",
                  )
                : null,
            ),
            // Column body
            h(
              "div",
              { style: { overflowY: "auto", flex: 1, minHeight: 80 } },
              colIssues.length === 0
                ? h(Empty, {
                    image: Empty.PRESENTED_IMAGE_SIMPLE,
                    description: h("span", { style: { color: C.muted } }, t("noIssues")),
                    style: { margin: "40px 0", opacity: 0.6 },
                  })
                : colIssues.map(function (issue) {
                    return h(IssueCard, {
                      key: issue.id,
                      issue: issue,
                      agents: agents,
                      locale: locale,
                      t: t,
                      onAssign: onAssign,
                      onMove: function (iss, st) { moveIssue(iss.id, st); },
                      onRun: onRun,
                      onStop: onStop,
                      onDelete: onDelete,
                      onEdit: onEdit,
                      onSubscribe: subscribeStream,
                      streamText: streams[issue.id],
                      queuePosition: queuePos[issue.id] || 0,
                      agentBusy: !!(issue.assignee && busyAgents[issue.assignee]),
                      pendingApprovals: approvals[issue.id] || [],
                      onApprove: function (reqId) {
                        api.approveRequest(reqId).then(function () {
                          if (message) message.success(t("approved"));
                          loadApprovals();
                        }).catch(function () {
                          if (message) message.error(t("approveFailed"));
                        });
                      },
                      onDeny: function (reqId) {
                        api.denyRequest(reqId).then(function () {
                          if (message) message.info(t("denied"));
                          loadApprovals();
                        }).catch(function () {
                          if (message) message.error(t("denyFailed"));
                        });
                      },
                    });
                  }),
            ),
          );
        }),
      ),
      // Create modal
      modal
        ? h(
            Modal,
            {
              open: true,
              title: modal.editIssueId
                ? t("editIssue")
                : t("newIssue", {
                    column: t((COLUMNS.find(function (column) { return column.key === modal.status; }) || {}).labelKey || ""),
                  }),
              okText: modal.editIssueId ? t("save") : t("create"),
              cancelText: t("cancel"),
              onOk: modal.editIssueId ? submitEdit : submitCreate,
              onCancel: function () {
                setModal(null);
                setForm({ title: "", description: "", assignee: "" });
              },
            },
            h(
              "div",
              { style: { display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 } },
              h(Input, {
                placeholder: t("title"),
                value: form.title,
                onChange: function (e) {
                  setForm(Object.assign({}, form, { title: e.target.value }));
                },
              }),
              h(Input.TextArea, {
                placeholder: t("descriptionOptional"),
                rows: 3,
                value: form.description,
                onChange: function (e) {
                  setForm(Object.assign({}, form, { description: e.target.value }));
                },
              }),
              // Only show assignee selector when creating (not editing)
              modal.editIssueId
                ? null
                : h(Select, {
                    placeholder: t("assigneeOptional"),
                    style: { width: "100%" },
                    value: form.assignee || "",
                    options: agentOptions,
                    onChange: function (val) {
                      setForm(Object.assign({}, form, { assignee: val }));
                    },
                  }),
            ),
          )
        : null,
    );
  }

  // ── Self-register route ─────────────────────────────────────────────────
  QwenPaw.registerRoutes("agent-kanban", [
    {
      path: "/apps/agent-kanban",
      component: KanbanBoard,
      label: "Agent Kanban",
      icon: "📋",
    },
  ]);

  console.info("[agent-kanban] registered route /apps/agent-kanban");
})();
