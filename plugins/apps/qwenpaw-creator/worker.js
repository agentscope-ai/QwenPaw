const api = QwenPawWorker;
const button = (text, action) => ({ tag: "button", text, action });
const field = (text, action, value) => ({
  tag: "label",
  text,
  children: [{ tag: "input", action, value }],
});
let projects = [],
  name = "",
  description = "",
  scenario = "general",
  selected = "",
  notice = "",
  deleting = false,
  page = 0;
let snapshot = {},
  nodes = [],
  conversation = "",
  messages = [],
  instruction = "",
  messageId = "",
  reviews = [];
let revision = {},
  edit = null;
const editSession = crypto.randomUUID();
const projectPath = () => "/projects/" + encodeURIComponent(selected);

function openProject(id) {
  selected = id;
  deleting = false;
  snapshot = {};
  nodes = [];
  conversation = "";
  messages = [];
  instruction = "";
  messageId = "";
  reviews = [];
  edit = null;
}

async function readProject() {
  const path = projectPath();
  const [document, graph, conversations, active] = await Promise.all([
    api.request(path + "/project"),
    api.request(path + "/work-graph"),
    api.request(path + "/conversations"),
    api.request(path + "/runtime/reviews/active"),
  ]);
  revision = { baseGeneration: document.generation, baseEtag: document.etag };
  snapshot = document.project;
  reviews = Array.isArray(active) ? active : [];
  nodes = graph.nodes || [];
  conversation ||= (
    conversations.items.find((c) => c.isDefault) || conversations.items[0]
  )?.conversationId;
  if (conversation)
    messages = (
      await api.request(
        path +
          "/conversations/" +
          encodeURIComponent(conversation) +
          "/messages?limit=50",
      )
    ).items;
}

function editableFields() {
  const result = [
    {
      label: api.t("项目标题", "Project title"),
      path: "/name",
      value: snapshot.name,
    },
    {
      label: api.t("项目说明", "Project description"),
      path: "/description",
      value: snapshot.description,
    },
  ];
  const escape = (key) => key.replace(/~/g, "~0").replace(/\//g, "~1");
  for (const timeline of Object.values(snapshot.timelines?.items || {})) {
    for (const element of Object.values(timeline.elements_by_id || {})) {
      if (result.length >= 82) break;
      const path =
        "/timelines/items/" +
        escape(timeline.timeline_id) +
        "/elements_by_id/" +
        escape(element.element_id) +
        "/span/";
      for (const [key, label] of [
        ["start_tick", api.t("开始刻度", "Start tick")],
        ["duration_tick", api.t("时长刻度", "Duration in ticks")],
      ]) {
        result.push({
          label: (element.label || element.element_id) + " · " + label,
          path: path + key,
          value: element.span[key],
          min: key === "start_tick" ? 0 : 1,
        });
      }
    }
  }
  return result;
}

async function saveEdit() {
  const value =
    typeof edit.value === "number" ? Number(edit.draft) : edit.draft;
  if (
    edit.min !== undefined &&
    (!edit.draft.trim() || !Number.isSafeInteger(value) || value < edit.min)
  ) {
    notice = api.t("请输入有效的时间刻度", "Enter a valid timeline tick");
    return;
  }
  const bytes = new TextEncoder().encode(JSON.stringify(edit.value));
  const hash = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
  await api.request(projectPath() + "/project", {
    method: "PATCH",
    idempotencyKey: edit.id,
    body: {
      ...edit.revision,
      clientCommandId: edit.id,
      editSessionId: editSession,
      operations: [
        {
          op: "replace",
          path: edit.path,
          value,
          expectedValueHash: "sha256:" + hash,
        },
      ],
    },
  });
  edit = null;
  notice = api.t("修改已保存", "Changes saved");
}

function reviewRows() {
  return reviews
    .flatMap((r) =>
      r.operations
        .filter((o) => o.decision === "PENDING")
        .map((o) => ({ review: r, operation: o })),
    )
    .slice(0, 15);
}

function mediaNode(version, collection) {
  const path =
    "/media/" + collection + "/" + encodeURIComponent(version.version_id);
  const file = snapshot.assets?.files_by_id?.[version.file_id];
  const mime = version.media_type || file?.media_type || "";
  return {
    tag: "section",
    children: [
      { tag: "p", text: version.name || version.version_id },
      ...(/^(image|audio|video)\//.test(mime)
        ? [
            {
              tag: "file-action",
              mode: "preview",
              text: api.t("预览素材", "Preview media"),
              path,
            },
          ]
        : []),
      {
        tag: "file-action",
        mode: "download",
        text: api.t("下载素材", "Download media"),
        path,
        filename: version.name || version.version_id,
      },
    ],
  };
}
let requestId = "";
const scenarios = {
  general: api.t("通用项目", "General"),
  short_drama: api.t("短剧", "Short drama"),
  video_edit: api.t("视频剪辑", "Video editing"),
};
api.registerRoute({
  id: "projects",
  path: "/apps/qwenpaw-creator",
  label: "QwenPaw Creator",
  async render(input, event) {
    const action = event?.action;
    try {
      if (action === "name") {
        name = event.value;
        requestId = "";
      } else if (action === "description") {
        description = event.value;
        requestId = "";
      } else if (action === "instruction") {
        instruction = event.value;
        messageId = "";
      } else if (action === "edit-value" && edit) {
        edit.draft = event.value;
        edit.id = crypto.randomUUID();
      } else if (action?.startsWith("scenario:")) {
        scenario = action.slice(9);
        requestId = "";
      } else {
        notice = "";
        if (action === "create" && name.trim()) {
          requestId ||= crypto.randomUUID();
          const created = await api.request("/projects", {
            method: "POST",
            body: {
              clientRequestId: requestId,
              name: name.trim(),
              description,
              scenario,
            },
          });
          openProject(created.projectId);
          conversation = created.conversationId;
          page = 0;
          requestId = "";
          name = "";
          description = "";
          notice = api.t("项目已创建", "Project created");
        }
        if (action?.startsWith("open:")) openProject(action.slice(5));
        if (action === "back") openProject("");
        if (selected && action?.startsWith("edit:")) {
          const field = editableFields()[Number(action.slice(5))];
          if (field)
            edit = {
              ...field,
              revision,
              draft: String(field.value ?? ""),
              id: crypto.randomUUID(),
            };
        }
        if (action === "cancel-edit") edit = null;
        if (edit && action === "save-edit") await saveEdit();
        if (selected && action?.startsWith("decide:")) {
          const [, decision, index] = action.split(":");
          const row = reviewRows()[Number(index)];
          if (row && ["ACCEPT", "REJECT"].includes(decision)) {
            const key = crypto.randomUUID();
            await api.request(
              projectPath() +
                "/runtime/reviews/" +
                encodeURIComponent(row.review.review_id) +
                "/decisions",
              {
                method: "POST",
                idempotencyKey: key,
                body: {
                  decisionId: key,
                  decisionToken: row.review.decision_token,
                  decisions: [
                    { operation_id: row.operation.operation_id, decision },
                  ],
                },
              },
            );
          }
        }
        if (selected && action === "delete") deleting = true;
        if (selected && deleting && action === "delete-confirm") {
          await api.request(projectPath(), {
            method: "DELETE",
            idempotencyKey: crypto.randomUUID(),
          });
          openProject("");
        }
        if (
          selected &&
          conversation &&
          action === "send" &&
          instruction.trim()
        ) {
          messageId ||= crypto.randomUUID();
          await api.request(projectPath() + "/messages", {
            method: "POST",
            idempotencyKey: messageId,
            body: {
              clientMessageId: messageId,
              conversationId: conversation,
              message: instruction.trim(),
            },
          });
          instruction = "";
          messageId = "";
          notice = api.t("创作指令已提交", "Instruction sent");
        }
        if (selected && action?.startsWith("dispatch:")) {
          const node = nodes.find((n) => n.id === action.slice(9));
          if (node?.dispatchable) {
            await api.request(
              projectPath() +
                "/work-graph/nodes/" +
                encodeURIComponent(node.id) +
                "/dispatch",
              { method: "POST" },
            );
            notice = api.t("制作任务已提交", "Production task submitted");
          }
        }
        if (action === "next") page++;
        if (action === "prev" && page > 0) page--;
        projects = (await api.request("/projects?limit=20&offset=" + page * 20))
          .items;
        if (selected) await readProject();
      }
    } catch {
      notice = api.t(
        "项目操作未完成，请检查权限或重试。",
        "The operation failed. Check your access or refresh the project.",
      );
    }
    const row = projects.find((p) => p.projectId === selected);
    return {
      tag: "section",
      children: [
        { tag: "h1", text: api.t("创作项目", "Creative projects") },
        button(api.t("刷新", "Refresh"), "refresh"),
        ...projects.map((p) => button(p.name, "open:" + p.projectId)),
        ...(page ? [button(api.t("上一页", "Previous page"), "prev")] : []),
        ...(projects.length === 20
          ? [button(api.t("下一页", "Next page"), "next")]
          : []),
        ...(selected
          ? [
              {
                tag: "h2",
                text:
                  snapshot.name ||
                  row?.name ||
                  api.t("项目详情", "Project details"),
              },
              button(api.t("返回列表", "Back to projects"), "back"),
              { tag: "p", text: snapshot.description || "" },
              {
                tag: "h3",
                text: api.t("项目与时间线编辑", "Edit project and timeline"),
              },
              ...editableFields().map((f, i) =>
                button(f.label + " · " + String(f.value ?? ""), "edit:" + i),
              ),
              ...(edit
                ? [
                    field(api.t("新值", "New value"), "edit-value", edit.draft),
                    button(api.t("保存修改", "Save changes"), "save-edit"),
                    button(api.t("取消编辑", "Cancel edit"), "cancel-edit"),
                  ]
                : []),
              { tag: "h3", text: api.t("创作对话", "Creative conversation") },
              ...messages.slice(-12).map((m) => ({
                tag: "p",
                text:
                  m.role +
                  " · " +
                  (m.content || [])
                    .map((part) => part.text || "")
                    .join(" ")
                    .slice(0, 1800),
              })),
              field(
                api.t("创作或修改指令", "Creation or editing instruction"),
                "instruction",
                instruction,
              ),
              {
                ...button(api.t("发送创作指令", "Send instruction"), "send"),
                disabled: !conversation || !instruction.trim(),
              },
              { tag: "h3", text: api.t("制作进度", "Production progress") },
              ...nodes
                .slice(0, 50)
                .map((n) => ({
                  tag: "section",
                  children: [
                    {
                      tag: "p",
                      text:
                        n.label +
                        " · " +
                        n.status +
                        (n.error ? " · " + n.error : ""),
                    },
                    ...(n.dispatchable
                      ? [
                          button(
                            api.t("执行 ", "Run ") + n.label,
                            "dispatch:" + n.id,
                          ),
                        ]
                      : []),
                  ],
                })),
              ...reviewRows().map(({ operation }, i) => ({
                tag: "section",
                children: [
                  {
                    tag: "pre",
                    text:
                      (operation.json_pointer || operation.operation_id) +
                      "\n" +
                      JSON.stringify(operation.before ?? null).slice(0, 500) +
                      " → " +
                      JSON.stringify(operation.after ?? null).slice(0, 500),
                  },
                  button(
                    api.t("接受变更", "Accept change"),
                    "decide:ACCEPT:" + i,
                  ),
                  button(
                    api.t("拒绝变更", "Reject change"),
                    "decide:REJECT:" + i,
                  ),
                ],
              })),
              { tag: "h3", text: api.t("素材与产物", "Media and outputs") },
              {
                tag: "file-action",
                mode: "upload",
                text: api.t("导入项目素材", "Import media"),
                path: projectPath() + "/assets",
                action: "refresh",
              },
              ...Object.values(snapshot.assets?.source_versions_by_id || {})
                .slice(0, 30)
                .map((v) => mediaNode(v, "assets")),
              ...Object.values(snapshot.assets?.artifact_versions_by_id || {})
                .slice(0, 30)
                .map((v) => mediaNode(v, "artifacts")),
              ...(row?.finalVideoVersionId
                ? [
                    {
                      tag: "file-action",
                      mode: "preview",
                      text: api.t("预览最终成片", "Preview final video"),
                      path:
                        "/media/artifacts/" +
                        encodeURIComponent(row.finalVideoVersionId),
                    },
                  ]
                : []),
              {
                tag: "file-action",
                mode: "download",
                text: api.t("导出项目 ZIP", "Export project ZIP"),
                path: projectPath() + "/export",
                filename: (row?.name || api.t("项目", "Project")) + ".zip",
              },
              deleting
                ? button(
                    api.t("确认删除项目", "Confirm project deletion"),
                    "delete-confirm",
                  )
                : button(api.t("删除项目", "Delete project"), "delete"),
            ]
          : []),
        { tag: "h2", text: api.t("创建项目", "Create a project") },
        field(api.t("项目名称", "Project name"), "name", name),
        field(api.t("项目描述", "Description"), "description", description),
        ...Object.entries(scenarios).map(([key, text]) => ({
          ...button(text, "scenario:" + key),
          disabled: key === scenario,
        })),
        {
          ...button(api.t("创建", "Create"), "create"),
          disabled: !name.trim(),
        },
        { tag: "p", text: notice },
      ],
    };
  },
});
