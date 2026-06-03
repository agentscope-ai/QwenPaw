/** Pet plugin UI locale — follows QwenPaw console ``localStorage.language``. */

import { readConsoleLanguage } from "./watchConsoleLanguage";

export type PetLocale = "zh" | "en";

export type MessageKey = keyof typeof messages.en;

const messages = {
  en: {
    routeLabel: "Pet",
    title: "QwenPaw Pet",
    intro:
      "Installed pets live under your QwenPaw working directory. Start the desktop bridge, then switch the floating pet without restarting QwenPaw.",
    startDesktop: "Start desktop pet",
    importPet: "Import pet",
    refresh: "Refresh",
    petsDirectory: "Pets directory:",
    desktopHealth: "Desktop health:",
    desktopUnknown: "unknown (refresh)",
    colPreview: "Preview",
    colName: "Name",
    colFolder: "Folder",
    colManifestId: "pet.json id",
    colAction: "Action",
    switch: "Switch",
    tableEmpty: "No pets found. Run: qwenpaw-pet install-pet …",
    desktopAlreadyRunning: "Desktop pet is already running.",
    desktopStartFailed: "Could not start the desktop pet.",
    desktopReady: "Desktop pet is ready.",
    desktopStarting:
      "Desktop may still be starting; check pet-desktop.log if needed.",
    dropFolderOrZip: "Drop a folder or a .zip file.",
    importChooseFirst: "Drop a folder or choose a .zip file first.",
    importSuccess: 'Imported "{name}" → {path}',
    switchSuccess: 'Switched to "{name}" ({petId})',
    switchFailed: "switch failed",
    modalImportTitle: "Import pet",
    modalImportOk: "Import",
    dropzoneTitle: "Drop a folder or .zip file here",
    dropzoneHint: "or click to choose a .zip",
    importFormatHint:
      "Folder or unzipped archive must contain pet.json and spritesheet.webp (1536×1872).",
    selectedOne: "Selected: {path}",
    selectedMany: "Selected: {count} files (root: {root})",
    importReplace: "Replace if a pet with the same id already exists",
  },
  zh: {
    routeLabel: "宠物",
    title: "QwenPaw 桌面宠物",
    intro:
      "已安装的宠物位于 QwenPaw 工作目录下。启动桌面桥接后，可在不重启 QwenPaw 的情况下切换悬浮宠物。",
    startDesktop: "启动桌面宠物",
    importPet: "导入宠物",
    refresh: "刷新",
    petsDirectory: "宠物目录：",
    desktopHealth: "桌面服务状态：",
    desktopUnknown: "未知（请刷新）",
    colPreview: "预览",
    colName: "名称",
    colFolder: "文件夹",
    colManifestId: "pet.json id",
    colAction: "操作",
    switch: "切换",
    tableEmpty: "未找到宠物。请运行：qwenpaw-pet install-pet …",
    desktopAlreadyRunning: "桌面宠物已在运行。",
    desktopStartFailed: "无法启动桌面宠物。",
    desktopReady: "桌面宠物已就绪。",
    desktopStarting: "桌面可能仍在启动中；如有问题请查看 pet-desktop.log。",
    dropFolderOrZip: "请拖入文件夹或 .zip 文件。",
    importChooseFirst: "请先拖入文件夹或选择 .zip 文件。",
    importSuccess: "已导入「{name}」→ {path}",
    switchSuccess: "已切换至「{name}」（{petId}）",
    switchFailed: "切换失败",
    modalImportTitle: "导入宠物",
    modalImportOk: "导入",
    dropzoneTitle: "将文件夹或 .zip 拖放到此处",
    dropzoneHint: "或点击选择 .zip 文件",
    importFormatHint:
      "文件夹或解压后的目录需包含 pet.json 与 spritesheet.webp（1536×1872）。",
    selectedOne: "已选择：{path}",
    selectedMany: "已选择：{count} 个文件（根目录：{root}）",
    importReplace: "若已存在相同 id 的宠物则覆盖",
  },
} as const;

/** Map QwenPaw console language to pet UI locale (non zh/en → en). */
export function toPetLocale(language: string | null | undefined): PetLocale {
  const base = String(language || "")
    .trim()
    .split("-")[0]
    .toLowerCase();
  if (base === "zh") return "zh";
  return "en";
}

export function resolvePetLocale(language?: string | null): PetLocale {
  return toPetLocale(language ?? readConsoleLanguage());
}

export function t(
  locale: PetLocale,
  key: MessageKey,
  params?: Record<string, string | number>,
): string {
  let text: string = messages[locale][key] ?? messages.en[key];
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}
