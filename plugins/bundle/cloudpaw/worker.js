const api = QwenPawWorker;
const button = (text, action) => ({ tag: "button", text, action });
const field = (text, action, value) => ({
  tag: "label",
  text,
  children: [{ tag: "input", action, value }],
});
const parse = (value) => {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
};
function content(input) {
  const blocks = input?.data?.content || input?.content || [];
  return {
    args: parse(blocks[0]?.data?.arguments) || {},
    output: parse(blocks[1]?.data?.output),
    id: blocks[0]?.data?.call_id || input?.data?.id,
  };
}
function readable(value) {
  return (
    typeof value === "string" ? value : JSON.stringify(value ?? "", null, 2)
  ).slice(0, 20000);
}
let approvals = new Map();
api.registerTool({
  id: "proposal",
  tool: "proposal_choice",
  async render(input, event, context) {
    const call = content(input);
    const key = context.sessionId + "/" + (call.id || "");
    const action = event?.action;
    let state = approvals.get(key);
    try {
      if (call.output || !context.sessionId) {
        approvals.delete(key);
        return { tag: "pre", text: readable(call.output || call.args.data) };
      }
      if (!state || action === "refresh") {
        const pending = await api.request(
          "/interaction/pending?session_id=" +
            encodeURIComponent(context.sessionId),
        );
        if (!pending)
          return {
            tag: "section",
            children: [
              api.t(
                "此会话当前没有待确认方案",
                "No pending proposal in this session",
              ),
              button(api.t("刷新", "Refresh"), "refresh"),
            ],
          };
        if (approvals.size >= 100)
          approvals.delete(approvals.keys().next().value);
        state = { pending, index: 0, note: "", message: "" };
        approvals.set(key, state);
      }
      if (action?.startsWith("choose:")) state.index = Number(action.slice(7));
      if (action === "note") state.note = event.value;
      const name = state.pending.names[state.index];
      if (
        name &&
        (action === "confirm" || (action === "adjust" && state.note.trim()))
      ) {
        const result =
          action === "confirm"
            ? "用户选择了「" + name + "」并确认部署"
            : "用户选择「" + name + "」并要求调整：" + state.note.trim();
        await api.request("/interaction", {
          method: "POST",
          body: {
            session_id: context.sessionId,
            pending_id: state.pending.id,
            result,
          },
        });
        state.message = result;
      }
      if (state.message) return { tag: "p", text: state.message };
      return {
        tag: "section",
        children: [
          {
            tag: "h3",
            text: api.t(
              "当前待确认的云资源方案",
              "Pending cloud resource proposal",
            ),
          },
          ...state.pending.names
            .slice(0, 20)
            .map((label, index) => ({
              ...button(label, "choose:" + index),
              disabled: state.index === index,
            })),
          {
            tag: "table",
            children: (state.pending.proposals[state.index] || [])
              .slice(0, 32)
              .map((row) => ({
                tag: "tr",
                children: row
                  .slice(0, 12)
                  .map((cell) => ({
                    tag: "td",
                    text: String(cell?.text ?? cell).slice(0, 256),
                  })),
              })),
          },
          field(api.t("调整意见", "Change request"), "note", state.note),
          {
            ...button(api.t("提交调整", "Request changes"), "adjust"),
            disabled: !state.note.trim(),
          },
          button(
            api.t(
              "确认部署所选方案",
              "Confirm deployment of selected proposal",
            ),
            "confirm",
          ),
        ],
      };
    } catch {
      return {
        tag: "section",
        children: [
          api.t(
            "方案已失效或当前账号无权操作",
            "This proposal expired or you no longer have access",
          ),
          button(api.t("重新读取", "Reload"), "refresh"),
        ],
      };
    }
  },
});
for (const [tool, label] of [
  ["manage_prd", api.t("需求文档", "Requirements document")],
  ["a2a_call", api.t("智能体调用", "Agent call")],
]) {
  api.registerTool({
    id: tool,
    tool,
    render(input) {
      const call = content(input);
      return {
        tag: "section",
        children: [
          { tag: "h3", text: label },
          { tag: "pre", text: readable(call.output || call.args) },
        ],
      };
    },
  });
}
let agents = [],
  url = "",
  alias = "",
  notice = "";
let editing = "",
  remove = "",
  rename = "",
  instruction = "",
  response = "";
api.registerRoute({
  id: "a2a",
  path: "/plugin/cloudpaw/a2a",
  label: api.t("A2A 智能体", "A2A agents"),
  async render(input, event) {
    const action = event?.action;
    if (action === "url") url = event.value;
    else if (action === "alias") alias = event.value;
    else if (action === "rename-value") rename = event.value;
    else if (action === "instruction") instruction = event.value;
    else
      try {
        if (action?.startsWith("open:")) {
          editing = agents[Number(action.slice(5))]?.alias || "";
          rename = editing;
          remove = "";
          response = "";
        }
        const query = "?alias=" + encodeURIComponent(editing);
        if (editing && action === "refresh-agent")
          await api.request("/a2a/agents/refresh" + query, { method: "POST" });
        if (editing && action === "rename" && rename.trim()) {
          await api.request("/a2a/agents" + query, {
            method: "PUT",
            body: { new_alias: rename.trim() },
          });
          editing = rename.trim();
        }
        if (editing && action === "remove") remove = editing;
        if (editing && remove === editing && action === "remove-confirm") {
          await api.request("/a2a/agents" + query, { method: "DELETE" });
          editing = "";
          remove = "";
        }
        if (editing && action === "call" && instruction.trim()) {
          const result = await api.request("/a2a/call", {
            method: "POST",
            body: { agent_alias: editing, message: instruction.trim() },
          });
          response = readable(result.error || result.response_text || result);
          instruction = "";
        }
        if (action === "register" && url.trim()) {
          await api.request("/a2a/agents", {
            method: "POST",
            body: { url: url.trim(), alias: alias.trim() },
          });
          url = "";
          alias = "";
          notice = api.t("已添加智能体", "Agent added");
        }
        agents = (await api.request("/a2a/agents")).agents;
      } catch {
        notice = api.t(
          "无法读取或修改 A2A 连接，请检查配置管理权限。",
          "Cannot manage A2A connections. Check your settings permissions.",
        );
      }
    return {
      tag: "section",
      children: [
        { tag: "h1", text: api.t("A2A 智能体", "A2A agents") },
        button(api.t("刷新连接", "Refresh connections"), "refresh"),
        ...agents
          .slice(0, 50)
          .map((a) => ({
            tag: "p",
            text: (a.alias || a.name || a.url) + " · " + a.status,
          })),
        ...agents
          .slice(0, 50)
          .map((a, i) => button(a.alias || a.name || a.url, "open:" + i)),
        ...(editing
          ? [
              field(api.t("新别名", "New alias"), "rename-value", rename),
              button(api.t("保存别名", "Save alias"), "rename"),
              button(
                api.t("刷新智能体名片", "Refresh agent card"),
                "refresh-agent",
              ),
              remove === editing
                ? button(
                    api.t("确认删除连接", "Confirm removal"),
                    "remove-confirm",
                  )
                : button(api.t("删除连接", "Remove connection"), "remove"),
              field(
                api.t("发给智能体的消息", "Message to agent"),
                "instruction",
                instruction,
              ),
              {
                ...button(api.t("发送消息", "Send message"), "call"),
                disabled: !instruction.trim(),
              },
              ...(response ? [{ tag: "pre", text: response }] : []),
            ]
          : []),
        field(api.t("服务地址", "Service URL"), "url", url),
        field(api.t("别名", "Alias"), "alias", alias),
        {
          ...button(api.t("添加连接", "Add connection"), "register"),
          disabled: !url.trim(),
        },
        notice,
      ],
    };
  },
});
