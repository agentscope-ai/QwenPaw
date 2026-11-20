const api = QwenPawWorker;
const button = (text, action) => ({ tag: "button", text, action });
const field = (text, action, value) => ({
  tag: "label",
  text,
  children: [{ tag: "input", action, value }],
});
const statuses = {
  backlog: api.t("待规划", "Backlog"),
  todo: api.t("等待调度", "Queued"),
  in_progress: api.t("进行中", "In progress"),
  review: api.t("审核中", "Review"),
  done: api.t("已完成", "Done"),
};
let issues = [],
  title = "",
  description = "",
  selected = "",
  output = "",
  notice = "",
  deleteId = "";
let approvals = [];

api.registerRoute({
  id: "board",
  path: "/apps/agent-kanban",
  label: api.t("任务看板", "Task board"),
  async render(input, event, context) {
    const action = event?.action;
    const item = issues.find((row) => row.id === selected);
    try {
      if (action === "title") title = event.value;
      else if (action === "description") description = event.value;
      else {
        notice = "";
        if (action?.startsWith("select:")) {
          selected = action.slice(7);
          const row = issues.find((issue) => issue.id === selected);
          title = row.title;
          description = row.description;
          output = "";
          deleteId = "";
        }
        if (action === "new") {
          selected = "";
          title = "";
          description = "";
          output = "";
        }
        if (action === "save" && title.trim()) {
          const result = await api.request(
            item ? "/issues/" + item.id : "/issues",
            {
              method: item ? "PATCH" : "POST",
              body: { title: title.trim(), description },
            },
          );
          selected = result.id;
          notice = api.t("已保存", "Saved");
        }
        if (item && action === "run") {
          if (!item.assignee) {
            await api.request("/issues/" + item.id, {
              method: "PATCH",
              body: { status: "todo", assignee: context.agentId },
            });
          } else {
            await api.request("/issues/" + item.id + "/run", {
              method: "POST",
            });
          }
        }
        if (item && action === "stop")
          await api.request("/issues/" + item.id + "/stop", { method: "POST" });
        if (item && action === "done")
          await api.request("/issues/" + item.id, {
            method: "PATCH",
            body: { status: "done" },
          });
        if (item && action === "result") {
          const result = await api.request("/issues/" + item.id + "/result");
          output =
            result.error ||
            (result.messages || [])
              .flatMap((m) => (m.content || []).map((b) => b.text || b.type))
              .join("\n") ||
            api.t("暂无结果", "No results yet");
        }
        if (item && action?.startsWith("decision:")) {
          const [, decision, index] = action.split(":");
          const pending = approvals[Number(index)];
          if (pending && ["approve", "deny"].includes(decision)) {
            await api.request(
              "/approvals/" +
                encodeURIComponent(pending.request_id) +
                "/" +
                decision,
              { method: "POST" },
            );
          }
        }
        if (item && action === "delete") deleteId = item.id;
        if (item && deleteId === item.id && action === "delete-confirm") {
          await api.request("/issues/" + item.id, { method: "DELETE" });
          selected = "";
          deleteId = "";
          title = "";
          description = "";
          output = "";
        }
        const board = await api.request("/issues");
        issues = board.issues;
        approvals = issues.some(
          (i) => i.id === selected && i.status === "in_progress",
        )
          ? (await api.request("/approvals")).approvals[selected] || []
          : [];
      }
    } catch {
      notice = api.t(
        "操作未完成，请检查访问权限后刷新。",
        "The operation failed. Check your access and refresh.",
      );
    }
    const active = issues.find((row) => row.id === selected);
    return {
      tag: "section",
      children: [
        { tag: "h1", text: api.t("任务看板", "Task board") },
        button(api.t("刷新", "Refresh"), "refresh"),
        button(api.t("新建任务", "New task"), "new"),
        ...Object.entries(statuses).map(([key, label]) => ({
          tag: "section",
          children: [
            { tag: "h2", text: label },
            ...issues
              .filter((row) => row.status === key)
              .slice(0, 50)
              .map((row) => button(row.title, "select:" + row.id)),
          ],
        })),
        {
          tag: "h2",
          text: active
            ? api.t("编辑任务", "Edit task")
            : api.t("新建任务", "New task"),
        },
        field(api.t("标题", "Title"), "title", title),
        field(api.t("描述", "Description"), "description", description),
        { ...button(api.t("保存", "Save"), "save"), disabled: !title.trim() },
        ...(active
          ? [
              active.status === "in_progress"
                ? button(api.t("停止", "Stop"), "stop")
                : button(
                    api.t("交给当前智能体", "Assign to current agent"),
                    "run",
                  ),
              button(api.t("查看执行结果", "View result"), "result"),
              button(api.t("标为完成", "Mark as done"), "done"),
              deleteId === active.id
                ? button(
                    api.t("确认删除任务", "Confirm task deletion"),
                    "delete-confirm",
                  )
                : button(api.t("删除任务", "Delete task"), "delete"),
            ]
          : []),
        ...approvals
          .slice(0, 20)
          .map((p, i) => ({
            tag: "section",
            children: [
              {
                tag: "p",
                text: [p.tool_name, p.exact_target, p.severity]
                  .filter(Boolean)
                  .join(" · "),
              },
              button(
                api.t("允许执行", "Allow execution"),
                "decision:approve:" + i,
              ),
              button(api.t("拒绝执行", "Deny execution"), "decision:deny:" + i),
            ],
          })),
        ...(output ? [{ tag: "pre", text: output.slice(0, 12000) }] : []),
        notice,
      ],
    };
  },
});
