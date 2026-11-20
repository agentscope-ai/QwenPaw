const api = QwenPawWorker;
const button = (text, action) => ({ tag: "button", text, action });
let pets = [],
  desktop,
  path = "",
  notice = "";
api.registerRoute({
  id: "pets",
  path: "/plugin/qwenpaw-pet/pets",
  label: api.t("桌面宠物", "Desktop pets"),
  async render(input, event) {
    const action = event?.action;
    if (action === "path") path = event.value;
    else
      try {
        if (action === "start") {
          const reply = await api.request("/desktop/start", { method: "POST" });
          notice =
            reply.error ||
            api.t("桌面启动请求已发送", "Desktop start requested");
        }
        if (action?.startsWith("switch:")) {
          const pet = pets[Number(action.slice(7))];
          if (pet) {
            const reply = await api.request("/switch-pet", {
              method: "POST",
              body: { pet_id: pet.folder },
            });
            notice =
              reply.error ||
              api.t("已切换到 ", "Switched to ") + pet.displayName;
          }
        }
        if (action === "import" && path.trim()) {
          await api.request("/import-pet", {
            method: "POST",
            body: { path: path.trim(), replace: false },
          });
          notice = api.t("已导入宠物", "Pet imported");
          path = "";
        }
        const [status, list] = await Promise.all([
          api.request("/status"),
          api.request("/pets"),
        ]);
        desktop = status.desktop;
        pets = list.pets;
      } catch {
        desktop = null;
        pets = [];
        notice = api.t(
          "宠物操作未完成，请检查管理员权限或重新刷新。",
          "The operation failed. Check administrator access and refresh.",
        );
      }
    return {
      tag: "section",
      children: [
        { tag: "h1", text: api.t("桌面宠物", "Desktop pets") },
        button(api.t("刷新宠物列表", "Refresh pets"), "refresh"),
        ...(desktop
          ? [
              {
                tag: "p",
                text: desktop.running
                  ? api.t("桌面宠物运行中", "Pet is running")
                  : api.t("桌面宠物未启动", "Pet is stopped"),
              },
              button(api.t("启动桌面宠物", "Start desktop pet"), "start"),
              ...pets
                .slice(0, 80)
                .map((pet, index) => ({
                  tag: "section",
                  children: [
                    button(
                      api.t("切换到 ", "Switch to ") + pet.displayName,
                      "switch:" + index,
                    ),
                    {
                      tag: "file-action",
                      mode: "preview",
                      text: api.t("预览 ", "Preview ") + pet.displayName,
                      path:
                        "/pets/" +
                        encodeURIComponent(pet.folder) +
                        "/spritesheet",
                    },
                  ],
                })),
              {
                tag: "file-action",
                mode: "upload-files",
                text: api.t(
                  "上传宠物 ZIP 或 pet.json 和精灵图",
                  "Upload a pet ZIP or pet.json with its sprite sheet",
                ),
                path: "/import-pet-upload",
              },
              {
                tag: "label",
                text: api.t(
                  "宿主机上的宠物目录或 ZIP",
                  "Pet folder or ZIP on the host",
                ),
                children: [{ tag: "input", value: path, action: "path" }],
              },
              {
                ...button(api.t("导入宠物", "Import pet"), "import"),
                disabled: !path.trim(),
              },
            ]
          : []),
        { tag: "p", text: notice },
      ],
    };
  },
});
