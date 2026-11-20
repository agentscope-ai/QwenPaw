const api = QwenPawWorker;
const button = (text, action) => ({ tag: "button", text, action });
let mode = "unpacked",
  notice = "";
let diagnosis = "";

api.registerRoute({
  id: "chrome",
  path: "/plugin/chrome",
  label: api.t("Chrome 浏览器", "Chrome browser"),
  async render(input, event) {
    let status;
    try {
      if (event?.action === "mode")
        mode = mode === "unpacked" ? "cws" : "unpacked";
      if (event?.action === "setup") {
        await api.request("/setup", {
          method: "POST",
          body: { install_mode: mode, reset: false },
        });
        notice = api.t("已完成安装检查", "Installation checked");
      }
      if (event?.action === "diagnose") {
        const report = await api.request("/self-test", { method: "POST" });
        diagnosis = JSON.stringify(report, null, 2).slice(0, 16000);
      }
      if (event?.action === "extensions" || event?.action === "folder") {
        const path =
          event.action === "extensions"
            ? "/open-chrome-extensions"
            : "/open-extension-folder";
        const result = await api.request(path, { method: "POST" });
        notice = result.opened
          ? api.t("已打开", "Opened")
          : result.error ||
            result.path ||
            api.t("请先连接 Chrome", "Connect Chrome first");
      }
      status = await api.request("/install-status");
    } catch {
      notice = api.t(
        "无法读取或管理宿主机 Chrome，请检查管理员权限和桥接服务。",
        "Cannot manage Chrome. Check your administrator access and bridge connection.",
      );
    }
    return {
      tag: "section",
      children: [
        { tag: "h1", text: api.t("Chrome 浏览器", "Chrome browser") },
        button(api.t("刷新安装状态", "Refresh installation status"), "refresh"),
        ...(status
          ? [
              {
                tag: "p",
                text: status.installed
                  ? api.t("扩展已安装", "Extension installed")
                  : api.t("扩展尚未安装", "Extension not installed"),
              },
              {
                tag: "p",
                text:
                  status.recovery_copy ||
                  status.native_host_repair_instruction ||
                  status.setup_phase ||
                  "",
              },
              button(
                mode === "unpacked"
                  ? api.t(
                      "安装方式：本地扩展",
                      "Installation method: local extension",
                    )
                  : api.t(
                      "安装方式：Chrome 应用商店",
                      "Installation method: Chrome Web Store",
                    ),
                "mode",
              ),
              button(
                api.t("安装或修复桥接", "Install or repair bridge"),
                "setup",
              ),
              button(
                api.t("打开扩展管理", "Open extension manager"),
                "extensions",
              ),
              button(api.t("打开扩展目录", "Open extension folder"), "folder"),
            ]
          : []),
        ...(status
          ? [button(api.t("桥接诊断", "Diagnose bridge"), "diagnose")]
          : []),
        ...(status && diagnosis ? [{ tag: "pre", text: diagnosis }] : []),
        { tag: "p", text: notice },
      ],
    };
  },
});
