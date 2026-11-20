const api = QwenPawWorker;
const button = (text, action) => ({ tag: "button", text, action });
let state,
  access = [],
  notice = "";
let session = {};
api.registerRoute({
  id: "desktop",
  path: "/plugin/computer-use",
  label: api.t("桌面控制", "Computer use"),
  async render(input, event, context) {
    try {
      const action = event?.action;
      if (action?.startsWith("decide:")) {
        const [, decision, index] = action.split(":");
        const item = session.pending?.[Number(index)];
        if (item)
          await api.request("/session/pending/decision", {
            method: "POST",
            body: {
              session_id: context.sessionId,
              request_id: item.request_id,
              decision,
            },
          });
      }
      if (action === "enable" || action === "disable") {
        await api.request("/feature", {
          method: "POST",
          body: { enabled: action === "enable" },
        });
        notice = api.t("设置已更新", "Settings updated");
      }
      if (action === "stop" && context.sessionId) {
        await api.request("/session/stop", {
          method: "POST",
          body: { session_id: context.sessionId },
        });
        notice = api.t(
          "本会话的桌面操作已停止",
          "Desktop actions stopped for this session",
        );
      }
      if (action?.startsWith("revoke:")) {
        const item = access[Number(action.slice(7))];
        if (item)
          await api.request("/access", {
            method: "DELETE",
            body: { canonical_app_id: item.canonical_app_id },
          });
        notice = api.t("已撤销应用授权", "Application access revoked");
      }
      [state, { access }] = await Promise.all([
        api.request("/status"),
        api.request("/access"),
      ]);
      session = context.sessionId
        ? await api.request(
            "/session?session_id=" + encodeURIComponent(context.sessionId),
          )
        : {};
    } catch {
      state = null;
      access = [];
      notice = api.t(
        "无法管理宿主机桌面，请检查管理员权限与连接。",
        "Cannot manage this desktop. Check administrator access and the host connection.",
      );
    }
    return {
      tag: "section",
      children: [
        { tag: "h1", text: api.t("桌面控制", "Computer use") },
        button(api.t("刷新", "Refresh"), "refresh"),
        ...(state
          ? [
              {
                tag: "p",
                text: state.runtime_available
                  ? api.t("桌面运行环境可用", "Desktop runtime available")
                  : api.t("桌面运行环境不可用", "Desktop runtime unavailable"),
              },
              {
                tag: "p",
                text: state.connection_active
                  ? api.t("已连接", "Connected")
                  : api.t("尚未连接", "Disconnected"),
              },
              button(
                state.enabled
                  ? api.t("停用桌面控制", "Disable computer use")
                  : api.t("启用桌面控制", "Enable computer use"),
                state.enabled ? "disable" : "enable",
              ),
              ...(context.sessionId
                ? [
                    button(
                      api.t(
                        "停止当前会话的桌面操作",
                        "Stop desktop actions for this session",
                      ),
                      "stop",
                    ),
                  ]
                : []),
              ...(session.pending || [])
                .slice(0, 30)
                .map((item, i) => ({
                  tag: "section",
                  children: [
                    { tag: "p", text: item.app },
                    button(
                      api.t("本会话允许", "Allow this session"),
                      "decide:session:" + i,
                    ),
                    button(
                      api.t("始终允许", "Always allow"),
                      "decide:always:" + i,
                    ),
                    button(api.t("拒绝", "Deny"), "decide:deny:" + i),
                  ],
                })),
              {
                tag: "h2",
                text: api.t("已授权应用", "Authorized applications"),
              },
              ...access
                .slice(0, 80)
                .map((item, index) =>
                  button(
                    api.t("撤销 ", "Revoke ") + item.display_name,
                    "revoke:" + index,
                  ),
                ),
            ]
          : []),
        { tag: "p", text: notice },
      ],
    };
  },
});
