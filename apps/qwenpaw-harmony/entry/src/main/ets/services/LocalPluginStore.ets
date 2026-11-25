/*
 * 本地插件（PawApp）存储 —— 无 QwenPaw 服务端时在本机运行前端 JS 插件。
 *
 * 目录布局（应用沙箱 filesDir，全部沙箱路径、可被 Web 组件 file:// 直读）：
 *   pluginhost/index.html / host.js / vendor/*.js   本地宿主 shell（首次运行从 rawfile/pluginhost
 *                                             拷入，版本号变化时重同步，见 ensureHostShell）
 *   pluginhost/plugins/<id>/...          插件文件（由用户设备 ZIP 解包而来）
 *   pluginhost/plugins.json              本地注册表
 *   pluginhost/trash/<时间戳>-<id>        卸载备份（不 rm 直接删，保留最近 5 份，更早移入 trash/old/）
 *
 * 安装流程（与服务器 src/qwenpaw/app/routers/plugins.py 的 find_plugin_root 同口径）：
 *   解包到临时目录 → 定位含 plugin.json 的插件目录（根或一级子目录）→ 校验 id 与前端入口
 *   （entry.frontend 存在）→ 整目录移入 plugins/<id>/ → 写注册表。
 * 卸载：插件目录移入 trash + 删注册表条目。
 *
 * 错误用模块常量编码抛出（见 ERR_*），由 UI 层映射到 i18n 文案——存储层不依赖资源管理器。
 */
import { zlib } from '@kit.BasicServicesKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { common } from '@kit.AbilityKit';
import resourceManager from '@ohos.resourceManager';
import { PickedFile, removeTemp } from './AttachmentPicker';

// 本地插件信息（注册表条目，plugins.json 的数组元素）
export interface LocalPluginInfo {
  id: string;
  name: string;
  version: string;
  // entry.frontend（如 ui/index.js），相对插件根目录
  entry: string;
}

// 安装/校验错误码（UI 层按码取 i18n 文案）
export const ERR_ZIP: string = 'zip';
export const ERR_ROOT: string = 'root';
export const ERR_ID: string = 'id';
export const ERR_ENTRY: string = 'entry';
export const ERR_ENTRY_MISSING: string = 'entry_missing';
export const ERR_EXISTS: string = 'exists';

// 宿主 shell 版本：rawfile/pluginhost 内容变更时 +1，触发沙箱侧重同步
// 7：host.js PawApp（meta.pawapp）单页模式——多路由插件不出左侧菜单壳
// 8：host.js 两轴契约（host.env kind/caps/apiVersion）+ antdIcons UMD + 通知载荷 kind/target
const HOST_SHELL_VERSION: string = '8';
// 回收区保留份数
const TRASH_KEEP: number = 5;
// 插件 id 合法字符（与服务端一致：小写字母/数字开头，含 - _）
const ID_PATTERN: RegExp = /^[a-z0-9][a-z0-9_-]*$/;

function hostDirOf(ctx: common.Context): string {
  return `${ctx.filesDir}/pluginhost`;
}

function pluginsDirOf(ctx: common.Context): string {
  return `${hostDirOf(ctx)}/plugins`;
}

function registryPathOf(ctx: common.Context): string {
  return `${hostDirOf(ctx)}/plugins.json`;
}

function trashDirOf(ctx: common.Context): string {
  return `${hostDirOf(ctx)}/trash`;
}

function mkdirs(path: string): void {
  if (fs.accessSync(path)) {
    return;
  }
  const parts: string[] = path.split('/');
  let cur: string = '';
  for (const p of parts) {
    if (p.length === 0) {
      continue;
    }
    cur = cur.length === 0 ? `/${p}` : `${cur}/${p}`;
    if (!fs.accessSync(cur)) {
      try {
        fs.mkdirSync(cur);
      } catch (e) {
        // 并发已建 → 忽略
      }
    }
  }
}

function readText(path: string): string {
  const f: fs.File = fs.openSync(path, fs.OpenMode.READ_ONLY);
  try {
    const size: number = fs.statSync(f.fd).size;
    const buf: ArrayBuffer = new ArrayBuffer(size);
    const len: number = fs.readSync(f.fd, buf);
    return new util.TextDecoder('utf-8').decodeToString(new Uint8Array(buf, 0, len));
  } finally {
    fs.closeSync(f);
  }
}

function writeText(path: string, text: string): void {
  const f: fs.File = fs.openSync(path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(f.fd, text);
  } finally {
    fs.closeSync(f);
  }
}

// 递归删除目录树（只用于清理本应用自建的临时目录）
function removeDirTree(dir: string): void {
  let entries: string[] = [];
  try {
    entries = fs.listFileSync(dir);
  } catch (e) {
    return;
  }
  for (const name of entries) {
    const p: string = `${dir}/${name}`;
    let isDir: boolean = false;
    try {
      isDir = fs.statSync(p).isDirectory();
    } catch (e) {
      continue;
    }
    try {
      if (isDir) {
        removeDirTree(p);
      } else {
        fs.unlinkSync(p);
      }
    } catch (e) {
      // 单条目失败不阻断清理
    }
  }
  try {
    fs.rmdirSync(dir);
  } catch (e) {
    // 目录残留不阻断主流程
  }
}

// 目录树递归拷贝（内容与 copyRawDir 同模式：逐条 list + 分支 file/dir）。
// 文件拷贝失败直接抛出——静默跳过会产生缺文件的"已安装"插件，比失败更糟。
function copyTree(srcDir: string, destDir: string): void {
  if (!fs.accessSync(destDir)) {
    fs.mkdirSync(destDir);
  }
  let entries: string[] = [];
  try {
    entries = fs.listFileSync(srcDir);
  } catch (e) {
    return;
  }
  for (const name of entries) {
    const s: string = `${srcDir}/${name}`;
    const d: string = `${destDir}/${name}`;
    let isDir: boolean = false;
    try {
      isDir = fs.statSync(s).isDirectory();
    } catch (e) {
      continue; // 跳过不可读条目
    }
    if (isDir) {
      copyTree(s, d);
    } else {
      fs.copyFileSync(s, d);
    }
  }
}

// 目录级移动 = 递归拷贝 + 清源目录。
// 不用系统目录接口的两个原因（实测）：moveFileSync 只支持文件，对目录抛
// 13900020（Invalid argument）；copyDirSync 按源目录名落到 dest/<源目录名> 下，
// 与「目标固定命名（插件 id / 回收区时间戳名）」不符。
function moveDirectory(src: string, dest: string): void {
  copyTree(src, dest);
  removeDirTree(src);
}

function strField(obj: Object, key: string): string {
  const v: Object = (obj as Record<string, Object>)[key];
  return typeof v === 'string' ? v as string : '';
}

export class LocalPluginStore {
  // 宿主 shell 落盘：rawfile/pluginhost → filesDir/pluginhost（版本比对，命中即跳过）
  static ensureHostShell(ctx: common.UIAbilityContext): void {
    const dir: string = hostDirOf(ctx);
    const verPath: string = `${dir}/VERSION`;
    let current: string = '';
    try {
      current = readText(verPath);
    } catch (e) {
      current = '';
    }
    if (current === HOST_SHELL_VERSION) {
      return;
    }
    mkdirs(dir);
    LocalPluginStore.copyRawDir(ctx.resourceManager, 'pluginhost', dir);
    writeText(verPath, HOST_SHELL_VERSION);
  }

  // rawfile 目录递归拷贝（rawfile 无列表目录之外的删除语义：新文件覆盖写、目录递归）
  private static copyRawDir(rm: resourceManager.ResourceManager, srcDir: string, destDir: string): void {
    mkdirs(destDir);
    const entries: string[] = rm.getRawFileListSync(srcDir);
    for (const e of entries) {
      const srcRel: string = srcDir.length > 0 ? `${srcDir}/${e}` : e;
      const destPath: string = `${destDir}/${e}`;
      if (LocalPluginStore.isRawDir(rm, srcRel)) {
        LocalPluginStore.copyRawDir(rm, srcRel, destPath);
      } else {
        const bytes: Uint8Array = rm.getRawFileContentSync(srcRel);
        const f: fs.File = fs.openSync(destPath, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
        try {
          fs.writeSync(f.fd, bytes.buffer);
        } finally {
          fs.closeSync(f);
        }
      }
    }
  }

  private static isRawDir(rm: resourceManager.ResourceManager, rel: string): boolean {
    try {
      rm.getRawFileListSync(rel);
      return true;
    } catch (e) {
      return false;
    }
  }

  // 从设备 ZIP 安装（离线，不经过任何服务端）
  static async installFromZip(ctx: common.UIAbilityContext, zip: PickedFile): Promise<LocalPluginInfo> {
    const pluginsDir: string = pluginsDirOf(ctx);
    const tmp: string = `${ctx.cacheDir}/localplug_${Date.now()}`;
    mkdirs(tmp);
    try {
      const options: zlib.Options = {
        level: zlib.CompressLevel.COMPRESS_LEVEL_DEFAULT_COMPRESSION,
        memLevel: zlib.MemLevel.MEM_LEVEL_DEFAULT,
        strategy: zlib.CompressStrategy.COMPRESS_STRATEGY_DEFAULT_STRATEGY
      };
      try {
        await zlib.decompressFile(zip.path, tmp, options);
      } catch (e) {
        throw new Error(ERR_ZIP);
      }
      const root: string = LocalPluginStore.findPluginRoot(tmp);
      if (root.length === 0) {
        throw new Error(ERR_ROOT);
      }
      let manifest: Object;
      try {
        manifest = JSON.parse(readText(`${root}/plugin.json`));
      } catch (e) {
        throw new Error(ERR_ROOT);
      }
      const id: string = strField(manifest, 'id');
      if (!ID_PATTERN.test(id)) {
        throw new Error(ERR_ID);
      }
      const nameRaw: string = strField(manifest, 'name');
      const version: string = strField(manifest, 'version');
      const entryObj: Object = (manifest as Record<string, Object>)['entry'];
      const entry: string = entryObj !== undefined && entryObj !== null && typeof entryObj === 'object'
        ? strField(entryObj as Record<string, Object>, 'frontend')
        : '';
      if (entry.length === 0 || entry.startsWith('/') || entry.includes('..')) {
        throw new Error(ERR_ENTRY);
      }
      if (!fs.accessSync(`${root}/${entry}`)) {
        throw new Error(ERR_ENTRY_MISSING);
      }
      const target: string = `${pluginsDir}/${id}`;
      if (fs.accessSync(target)) {
        if (LocalPluginStore.get(ctx, id) !== null) {
          throw new Error(ERR_EXISTS);
        }
        // 有目录但无注册表条目 = 历史安装残留，清掉再装
        LocalPluginStore.moveToTrash(ctx, target, `stale_${id}_${Date.now()}`);
      }
      mkdirs(pluginsDir);
      moveDirectory(root, target);
      const info: LocalPluginInfo = {
        id: id,
        name: nameRaw.length > 0 ? nameRaw : id,
        version: version,
        entry: entry
      };
      LocalPluginStore.upsert(ctx, info);
      // 剩余临时目录（同级多顶层目录等）整体移入回收区，不留 cache 垃圾
      LocalPluginStore.moveToTrash(ctx, tmp, `install_${Date.now()}`);
      removeTemp(zip.path);
      return info;
    } catch (e) {
      // 失败也回收临时目录（不 rm，移回收区）
      LocalPluginStore.moveToTrash(ctx, tmp, `failed_${Date.now()}`);
      removeTemp(zip.path);
      throw e as Error;
    }
  }

  // 定位插件根：tmp/plugin.json 存在 → tmp；否则找一级子目录（与服务端 find_plugin_root 同口径）
  private static findPluginRoot(tmp: string): string {
    if (fs.accessSync(`${tmp}/plugin.json`)) {
      return tmp;
    }
    let names: string[] = [];
    try {
      names = fs.listFileSync(tmp);
    } catch (e) {
      return '';
    }
    for (const n of names) {
      const sub: string = `${tmp}/${n}`;
      try {
        if (fs.statSync(sub).isDirectory() && fs.accessSync(`${sub}/plugin.json`)) {
          return sub;
        }
      } catch (e) {
        // 跳过不可读条目
      }
    }
    return '';
  }

  // 注册表读取（文件缺失/损坏 → 空表）
  static list(ctx: common.Context): LocalPluginInfo[] {
    const out: LocalPluginInfo[] = [];
    let text: string = '';
    try {
      text = readText(registryPathOf(ctx));
    } catch (e) {
      return out;
    }
    let arr: Object;
    try {
      arr = JSON.parse(text);
    } catch (e) {
      return out;
    }
    if (!Array.isArray(arr)) {
      return out;
    }
    for (const item of arr as Object[]) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const id: string = strField(r, 'id');
      const entry: string = strField(r, 'entry');
      if (id.length === 0 || entry.length === 0) {
        continue;
      }
      const info: LocalPluginInfo = {
        id: id,
        name: strField(r, 'name'),
        version: strField(r, 'version'),
        entry: entry
      };
      if (info.name.length === 0) {
        info.name = id;
      }
      out.push(info);
    }
    out.sort((a: LocalPluginInfo, b: LocalPluginInfo): number => a.name.localeCompare(b.name));
    return out;
  }

  // 按 id 取注册表条目（未安装 → null）
  static get(ctx: common.Context, id: string): LocalPluginInfo | null {
    const all: LocalPluginInfo[] = LocalPluginStore.list(ctx);
    for (const info of all) {
      if (info.id === id) {
        return info;
      }
    }
    return null;
  }

  // 插件文件是否完好（目录 + 入口文件都在）
  static pluginReady(ctx: common.Context, info: LocalPluginInfo): boolean {
    return fs.accessSync(`${pluginsDirOf(ctx)}/${info.id}/${info.entry}`);
  }

  // 读插件 plugin.json 的 meta.pawapp（单页 PawApp 标记）：不可读 / 非 PawApp → null。
  // 每次开页现读（manifest 小，不缓存、注册表不加字段）——重装插件后标记即时生效。
  static readPawappMeta(ctx: common.Context, id: string): Record<string, Object> | null {
    let manifest: Object;
    try {
      manifest = JSON.parse(readText(`${pluginsDirOf(ctx)}/${id}/plugin.json`));
    } catch (e) {
      return null;
    }
    const meta: Object = (manifest as Record<string, Object>)['meta'];
    if (meta === undefined || meta === null || typeof meta !== 'object') {
      return null;
    }
    const pawapp: Object = (meta as Record<string, Object>)['pawapp'];
    if (pawapp === undefined || pawapp === null || typeof pawapp !== 'object') {
      return null;
    }
    return pawapp as Record<string, Object>;
  }

  // 卸载：注册表删条目 + 插件目录移入回收区
  static remove(ctx: common.UIAbilityContext, id: string): void {
    const src: string = `${pluginsDirOf(ctx)}/${id}`;
    if (fs.accessSync(src)) {
      LocalPluginStore.moveToTrash(ctx, src, `${Date.now()}-${id}`);
    }
    const kept: LocalPluginInfo[] = LocalPluginStore.list(ctx).filter(
      (info: LocalPluginInfo): boolean => info.id !== id);
    LocalPluginStore.saveRegistry(ctx, kept);
  }

  private static upsert(ctx: common.Context, info: LocalPluginInfo): void {
    const kept: LocalPluginInfo[] = LocalPluginStore.list(ctx).filter(
      (x: LocalPluginInfo): boolean => x.id !== info.id);
    kept.push(info);
    LocalPluginStore.saveRegistry(ctx, kept);
  }

  private static saveRegistry(ctx: common.Context, items: LocalPluginInfo[]): void {
    mkdirs(hostDirOf(ctx));
    writeText(registryPathOf(ctx), JSON.stringify(items));
  }

  // 目录移入回收区（保留最近 TRASH_KEEP 份，更早的移入 trash/old/，不直接删）
  private static moveToTrash(ctx: common.Context, src: string, name: string): void {
    if (!fs.accessSync(src)) {
      return;
    }
    const trashDir: string = trashDirOf(ctx);
    mkdirs(trashDir);
    try {
      moveDirectory(src, `${trashDir}/${name}`);
    } catch (e) {
      return; // 移不动就留原地，不影响主流程
    }
    LocalPluginStore.pruneTrash(trashDir);
  }

  private static pruneTrash(trashDir: string): void {
    let names: string[] = [];
    try {
      names = fs.listFileSync(trashDir).filter((n: string): boolean => n !== 'old');
    } catch (e) {
      return;
    }
    if (names.length <= TRASH_KEEP) {
      return;
    }
    names.sort();
    const overflow: string = `${trashDir}/old`;
    mkdirs(overflow);
    for (let i = 0; i < names.length - TRASH_KEEP; i++) {
      try {
        moveDirectory(`${trashDir}/${names[i]}`, `${overflow}/${names[i]}`);
      } catch (e) {
        // 忽略单份失败
      }
    }
  }
}
