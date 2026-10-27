/*
 * 聊天行组件 —— 会话详情页把「一个回合 = 一个 ListItem」拆成「一行 = 一个 ListItem」后的行渲染层。
 *
 * 行类型（ConversationRow.kind）：
 *   user        —— 用户气泡（右对齐实底）
 *   message     —— 一段响应文本气泡（markdown / 选择态纯文本）
 *   stepsGroup  —— 一个过程组（组头卡 + 组内行集合，单一列表项，见 ProcessGroup）
 *   media       —— 该回合的工具产出媒体（图片 / 文件卡）
 *   pending     —— 待发回合的「正在生成…」占位
 *
 * 拆分动机：整回合一个 ListItem 时，流式期间每个 flush 都会让 List 重排这个巨大 item，
 * 过程卡（数百行）参与重排直接卡死；拆成行后 List 的虚拟化对每行生效，只有"正在长的那一行"重排。
 * 行组件全部自持交互态（展开 / 选择 / 复制），使某行重排/重建不牵连其它行。
 */

import { image } from '@kit.ImageKit';
import { util } from '@kit.ArkTS';
import { common } from '@kit.AbilityKit';
import { pasteboard } from '@kit.BasicServicesKit';
import { UIContext, SymbolGlyphModifier, curves, LengthMetrics } from '@kit.ArkUI';
import {
  DisplayMessage, DisplayPart, textOfParts
} from '../services/ChatDetailService';
import { ThemeSnapshot, ThemeManager } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { downloadToCache, saveToGallery, shareFile, safeNameOf, openCachedFilePreview,
  canSystemPreview, isMarkdownName, isTextualName, readTextFile, TextRead,
  saveCachedFileWithPicker, openCachedFileWithOtherApp, saveBytesToCache,
  defaultNameOf } from '../services/MediaActions';
import { healStreamingMarkdown, stripScrollHeadlines } from '../services/StreamMarkdown';
import { fileIconOf } from '../theme/FileIcons';

import { SheetGate, moduleSheetOptions } from './SheetGate';
import { Markdown } from '../vendor/markdown/Index';
import { MarkdownOptions, MarkdownTheme, MarkdownFontStyle } from '../vendor/markdown/Index';
import { CodeStyle, CodeSpan, BlockQuoteStyle, DriveStyle } from '../vendor/markdown/src/main/ets/config/MarkdownTheme';
import { contextMenuOptions } from '../theme/MenuMaterial';
import { t } from '../services/I18n';

// ============ 扁平行模型 ============
// 会话被展平成行序列：List 的每个 ListItem 承载一行，键只含结构信息（回合 + 块序号），
// 行内容的变化走可观察对象原地更新（见下方 ConversationRow 注释）。
/*
 * 列表行模型：@Observed 类 + 行组件用 @ObjectLink 接收 —— 这是"流式期间只有那一行内容在变"
 * 的正确更新路径。ArkUI 的 ForEach 只在键变化时重跑 itemGenerator：把内容指纹放进键可以让在途行
 * 刷新，但代价是**每帧销毁重建该行**（整卡闪、滚动被打断，真机表现为"刷屏"）；改用可观察对象后，
 * 键保持结构键不变，页面只把新数据**赋值到同一个行对象**上，行组件原地更新（不重建子树）。
 * 同一键的行（无论所属回合在途还是已完结）都由页面复用同一实例，且只在字段真实变化时赋值
 * （rowFor 的判重守卫）——流式期间每 60ms 的 flush 只刷新真正在变的活动行，不牵连整张列表。
 */
@Observed
export class ConversationRow {
  key: string = '';            // ForEach 键（唯一且稳定，只含结构信息）
  kind: string = '';           // user | message | stepsGroup | media | pending
  turnId: string = '';         // 所属回合 id
  // message 行的消息；user 行 [用户消息]；stepsGroup 行 = 组内原始消息（组头摘要按它统计）
  messages: DisplayMessage[] = [];
  // stepsGroup 行：合并连续同工具后的组内行（body 的 ForEach 数据源；非 steps 行恒空）
  bodyMessages: DisplayMessage[] = [];
  parts: DisplayPart[] = [];   // media 行的媒体分片
  pending: boolean = false;    // 所属回合是否在途
  expanded: boolean = false;   // 过程组当前是否展开（展开态由页面持有；作为目标态传入组组件）
  groupKey: string = '';       // 过程组的稳定键（turnId:块序号），用于页面切换展开态
  last: boolean = false;       // message 行是否为该回合最终回复
  generating: boolean = false; // steps 组是否为该回合正在生成的「活动组」
  // stepsGroup 行：本次挂载是否播展开动画（用户手动展开 / 组首次出现才有；虚拟化重入不重播）
  animateOpen: boolean = false;
}

export function rowOf(kind: string, key: string, turnId: string, messages: DisplayMessage[],
  parts: DisplayPart[]): ConversationRow {
  const r: ConversationRow = new ConversationRow();
  r.kind = kind;
  r.key = key;
  r.turnId = turnId;
  r.messages = messages;
  r.parts = parts;
  return r;
}

// 展开态「不限行数」用的行数上限：不能用 maxLines(0) —— 真机实测该值被当作 0 行处理，
// 展开后文本反而整段不显示（Text 节点消失）。用一个足够大的整数表达「不限制」。
const NO_LINE_LIMIT: number = 100000;

// 行级 body 视口与行首之间的竖向间距：随开合同一弹簧插值（开=本值 / 收=0）。收合末帧与
// 内容高度同时归零 ⇒ 子树摘除时布局零变化；若写成固定 margin，摘除子树会带走这段间距，
// 造成一次离散的高度跳变（stackFromEnd 随之重锚 → 视线"闪一下"）。
const PROC_BODY_GAP: number = 6;

// 喂给 Markdown 的内容节流窗口（ms）。对应 QwenCode web-shell Markdown.tsx 的 useThrottledValue
// （React useDeferredValue 的替代实现；它取 80ms，本工程一次 flush 已是 60ms 的批量，取稍宽的窗口
// 让"整段重新解析"的节奏更稳）：本工程 Markdown 组件每次 content 变化都会重起一次解析任务，
// 流式期间逐分片重解析会让整块反复重排。仅对喂入内容做节流，窗口内的最后一批变化由定时器兜住，
// 流一停立即落盘（不会停在旧内容上）；行内文本与非 markdown 部分不受影响。
const MD_THROTTLE_MS: number = 180;
// 页内只读预览的文本读取上限：超过就只读前 256KB 并附截断提示（避免超大文件卡住渲染）
const TEXT_PREVIEW_CAP: number = 256 * 1024;

// ============ 媒体渲染（对齐 PR #7378 features/chat/MessageParts.tsx）============
// 媒体 URL 解析对齐 7378 client.ts mediaSource：http/https/data 原样，
// 其余（相对路径 / file://）拼 {baseUrl}/api/files/preview{path}。
// 注：ArkTS Image 组件不支持自定义请求头（7378 的 mediaSource 会带 Authorization / X-Agent-Id），
// 开放模式免票据可直接访问；需票据的部署下带认证媒体暂不显示（后续以 ArrayBuffer 下载 → PixelMap 补齐）。
function mediaUrl(baseUrl: string, rawUrl: string): string {
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://') || rawUrl.startsWith('data:')) {
    return rawUrl;
  }
  const path: string = rawUrl.startsWith('file://') ? rawUrl.slice(7) : rawUrl;
  // 绝对路径（工具写工作区外的文件、截图等）→ 文件预览通道；
  // 相对路径（工具在工作区内写文件时给的就是相对路径）→ 工作区文件下载通道
  if (path.startsWith('/')) {
    return `${baseUrl}/api/files/preview${path}`;
  }
  return `${baseUrl}/api/workspace/file-download?root=workspace&path=${encodeURIComponent(path)}`;
}

function mediaPartsOf(parts: DisplayPart[]): DisplayPart[] {
  return parts.filter((p: DisplayPart): boolean => p.type !== 'text');
}

// 同一相对路径的另一个工作区根：产物可能落在「绑定项目目录」（console 的 project 根）或
// 「智能体自身存储根」（workspace 根）两处 —— console 对相对路径固定取 project 根，本工程
// 历史上按 workspace 根取，两者各自覆盖一部分产物。故下载失败时换另一个根再取一次。
// 绝对路径 / 内联数据没有第二个根（走 /api/files/preview 通道），返回空串表示无可回退。
function altRootUrl(baseUrl: string, rawUrl: string): string {
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://') || rawUrl.startsWith('data:')) {
    return '';
  }
  const path: string = rawUrl.startsWith('file://') ? rawUrl.slice(7) : rawUrl;
  if (path.startsWith('/')) {
    return '';
  }
  return `${baseUrl}/api/workspace/file-download?root=project&path=${encodeURIComponent(path)}`;
}

// 该消息是否有可见内容（非空白文本 / 媒体分片 / 错误）。服务端会下发 text 只有 "\n\n" 的 message
// 记录（实测同一会话 26 条），它渲染成空内容 + 卡片底色 = 一张空白卡，故按可见性判定后不出行。
// 里程碑标题行（⟦ … ⟧ / 〚 … 〛，见 stripScrollHeadlines 注释）渲染前会被剥离，
// 只有标题行的 message 同样判"无内容"——否则它渲染成一张只有卡片底色的空白卡。
export function rowHasVisibleContent(m: DisplayMessage): boolean {
  if (m.error !== undefined && m.error.length > 0) {
    return true;
  }
  for (const p of m.parts) {
    if (p.type !== 'text') {
      return true;
    }
    const t: string = p.text !== undefined ? p.text : '';
    if (t.indexOf('⟦') >= 0 || t.indexOf('〚') >= 0) {
      // 含标题行标记才走剥离正则（快判避免常规无标记文本每帧跑正则）
      if (stripScrollHeadlines(t).length > 0) {
        return true;
      }
    } else if (t.trim().length > 0) {
      return true;
    }
  }
  return false;
}

// 复制纯文本到系统剪贴板；成功返回 true（调用方据此置「复制完成」反馈）
export async function copyTextToClipboard(ctx: UIContext, text: string): Promise<boolean> {
  if (text.length === 0) {
    return false;
  }
  try {
    const data: pasteboard.PasteData = pasteboard.createData(pasteboard.MIMETYPE_TEXT_PLAIN, text);
    await pasteboard.getSystemPasteboard().setData(data);
    return true;
  } catch (e) {
    return false;
  }
}

// 单个媒体块：图片 → Image（data URL 先转 PixelMap）；video/audio/file → 文件卡
@Component
struct MediaThumb {
  @Prop part: DisplayPart = { type: '' };
  @Prop baseUrl: string = '';
  @Prop anchorId: string = '';                 // 分享面板贴靠锚点 id（长按菜单里分享时用）
  // 卡片宽度：多图网格 48.5%，单图/文件整行 100%（不再固定 180vp，避免超出气泡容器）
  @Prop itemW: string = '100%';
  @State pixelMap: image.PixelMap | undefined = undefined;
  @State failed: boolean = false;
  @State busy: boolean = false;
  // 内联 base64 图（data: URL）的原始字节：除解码成 PixelMap 展示外另留一份，
  // 点开时落成缓存文件交给系统预览（这类图没有可下载的远端地址）
  private inlineBytes: Uint8Array | undefined = undefined;
  // 页内只读预览（Preview Kit 打不开的文本/代码类文件）：内容 + 是否 markdown + 标题（文件名）
  @State textShown: boolean = false;
  @State textBody: string = '';
  @State textMd: boolean = false;
  @State textName: string = '';
  @StorageLink('appIsDark') dark: boolean = false;
  private sheetGate: SheetGate = new SheetGate();

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  // 打开失败提示：区分「服务端已经没有这个文件」与「格式不支持」。
  // 产物源文件消失是常态（工具写到容器 /tmp 的临时图，服务端清理后只剩历史里的路径），
  // 这时给「源文件已不在服务端」，不要一律报"无法预览"让人以为格式不支持。
  private failToast(e: Object): void {
    const msg: string = (e as Error).message !== undefined ? (e as Error).message : '';
    if (msg.indexOf('404') >= 0) {
      this.toast(t($r('app.string.chat_file_gone')));
      return;
    }
    this.toast(t($r('app.string.chat_file_no_preview')));
  }

  // 资源文案取字符串（工程统一口径：resourceManager.getStringSync）

  private hostCtx(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  private urlOf(): string {
    return mediaUrl(this.baseUrl, this.part.url !== undefined ? this.part.url : '');
  }

  // 落到缓存（带回退），返回缓存路径 —— 点开预览 / 保存到 / 分享 / 其他应用打开都先过这里：
  //   · 内联 base64（data:）没有可下载的远端地址 → 用内存里那份字节直接落盘；
  //   · 远端地址失败且是相对路径 → 换另一个工作区根再取一次（见 altRootUrl）。
  private async fetchToCache(type: string): Promise<string> {
    const ctx: common.UIAbilityContext = this.hostCtx();
    const raw: string = this.part.url !== undefined ? this.part.url : '';
    if (raw.startsWith('data:')) {
      const bytes: Uint8Array | undefined = this.inlineBytes;
      if (bytes === undefined) {
        throw new Error('inline data not decoded yet');
      }
      return saveBytesToCache(ctx, bytes, this.fileNameOf());
    }
    try {
      return await downloadToCache(ctx, this.urlOf(), type, this.fileNameOf());
    } catch (e) {
      const alt: string = altRootUrl(this.baseUrl, raw);
      if (alt.length === 0) {
        throw e as Error;
      }
      return await downloadToCache(ctx, alt, type, this.fileNameOf());
    }
  }

  private fileNameOf(): string {
    const rawUrl: string = this.part.url !== undefined ? this.part.url : '';
    const given: string = this.part.name !== undefined && this.part.name.length > 0 ? this.part.name : '';
    if (given.length > 0) {
      return safeNameOf(given, this.part.type);
    }
    // 内联数据没有文件名（末段是 base64 正文，切出来是垃圾）→ 按类型给默认名
    if (rawUrl.startsWith('data:')) {
      return defaultNameOf(this.part.type);
    }
    const segs: string[] = this.urlOf().split('/');
    const last: string = segs.length > 0 ? segs[segs.length - 1] : '';
    return safeNameOf(last, this.part.type);
  }

  // 文件卡副标题：工具产出文件显示变化类型（新建 / 修改 / 发送，对齐 console 的 artifactChange），
  // 其余分片就显示类型名
  private subtitle(): string {
    const note: string = this.part.note !== undefined ? this.part.note : '';
    if (note === 'created') {
      return t($r('app.string.chat_file_created'));
    }
    if (note === 'modified') {
      return t($r('app.string.chat_file_modified'));
    }
    if (note === 'sent') {
      return t($r('app.string.chat_file_sent'));
    }
    return this.part.type;
  }

  // 保存到相册：安全控件回调内已有临时授权 → 下载到缓存再写入媒体库（对齐 7378 cacheMedia + saveToLibrary）
  handleSave: SaveButtonCallback = async (event: ClickEvent, result: SaveButtonOnClickResult): Promise<void> => {
    if (result !== SaveButtonOnClickResult.SUCCESS || this.busy) {
      return;
    }
    this.busy = true;
    try {
      const ctx: common.UIAbilityContext = this.hostCtx();
      const path: string = await downloadToCache(ctx, this.urlOf(), this.part.type, this.fileNameOf());
      await saveToGallery(ctx, this.part.type, path);
      this.toast(t($r('app.string.chat_media_saved')));
    } catch (e) {
      this.toast(`${t($r('app.string.chat_media_save_failed'))}: ${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  };

  // 分享：下载到缓存后走系统分享面板（ShareKit）
  private async shareMedia(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const ctx: common.UIAbilityContext = this.hostCtx();
      const path: string = await downloadToCache(ctx, this.urlOf(), this.part.type, this.fileNameOf());
      shareFile(ctx, path, this.part.type, this.anchorId);
    } catch (e) {
      this.toast(`${t($r('app.string.chat_media_share_failed'))}: ${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  // 点文件卡 → 打开：Preview Kit 支持表内的格式（Office / pdf / 图片 / 音视频 / 文本类）交给系统预览；
  // 表外的文本/代码类（md / py / sh / json / log …）系统预览打不开，落页内只读预览（md 走渲染）。
  private openFile(): void {
    const name: string = this.fileNameOf();
    if (!canSystemPreview(name) && isTextualName(name)) {
      this.openTextPreview(name);
      return;
    }
    this.previewFile();
  }

  // 页内只读预览：下载到缓存 → 按文本读取（超过 TEXT_PREVIEW_CAP 截断并附提示）→ 半模态面板
  private async openTextPreview(name: string): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const path: string = await this.fetchToCache(this.part.type);
      const read: TextRead = readTextFile(path, TEXT_PREVIEW_CAP);
      if (read.text.length === 0) {
        throw new Error('empty');
      }
      if (!this.sheetGate.request()) {
        return;
      }
      this.textName = name;
      this.textMd = isMarkdownName(name);
      this.textBody = read.truncated
        ? `${read.text}\n\n[${t($r('app.string.module_files_truncated'))}]`
        : read.text;
      this.textShown = true;
    } catch (e) {
      this.failToast(e as Object);
    } finally {
      this.busy = false;
    }
  }

  // 页内只读预览面板：标题 = 文件名，正文 = markdown 渲染 / 纯文本（跟随半模态材质与关叉避让口径）
  @Builder
  textPreviewSheet() {
    Column() {
      Text(this.textName)
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .width('100%')
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ bottom: 12 })
      if (this.textMd) {
        Scroll() {
          Column() {
            Markdown({ content: this.textBody, options: { darkMode: this.dark } })
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.sheet_card_bg'))
        }
        .width('100%')
        .layoutWeight(1)
        .align(Alignment.Top)
        .scrollBar(BarState.Auto)
      } else {
        Scroll() {
          Text(this.textBody)
            .fontSize(UiTokens.fsSecondary)
            .lineHeight(20)
            .width('100%')
            .padding(UiTokens.cardPad)
            .borderRadius(UiTokens.cardRadius)
            .backgroundColor($r('app.color.sheet_card_bg'))
            .textAlign(TextAlign.Start)
            .wordBreak(WordBreak.BREAK_ALL)
            .copyOption(CopyOptions.LocalDevice)
        }
        .width('100%')
        .layoutWeight(1)
        .align(Alignment.Top)
        .scrollBar(BarState.Auto)
      }
    }
    .width('100%')
    .height('100%')
    .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin, bottom: UiTokens.pageHMargin })
  }

  // 保存到…：下载到缓存后交给系统 picker 选位置（可选目录）——与「文件」模块同一出口
  private async saveViaPicker(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const ctx: common.UIAbilityContext = this.hostCtx();
      const path: string = await this.fetchToCache(this.part.type);
      const saved: boolean = await saveCachedFileWithPicker(ctx, path, this.fileNameOf());
      if (saved) {
        this.toast(t($r('app.string.module_files_downloaded')));
      }
    } catch (e) {
      this.toast(`${t($r('app.string.chat_media_save_failed'))}: ${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  // 其他应用打开：下载到缓存后走官方隐式 Want（见 services/MediaActions.openCachedFileWithOtherApp）
  private async openExternally(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const ctx: common.UIAbilityContext = this.hostCtx();
      const path: string = await this.fetchToCache(this.part.type);
      await openCachedFileWithOtherApp(ctx, path, this.fileNameOf());
    } catch (e) {
      this.toast(t($r('app.string.module_files_open_external_failed')));
    } finally {
      this.busy = false;
    }
  }

  // 点开 → 系统预览服务（Preview Kit，文本/Office/图片/音视频都能开）。内联 base64 图与远端图
  // 走同一出口（差别只在 fetchToCache 怎么拿到文件）。
  // 预览不可用（格式不支持 / 设备无预览服务 / 源文件已被服务端清理）时给对应提示。
  private async previewFile(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const ctx: common.UIAbilityContext = this.hostCtx();
      const path: string = await this.fetchToCache(this.part.type);
      await openCachedFilePreview(ctx, path, this.fileNameOf());
    } catch (e) {
      this.failToast(e as Object);
    } finally {
      this.busy = false;
    }
  }

  // 长按菜单：保存 / 分享 / 其他应用打开 —— 与工作台「文件」模块同一套出口
  // （图片/视频的「保存」= 安全控件存相册，文件卡的「保存」= 系统 picker 选目录另存）
  @Builder
  mediaMenu() {
    Column() {
      if (this.part.type === 'image' || this.part.type === 'video') {
        SaveButton({ icon: SaveIconStyle.FULL_FILLED, text: SaveDescription.DOWNLOAD })
          .iconSize(20)
          .onClick(this.handleSave)
      } else {
        Row({ space: 8 }) {
          Image($r('app.media.folder_plus'))
            .width(18).height(18)
            .fillColor($r('app.color.text_secondary'))
          Text($r('app.string.module_files_save_as'))
            .fontSize(UiTokens.fsBody)
            .fontColor($r('app.color.text_primary_strong'))
        }
        .width('100%')
        .padding({ left: 12, right: 12, top: 10, bottom: 10 })
        .onClick((): void => {
          this.saveViaPicker();
        })
      }
      Divider().color($r('app.color.card_bg')).strokeWidth(1)
      Row({ space: 8 }) {
        Image($r('app.media.link'))
          .width(18).height(18)
          .fillColor($r('app.color.text_secondary'))
        Text($r('app.string.chat_media_share'))
          .fontSize(UiTokens.fsBody)
          .fontColor($r('app.color.text_primary_strong'))
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 10, bottom: 10 })
      .onClick((): void => {
        this.shareMedia();
      })
      Divider().color($r('app.color.card_bg')).strokeWidth(1)
      Row({ space: 8 }) {
        Image($r('app.media.book_open'))
          .width(18).height(18)
          .fillColor($r('app.color.text_secondary'))
        Text($r('app.string.module_files_open_external'))
          .fontSize(UiTokens.fsBody)
          .fontColor($r('app.color.text_primary_strong'))
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 10, bottom: 10 })
      .onClick((): void => {
        this.openExternally();
      })
    }
    .width('100%')
    .constraintSize({ maxWidth: '100%' })
    .padding(6)
  }

  aboutToAppear(): void {
    const url: string = this.part.url !== undefined ? this.part.url : '';
    if (this.part.type === 'image' && url.startsWith('data:')) {
      this.decodeDataUrl(url);
    }
  }

  // base64 data URL → PixelMap（ArkTS Image 不直读 data URL；对齐 7378 base64 source 分支）。
  // 原始字节另留一份：Image 只能"看"，点开要出文件（见 openInline）。
  private async decodeDataUrl(url: string): Promise<void> {
    const comma: number = url.indexOf(',');
    if (comma < 0) {
      return;
    }
    try {
      const bytes: Uint8Array = new util.Base64Helper().decodeSync(url.slice(comma + 1));
      this.inlineBytes = bytes;
      const buf: ArrayBuffer =
        bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
      const src: image.ImageSource = image.createImageSource(buf);
      this.pixelMap = await src.createPixelMap();
    } catch (e) {
      this.failed = true;
    }
  }

  @Builder
  FileCard() {
    Row() {
      Image(fileIconOf(this.fileNameOf()))
        .width(20)
        .height(20)
        .fillColor($r('app.color.text_secondary'))
        .margin({ right: 10 })
      Column() {
        Text(this.part.name !== undefined && this.part.name.length > 0 ? this.part.name : this.part.type)
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_primary_strong'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(this.subtitle())
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding({ left: 10, right: 10, top: 8, bottom: 8 })
    .borderRadius(12)
    .backgroundColor($r('app.color.card_bg'))
    .onClick((): void => {
      this.openFile();
    })
    // 页内只读预览面板（Preview Kit 表外的文本类才用得上），与长按菜单分挂不同节点：
    // 同一节点挂多个半模态只有最后一个生效（SheetGate 口径），故菜单留在外层容器
    .bindSheet(this.textShown, this.textPreviewSheet(),
      moduleSheetOptions(680, this.sheetGate, (v: boolean): void => {
        this.textShown = v;
      }))
  }

  build() {
    // 外包一层内置容器：既作为分享面板锚点（id），也承载长按菜单（自定义组件不能链式挂属性）
    Column() {
      if (this.part.type === 'image' && !this.failed) {
        if (this.pixelMap !== undefined) {
          Image(this.pixelMap)
            .width('100%')
            .aspectRatio(1.28)
            .objectFit(ImageFit.Cover)
            .borderRadius(UiTokens.cardRadius)
            .backgroundColor($r('app.color.card_bg'))
            // 内联 base64 图同样可点开：与远端图同一出口（点开 = 系统预览）
            .onClick((): void => {
              this.previewFile();
            })
        } else {
          Image(this.urlOf())
            .width('100%')
            .aspectRatio(1.28)
            .objectFit(ImageFit.Cover)
            .borderRadius(UiTokens.cardRadius)
            .backgroundColor($r('app.color.card_bg'))
            .onError((): void => {
              this.failed = true;
            })
            // 点图 → 系统预览（Preview Kit）：图片此前只能看不能开。
            // data: 内联图（pixelMap 分支）不挂点击——它没有可下载的远端地址
            .onClick((): void => {
              this.previewFile();
            })
        }
      } else {
        this.FileCard()
      }
    }
    .width(this.itemW)
    .id(this.anchorId)
    // 长按菜单属弹窗类接口 → 走统一材质出口（此前漏传 options，菜单没有沉浸光感）
    .bindContextMenu(this.mediaMenu(), ResponseType.LongPress, contextMenuOptions())
  }
}

// 媒体块列表（跳过 text；文本已由气泡另行渲染）
@Component
struct MediaParts {
  @Prop parts: DisplayPart[] = [];
  @Prop baseUrl: string = '';

  // 多图 → 两列网格（每项 48.5%）；单图 / 含文件 → 整行铺满。此前每项固定 180vp，
  // 窄容器（分栏右栏 / 手机短气泡）下会顶出气泡边界
  private multiImage(): boolean {
    const ms: DisplayPart[] = mediaPartsOf(this.parts);
    if (ms.length < 2) {
      return false;
    }
    for (const m of ms) {
      if (m.type !== 'image') {
        return false;
      }
    }
    return true;
  }

  build() {
    Flex({ wrap: FlexWrap.Wrap, space: { main: LengthMetrics.vp(6), cross: LengthMetrics.vp(6) } }) {
      ForEach(mediaPartsOf(this.parts), (p: DisplayPart, i: number) => {
        MediaThumb({ part: p, baseUrl: this.baseUrl, anchorId: `chat_media_${i}`,
          itemW: this.multiImage() ? '48.5%' : '100%' })
      }, (p: DisplayPart, i: number) => `${p.type}:${p.url !== undefined ? p.url : ''}:${i}`)
    }
    .width('100%')
  }
}

// ============ 选择态工具栏（提示 + 复制全文 + 完成）============
// 对齐 7378 features/chat/MessageBubbleActions 的 selectionToolbar。用户气泡（实底）与
// 消息气泡（浅底）只差前景色，故用 inverted 区分，避免两处重复。
// 落位是页面级统一浮层（ChatDetailPage.selBar，贴标题栏底边）：行内随卡顶上浮时，高气泡
// 卡顶贴屏顶会把工具栏推出屏外不可点；页面固定落位任何气泡高度下都可达，且出流不随行高变。
@Component
export struct SelectionToolbar {
  @Prop inverted: boolean = false;
  @Prop copied: boolean = false;
  @StorageLink('appIsDark') isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  onCopy: () => void = (): void => {};
  onDone: () => void = (): void => {};

  private fg(): ResourceColor {
    return this.inverted ? Color.White : (this.isDark ? this.theme.accentDark : this.theme.accent);
  }

  private hairline(): ResourceColor {
    return this.inverted ? '#3DFFFFFF' : $r('app.color.line');
  }

  build() {
    Row({ space: 6 }) {
      SymbolGlyph($r('sys.symbol.smart_selection_area'))
        .fontSize(17)
        .fontColor([this.fg()])
      Text($r('app.string.chat_select_hint'))
        .fontSize(UiTokens.fsCaption)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.fg())
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .layoutWeight(1)
      Button() {
        Image(this.copied ? $r('app.media.check') : $r('app.media.copy'))
          .width(18).height(18)
          .fillColor(this.fg())
      }
      .type(ButtonType.Normal)
      .backgroundColor(Color.Transparent)
      .stateEffect(false)
      .width(40)
      .height(40)
      .onClick((): void => {
        this.onCopy();
      })
      Button() {
        Image($r('app.media.x'))
          .width(19).height(19)
          .fillColor(this.inverted ? Color.White : $r('app.color.text_primary_strong'))
      }
      .type(ButtonType.Normal)
      .backgroundColor(Color.Transparent)
      .stateEffect(false)
      .width(40)
      .height(40)
      .onClick((): void => {
        this.onDone();
      })
    }
    // 胶囊形（整条圆角，不做方角横条）+ 左右外边距与消息卡同缘（pageHMargin，对齐气泡卡左边）：
    // 44vp 高配 radius 22 = 完整胶囊；内边距 12vp（图标不贴胶囊缘），40vp 按钮为最小触控区
    .width('100%')
    .height(44)
    .borderRadius(22)
    .padding({ left: 12, right: 12 })
    .margin({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin, bottom: 2 })
    .border({ width: this.inverted ? 0 : 0.5, color: this.hairline() })
  }
}

// ============ 用户气泡行 ============
@Component
export struct UserRow {
  @Prop message: DisplayMessage = { id: '', role: 'user', kind: 'message', parts: [] };
  @StorageLink('appIsDark') isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @Prop baseUrl: string = '';
  // 选择态由页面持有（单一事实源，见 ChatDetailPage.selectingId）：
  // 「点气泡外 / 返回手势」要能统一清退，多行之间天然互斥、不残留各行私有状态
  @Prop selecting: boolean = false;
  onRequestSelect: () => void = (): void => {};

  // 资源文案取字符串（工程统一口径：resourceManager.getStringSync）

  private text(): string {
    return textOfParts(this.message.parts);
  }

  private media(): DisplayPart[] {
    return mediaPartsOf(this.message.parts);
  }

  // 选择态禁掉长按菜单（改用右键触发），与 7378 一致
  private trigger(): ResponseType {
    return this.selecting || this.text().length === 0 ? ResponseType.RightClick : ResponseType.LongPress;
  }

  private async doCopy(): Promise<void> {
    const ok: boolean = await copyTextToClipboard(this.getUIContext(), this.text());
    const msg: string = ok ? t($r('app.string.chat_msg_copied')) : t($r('app.string.chat_msg_copy_failed'));
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  @Builder
  bubbleMenu() {
    Menu() {
      MenuItem({
        content: t($r('app.string.chat_msg_copy')),
        symbolStartIcon: new SymbolGlyphModifier($r('app.media.copy'))
      })
        .onClick((): void => {
          this.doCopy();
        })
      MenuItem({
        content: t($r('app.string.chat_msg_select')),
        symbolStartIcon: new SymbolGlyphModifier($r('sys.symbol.smart_selection_area'))
      })
        .onClick((): void => {
          if (this.text().length > 0) {
            this.onRequestSelect();
          }
        })
    }
  }

  build() {
    Row() {
      Blank()
      Column() {
        if (this.text().length > 0) {
          Text(this.text())
            .fontSize(UiTokens.fsBody)
            .fontColor(Color.White)
            .lineHeight(21)
            .wordBreak(WordBreak.BREAK_WORD)
            .copyOption(this.selecting ? CopyOptions.LocalDevice : CopyOptions.None)
        }
        if (this.media().length > 0) {
          Column() {
            MediaParts({ parts: this.media(), baseUrl: this.baseUrl })
          }
          .width('100%')
          .margin({ top: this.text().length > 0 ? 6 : 0 })
        }
      }
      .alignItems(HorizontalAlign.Start)
      // 带附件时必须给**确定宽度**：媒体块/网格用 100%、48.5% 百分比，父容器若为 auto 宽，
      // 百分比会按整行约束解析 → 卡片顶出气泡边界（真机「附件卡片超宽」的结构根因）
      .width(this.media().length > 0 ? '78%' : 'auto')
      .constraintSize({ maxWidth: '78%' })
      .padding({ left: 12, right: 12, top: 10, bottom: 10 })
      .borderRadius(UiTokens.cardRadius)
      .backgroundColor(this.isDark ? this.theme.accentDark : this.theme.accent)
      .bindContextMenu(this.bubbleMenu(), this.trigger(), contextMenuOptions())
      // 选择态点气泡本身不退出（退出只认气泡外点击 / 返回手势 / 工具栏完成）：
      // 空点击手势拦下该次点击，阻止其冒泡到列表的「点气泡外退出」onClick
      .onClick((): void => {
      })
    }
    .width('100%')
    .margin({ top: 6, bottom: 6 })
    .justifyContent(FlexAlign.End)
  }
}

// 代码块高亮 token 终态类型集（vendor HighlightAnalyzer 分词器只产出这 7 类；vendor 的
// CodeHighLight 未导出，本地定同形接口）：浅色底代码块须逐 token 型显式给文字色
// （vendor 默认 map 面向黑底给白字，缺键落默认黑，浅底上不可控）
interface LightCodeFont {
  text: ResourceColor;
  string: ResourceColor;
  keyword: ResourceColor;
  type: ResourceColor;
  symbol: ResourceColor;
  number: ResourceColor;
  boolean: ResourceColor;
}

const lightCodeFont: LightCodeFont = {
  text: '#182431', string: '#116329', keyword: '#8250DF', type: '#0A69DA',
  number: '#B35900', symbol: '#57606A', boolean: '#0550AE'
};

// 正文档级 markdown 选项（主消息行与进程组内「中间结果」行共用同一口径）：
// 只覆盖 7378 features/chat/MessageParts.tsx 的 markdownStyles 已定义的项
// （paragraph 16、h1 22 / h2 19 / h3 17、加粗、链接色），其余交库默认主题 —— 库内对 theme 做深合并，
// 部分字段即可（文字色取本工程文本 token，浅/深各给一套，随主题切换）。
// 注意：本 vendor 库的段落正文取字号/墨色读的是 theme.fontStyle（Inline 的 Text 基样式与
// parseInlineToken 的 span 均如此），paragraphStyle 无消费方 —— 段落样式必须落在 fontStyle 上。
// 代码块：浅色底 = 卡面色 #FFFDF9 + 1px 线色边框 #E4DDD4 —— 思考行底是卡基色 #F1F3F5，
// 若 code 底与行底同色则"框"隐形（真机报障），同底色上必须有边框才算有框；深色底 #1C1917
// 配 1px 深线 #37332E，两边同宽避免深浅切换时布局位移。fontColor 必须显式给全 7 键 ——
// vendor 默认 map 是面向黑底的全白字，缺键落默认黑（与白字混排不可控）；深色底不给
// fontColor（默认白字 map 存活）。
function buildBodyMdOptions(isDark: boolean, accent: string, accentDark: string): MarkdownOptions {
  const lightInk: ResourceColor = '#182431';
  const darkInk: ResourceColor = '#FAFAFA';
  const lp: MarkdownFontStyle = { fontSize: 16, fontColor: lightInk };
  const l1: MarkdownFontStyle = { fontSize: 22, fontColor: lightInk, fontWeight: FontWeight.Bold };
  const l2: MarkdownFontStyle = { fontSize: 19, fontColor: lightInk, fontWeight: FontWeight.Bold };
  const l3: MarkdownFontStyle = { fontSize: 17, fontColor: lightInk, fontWeight: FontWeight.Bold };
  const lightHeads: MarkdownFontStyle[] = [l1, l2, l3];
  const lCode: CodeStyle = {
    backgroundColor: '#FFFDF9', borderColor: '#E4DDD4', fontSize: 13, borderRadius: 12, fontColor: lightCodeFont
  };
  const lSpan: CodeSpan = { backgroundColor: '#EEEAE2', borderRadius: 5 };
  const lQuote: BlockQuoteStyle = {
    backgroundColor: '#FFF0E5', driveColor: accent, driveWidth: 3
  };
  const lHr: DriveStyle = { driveColor: '#E4DDD4' };
  const light: MarkdownTheme = {
    themeColor: lightInk,
    fontStyle: lp,
    headingStyle: lightHeads,
    linkColor: accent,
    code: lCode,
    codeSpan: lSpan,
    blockQuoteStyle: lQuote,
    hrStyle: lHr
  };
  const dp: MarkdownFontStyle = { fontSize: 16, fontColor: darkInk };
  const d1: MarkdownFontStyle = { fontSize: 22, fontColor: darkInk, fontWeight: FontWeight.Bold };
  const d2: MarkdownFontStyle = { fontSize: 19, fontColor: darkInk, fontWeight: FontWeight.Bold };
  const d3: MarkdownFontStyle = { fontSize: 17, fontColor: darkInk, fontWeight: FontWeight.Bold };
  const darkHeads: MarkdownFontStyle[] = [d1, d2, d3];
  const dCode: CodeStyle = { backgroundColor: '#1C1917', borderColor: '#37332E', fontSize: 13, borderRadius: 12 };
  const dSpan: CodeSpan = { backgroundColor: '#2A2723', borderRadius: 5 };
  const dQuote: BlockQuoteStyle = {
    backgroundColor: '#3B261B', driveColor: accentDark, driveWidth: 3
  };
  const dHr: DriveStyle = { driveColor: '#37332E' };
  const dark: MarkdownTheme = {
    themeColor: darkInk,
    fontStyle: dp,
    headingStyle: darkHeads,
    linkColor: accentDark,
    code: dCode,
    codeSpan: dSpan,
    blockQuoteStyle: dQuote,
    hrStyle: dHr
  };
  const opts: MarkdownOptions = {
    theme: light,
    darkTheme: dark,
    darkMode: isDark
  };
  // 行距口径对齐 console 参照（@agentscope-ai/chat Markdown：正文统一 line-height 1.7 倍率，
  // p/h 的块间 margin 4/7em）：倍率行盒 1.7×16pt≈27.2，块缝 0.571em≈9vp；
  // 倍率设了后覆盖 vendor 的加性 lineSpacing/inlineLineSpace（lineHeightMultiple 官方语义）
  opts.lineHeightMultiple = 1.7;
  opts.lineSpace = 9;
  return opts;
}

// ============ 消息气泡行（对齐 7378 MessageBubble）============
@Component
export struct MessageRow {
  @Prop @Watch('onMessageChanged') message: DisplayMessage = { id: '', role: 'assistant', kind: 'message', parts: [] };
  // 本条是否仍在流式写入（回合未落定）：渲染前对 markdown 做自愈（见 StreamMarkdown）
  @Prop @Watch('onMessageChanged') streaming: boolean = false;
  @Prop last: boolean = false;
  @StorageLink('appIsDark') isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @Prop baseUrl: string = '';
  // 选择态由页面持有（单一事实源，见 ChatDetailPage.selectingId 与 UserRow 同名注释）
  @Prop selecting: boolean = false;
  onRequestSelect: () => void = (): void => {};
  // 喂给 Markdown 的节流文本（见 MD_THROTTLE_MS 注释）
  @State mdShown: string = '';
  // markdown 实测盒高（onAreaChange 上报）：选择态镜像强制与此等高，行高恒定 ⇒ 零跳（见 build 内注释）
  @State mdHeight: number = 0;
  private mdTimer: number = -1;

  aboutToAppear(): void {
    this.mdShown = this.mdForRender();
  }

  aboutToDisappear(): void {
    if (this.mdTimer >= 0) {
      clearTimeout(this.mdTimer);
      this.mdTimer = -1;
    }
  }

  // 渲染用 markdown：先剥离里程碑标题行（⟦ … ⟧，见 stripScrollHeadlines 注释），
  // 流式中再自愈未闭合标记，落定后用剥离后的原文（落盘文本剥离后才是事实）
  private mdForRender(): string {
    const raw: string = stripScrollHeadlines(this.text());
    return this.streaming ? healStreamingMarkdown(raw) : raw;
  }

  // Markdown 选项对象必须复用：每次 build 新建对象会让 Markdown 组件的 @Monitor('options') 每次都
  // 触发（重新 deepMerge 主题 + 重新赋值 optionsClass ⇒ 整块 markdown 子树跟着重渲染），即使内容
  // 没变 —— 流式期间即表现为"整块一直在重绘/闪"。按输入指纹缓存，输入不变就复用同一实例。
  private optsKey: string = '';
  private optsCache: MarkdownOptions | null = null;

  private renderOptions(): MarkdownOptions {
    const key: string = `${this.isDark ? 'd' : 'l'}|${this.theme.accent}|${this.theme.accentDark}`;
    let out: MarkdownOptions | null = this.optsCache;
    if (out === null || this.optsKey !== key) {
      out = this.mdOptions();
      this.optsCache = out;
      this.optsKey = key;
    }
    return out;
  }

  // 文本变化 → 节流落盘（窗口内只安排一次）；流一停立刻落盘，不等窗口
  private onMessageChanged(): void {
    if (!this.streaming) {
      if (this.mdTimer >= 0) {
        clearTimeout(this.mdTimer);
        this.mdTimer = -1;
      }
      this.mdShown = this.mdForRender();
      return;
    }
    if (this.mdTimer >= 0) {
      return;
    }
    this.mdTimer = setTimeout((): void => {
      this.mdTimer = -1;
      this.mdShown = this.mdForRender();
    }, MD_THROTTLE_MS);
  }

  private text(): string {
    return textOfParts(this.message.parts);
  }

  // 选择态分段：按空行（\n\n+）切段，与 markdown 段落解析口径一致；段内单 \n 是软换行，
  // 按空格并入本行（vendor 解析器同款口径）——分段数/行数决定选择态盒高，须与普通态一致。
  // 先剥离里程碑标题行（stripScrollHeadlines，末尾自带 trim）：选择态镜像必须与普通态同文
  private selParagraphs(): string[] {
    const raw: string = stripScrollHeadlines(this.text());
    const out: string[] = [];
    if (raw.length === 0) {
      return out;
    }
    const parts: string[] = raw.split(/\n[ \t]*\n+/);
    for (let i = 0; i < parts.length; i++) {
      const p: string = parts[i].replace(/\n/g, ' ').trim();
      if (p.length > 0) {
        out.push(p);
      }
    }
    return out;
  }

  // 资源文案取字符串（工程统一口径：resourceManager.getStringSync）

  private error(): string {
    return this.message.error !== undefined ? this.message.error : '';
  }

  private media(): DisplayPart[] {
    return mediaPartsOf(this.message.parts);
  }

  private trigger(): ResponseType {
    return this.selecting || this.text().length === 0 ? ResponseType.RightClick : ResponseType.LongPress;
  }

  private async doCopy(): Promise<void> {
    const ok: boolean = await copyTextToClipboard(this.getUIContext(), this.text());
    const msg: string = ok ? t($r('app.string.chat_msg_copied')) : t($r('app.string.chat_msg_copy_failed'));
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  @Builder
  bubbleMenu() {
    Menu() {
      MenuItem({
        content: t($r('app.string.chat_msg_copy')),
        symbolStartIcon: new SymbolGlyphModifier($r('app.media.copy'))
      })
        .onClick((): void => {
          this.doCopy();
        })
      MenuItem({
        content: t($r('app.string.chat_msg_select')),
        symbolStartIcon: new SymbolGlyphModifier($r('sys.symbol.smart_selection_area'))
      })
        .onClick((): void => {
          if (this.text().length > 0) {
            this.onRequestSelect();
          }
        })
    }
  }

  // markdown 渲染选项（口径见 buildBodyMdOptions 注释）；长回复不截断、全量渲染
  // （console 口径：最终回复无展开收起）
  private mdOptions(): MarkdownOptions {
    return buildBodyMdOptions(this.isDark, this.theme.accent, this.theme.accentDark);
  }

  build() {
    Column() {
      if (this.last) {
        Text($r('app.string.chat_answer_label'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ bottom: 4 })
      }
      if (this.error().length > 0) {
        Text($r('app.string.chat_answer_failed'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.status_error'))
          .fontWeight(FontWeight.Bold)
          .margin({ bottom: 2 })
        Text(this.error())
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.status_error'))
          .wordBreak(WordBreak.BREAK_ALL)
      } else if (this.text().length > 0) {
        if (this.selecting) {
          // 选择态：保留纯文本 Text —— 系统文本选择与 copyOption 只在这条路上可用，
          // 换成渲染组件会把「复制 / 选择文本」这条已验收能力打掉。
          // 零跳契约（结构版）：镜像盒高强制 = markdown 实测盒高（mdHeight，onAreaChange 上报）。
          // 段落几何镜像 vendor 倍率行盒口径（行盒 1.7×16pt、块顶半 leading 6、块间缝 9，
          // 与 renderOptions 的 lineHeightMultiple/lineSpace 同源），纯文本消息两态天然等高；
          // 但含表格、标题、代码块的行，纯文本镜像的自然高与 vendor 盒高不一致
          //（表格=定宽两列 Scroll、标题 22/19/17 号字、代码块独立卡底——逐块复刻等于重写渲染器），
          // 故强制等高兜底：矮了留白、高了内部滚动（BarState.Off 无滚动条）。
          // 行高恒定 ⇒ 贴底列表（stackFromEnd）进出选择态不重锚、整页不跳。
          Scroll() {
            Column({ space: 9 }) {
              ForEach(this.selParagraphs(), (p: string) => {
                Text(p)
                  .fontSize(16)
                  .fontColor($r('app.color.input_text'))
                  .lineHeightMultiple(1.7)
                  .padding({ top: 6 })
                  .maxLines(NO_LINE_LIMIT)
                  .textOverflow({ overflow: TextOverflow.Ellipsis })
                  .copyOption(CopyOptions.LocalDevice)
              }, (p: string, i: number): string => 'p' + i)
            }
            .width('100%')
          }
          .width('100%')
          .height(this.mdHeight > 0 ? this.mdHeight : 'auto')
          .scrollBar(BarState.Off)
          .edgeEffect(EdgeEffect.None)
          // 进出选择态与 markdown 交叉淡入淡出（两分支各挂同款对称过渡，140ms 与工具栏同档）
          .transition(TransitionEffect.OPACITY.animation({ duration: 140, curve: Curve.EaseOut }))
        } else {
          // 普通态：markdown 渲染（口径见 mdOptions 注释）；内容走节流副本（见 MD_THROTTLE_MS）
          // mdHeight = 实测盒高，供选择态镜像强制等高（零跳，见上注释）
          Markdown({ content: this.mdShown, options: this.renderOptions() })
            .width('100%')
            .onAreaChange((_o: Area, n: Area): void => {
              this.mdHeight = Number(n.height);
            })
            .transition(TransitionEffect.OPACITY.animation({ duration: 140, curve: Curve.EaseOut }))
        }
      }
      // 该段自带媒体（图片 / 文件卡）
      if (this.media().length > 0) {
        Column() {
          MediaParts({ parts: this.media(), baseUrl: this.baseUrl })
        }
        .width('100%')
        .margin({ top: 8 })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: 12, right: 12, top: 10, bottom: 10 })
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_surface'))
    .bindContextMenu(this.bubbleMenu(), this.trigger(), contextMenuOptions())
    // 选择态点气泡本身不退出（拦截冒泡，写法与 UserRow 一致）
    .onClick((): void => {
    })
    .margin({ top: 6, bottom: 6 })
  }
}

// ============ 回合工具产出媒体行 ============
@Component
export struct MediaRow {
  @Prop parts: DisplayPart[] = [];
  @Prop baseUrl: string = '';
  // 本行结构键（分发器传入，= 本行行键）：开合取证探针的键
  rowKey: string = '';
  // 文件/媒体清单默认收起：console 把它作为回合末尾的一项（ResponseArtifactList）按需展示，
  // 不是一直挂在下方的常驻块
  @State expanded: boolean = false;
  // 清单视口高（两阶段开合，与 ProcessRow 同机制）：子树的结构插入/摘除不是属性动画——
  // 写进 animateTo 闭包里会在下一帧整体出现/消失（行高一步跳变、List 按底边重锚 →
  // 屏幕"闪一下"），须套 0 高视口，测得自然高后由高度弹簧在开合意图当帧起插
  @State bodyH: number = 0;
  @State bodyMounted: boolean = false;
  private bodyNaturalH: number = 0;
  private bodyOpened: boolean = false;
  private bodyAnimId: number = 0;
  private bodyAnimRunning: boolean = false;

  private headerText(): string {
    const n: string = this.parts.length.toString();
    const raw: string = t($r('app.string.chat_files_section'));
    return raw.length > 0 ? raw.replace('%d', n) : n;
  }

  // 两阶段「开」：已挂载且测得高 → 直接播；否则挂载 0 高视口，等首帧测得自然高再播
  private openBody(): void {
    if (this.bodyMounted && this.bodyOpened) {
      return;
    }
    this.bodyMounted = true;
    if (this.bodyNaturalH > 0) {
      this.bodyOpened = true;
      this.startBodyAnim(this.bodyNaturalH);
    }
  }

  // 两阶段「收」：弹簧滑合 → onFinish 摘除内容（未挂载/零高 = 无动画直接复位）
  private closeBody(): void {
    if (!this.bodyMounted || this.bodyH <= 0) {
      this.bodyMounted = false;
      this.bodyOpened = false;
      this.bodyNaturalH = 0;
      return;
    }
    this.bodyOpened = false;
    this.startBodyAnim(0);
  }

  // 开合统一曲线：springMotion（口径同 ProcessRow.startBodyAnim，行/组/文件卡同一节奏）。
  // onFinish 带动画 id 判重守卫（途中被重定向的旧回调作废）
  private startBodyAnim(toH: number): void {
    this.bodyAnimId++;
    const id: number = this.bodyAnimId;
    this.bodyAnimRunning = true;
    this.getUIContext().animateTo({
      curve: curves.springMotion(0.4, 1),
      onFinish: (): void => {
        if (id !== this.bodyAnimId) {
          return;
        }
        this.bodyAnimRunning = false;
        if (toH <= 0) {
          this.bodyMounted = false;
          this.bodyNaturalH = 0;
        } else {
          // 开完成：校到最新自然高（途中重定向的终点可能是较早测量值）
          this.bodyH = this.bodyNaturalH;
        }
      }
    }, (): void => {
      this.bodyH = toH;
    });
  }

  // 停掉在跑的体高弹簧并裸对齐最新自然高（官方「持续时间为 0 的动画闭包中改变属性」
  // = 停动画机制，先自增 id 使旧 onFinish 被守卫作废）。口径同 ProcessRow.stopBodyAnim：
  // 内容增长（媒体图卡懒加载）期间逐测量重定向的弹簧追不上移动目标，视口滞后内容
  // 裁底「展示不全」
  private stopBodyAnim(): void {
    this.bodyAnimId++;
    this.getUIContext().animateTo({ duration: 0 }, (): void => {
      this.bodyH = this.bodyNaturalH;
    });
    this.bodyAnimRunning = false;
  }

  // 内层内容列实测高（Scroll 视口不钳制内容自然高，口径同 CollapsibleBody）：首测 →
  // 目标态为开则播开合动画；已开稳定期 → 高度变化（媒体图卡懒加载）裸跟随
  private onBodyMeasured(h: number): void {
    if (h <= 0) {
      return;
    }
    // 同值复测（布局期/滚动期的重复 onAreaChange）不做任何事：省掉状态写入与后续重排
    if (h === this.bodyNaturalH) {
      return;
    }
    this.bodyNaturalH = h;
    if (this.bodyOpened) {
      if (this.bodyAnimRunning) {
        this.stopBodyAnim();
      } else {
        this.bodyH = h;
      }
      return;
    }
    if (this.bodyMounted && this.expanded) {
      this.bodyOpened = true;
      this.startBodyAnim(h);
    }
  }

  build() {
    Column() {
      Row() {
        Text(this.headerText())
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_secondary'))
          .fontWeight(FontWeight.Medium)
          .layoutWeight(1)
        Text(this.expanded ? $r('app.string.chat_answer_collapse') : $r('app.string.chat_answer_expand'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .onClick((): void => {
        this.expanded = !this.expanded;
        if (this.expanded) {
          this.openBody();
        } else {
          this.closeBody();
        }
      })
      if (this.bodyMounted) {
        Scroll() {
          MediaParts({ parts: this.parts, baseUrl: this.baseUrl })
            .onAreaChange((_old: Area, cur: Area): void => {
              this.onBodyMeasured(cur.height as number);
            })
        }
        .width('100%')
        .height(this.bodyH)
        // 与过程组/思考行同一口径：盒高动画期间内容贴合顶边（RenderFit 默认 CENTER 会让
        // 内容在收小时上下两端同时内收），收起才是展开的镜像
        .renderFit(RenderFit.TOP)
        .scrollBar(BarState.Off)
        .enableScrollInteraction(false)
      }
    }
    .width('100%')
    .margin({ top: 8, bottom: 6 })
  }
}

// ============ 待发回合「正在生成…」占位行 ============
@Component
export struct PendingRow {
  build() {
    Column() {
      Text($r('app.string.chat_answer_pending'))
        .fontSize(UiTokens.fsSecondary)
        .fontColor($r('app.color.text_tertiary'))
        .margin({ top: 6, bottom: 6 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}

// ============ 步骤组卡（思考 / 工具）============
// 折叠时不渲染子树（对齐 console 的 LazyAccordion destroy-on-close）。
function toolLabel(name: string | undefined): string {
  if (name === undefined || name.length === 0) {
    return '';
  }
  return name.replace(/_/g, ' ');
}

// 工具状态等级（对齐 7378 toolStateLabel）：0=调用（无结果无状态）/1=失败/2=完成
function toolStateLevel(m: DisplayMessage): number {
  const hasOutput: boolean = m.toolOutput !== undefined && m.toolOutput.length > 0;
  const state: string = m.toolState !== undefined ? m.toolState : '';
  if (!hasOutput && state.length === 0) {
    return 0;
  }
  if (/error|failed|denied|interrupted/i.test(state)) {
    return 1;
  }
  return 2;
}

// 合并连续同工具消息（对齐 7378 mergeToolMessages：同 callId 或同 name 或无名同 input 无 output）
export function mergeToolMessages(messages: DisplayMessage[]): DisplayMessage[] {
  const merged: DisplayMessage[] = [];
  for (const message of messages) {
    if (message.kind !== 'tool') {
      merged.push(message);
      continue;
    }
    const prev: DisplayMessage | null = merged.length > 0 ? merged[merged.length - 1] : null;
    if (prev !== null && prev.kind === 'tool') {
      const sameCall: boolean =
        (message.toolCallId !== undefined && message.toolCallId.length > 0
          && message.toolCallId === prev.toolCallId)
        || (message.toolName !== undefined && message.toolName.length > 0
          && message.toolName === prev.toolName)
        || (message.toolName === undefined && message.toolInput !== undefined
          && prev.toolInput !== undefined
          && (prev.toolOutput === undefined || prev.toolOutput.length === 0));
      if (sameCall) {
        const parts: DisplayPart[] = [];
        const seen: string[] = [];
        for (const p of prev.parts.concat(message.parts)) {
          const k: string = p.type === 'text' ? `t:${p.text !== undefined ? p.text : ''}`
            : `${p.type}:${p.url !== undefined ? p.url : ''}`;
          if (seen.indexOf(k) < 0) {
            seen.push(k);
            parts.push(p);
          }
        }
        const nm: DisplayMessage = {
          id: prev.id,
          role: prev.role,
          kind: 'tool',
          parts: parts,
          toolName: prev.toolName !== undefined ? prev.toolName : message.toolName,
          toolState: message.toolState !== undefined ? message.toolState : prev.toolState,
          toolCallId: prev.toolCallId !== undefined ? prev.toolCallId : message.toolCallId,
          toolInput: prev.toolInput !== undefined ? prev.toolInput : message.toolInput,
          toolOutput: message.toolOutput !== undefined ? message.toolOutput : prev.toolOutput
        };
        merged[merged.length - 1] = nm;
        continue;
      }
    }
    merged.push(message);
  }
  return merged;
}

@Component
struct ProcessHeader {
  @Prop process: DisplayMessage[] = [];
  @StorageLink('appIsDark') isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 生成中的过程组默认展开（对齐 console getCollapsedStepPresentation：generating → defaultOpen true）
  // 本组是否为「活动组」（正在生成）：活动组头部显示转圈，其工具行未出结果时显示进行中
  @Prop generating: boolean = false;
  // 展开态由页面持有：箭头与点击反馈跟它（点按即翻转，不等动画）
  @Prop expanded: boolean = false;
  // 组框是否处于展开几何（body 盒高度 > 0：展开中 / 收起动画中）：框几何（底圆角/底 margin）
  // 跟它 —— 收起动画期间（弹簧高度插值）body 盒仍占高，几何须保持展开态，动画结束的一瞬
  // 整体归位，不闪 6vp 接缝
  @Prop frameOpen: boolean = false;
  onToggle: () => void = (): void => {};

  // 资源文案取字符串（工程统一口径：resourceManager.getStringSync）

  private accentColor(): string {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private summary(): string {
    const msgs: DisplayMessage[] = this.process;
    let tools: number = 0;
    let toolCalls: number = 0;
    let hasReasoning: boolean = false;
    for (const m of msgs) {
      if (m.kind === 'tool') {
        tools++;
        if (m.toolState === undefined || m.toolState.length === 0) {
          toolCalls++;
        }
      } else if (m.kind === 'reasoning') {
        hasReasoning = true;
      }
    }
    const effectiveTools: number = toolCalls > 0 ? toolCalls : tools;
    const parts: string[] = [];
    if (hasReasoning) {
      parts.push(t($r('app.string.chat_process_summary_think')));
    }
    if (effectiveTools > 0) {
      parts.push(t($r('app.string.chat_process_summary_tools')).replace('%d', effectiveTools.toString()));
    }
    if (parts.length === 0) {
      parts.push(t($r('app.string.chat_process_summary_mid')).replace('%d', msgs.length.toString()));
    }
    return parts.join(' · ');
  }

  build() {
    Column() {
      Row() {
        Image($r('app.media.activity'))
          .width(16).height(16)
          .fillColor(this.accentColor())
          .margin({ right: 8 })
        Column() {
          Text($r('app.string.chat_process_tool'))
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_secondary'))
            .fontWeight(FontWeight.Medium)
          Text(this.summary())
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_tertiary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        if (this.generating) {
          LoadingProgress()
            .width(16)
            .height(16)
            .color(this.accentColor())
            .margin({ right: 6 })
        }
        Text(this.expanded ? '▲' : '▼')
          .fontSize(12)
          .fontColor($r('app.color.text_tertiary'))
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 10, bottom: 10 })
      .onClick((): void => {
        this.onToggle();
      })
    }
    .width('100%')
    // body 盒处于展开几何时组头是组框的顶盖：底部圆角归零、底 margin 归零，与首行的左右边框
    // 接合成一整块圆角矩形（console 口径：Accordion 展开 = 容器边框包住 header + body，
    // body 内缩；7378 = processCard 单卡包 header + body）。收起时恢复独立 chip 的四边圆角与底 margin。
    // 几何跟 frameOpen；frameOpen 在收起的 animateTo 闭包内与 animH 同时翻转，圆角与底 margin
    // 因此和高度走同一弹簧渐进插值（两分支同用四角对象写法，保证 number↔number 逐角插值）
    .borderRadius(this.frameOpen
      ? { topLeft: UiTokens.cardRadius, topRight: UiTokens.cardRadius, bottomLeft: 0, bottomRight: 0 }
      : { topLeft: UiTokens.cardRadius, topRight: UiTokens.cardRadius,
        bottomLeft: UiTokens.cardRadius, bottomRight: UiTokens.cardRadius })
    .backgroundColor($r('app.color.card_surface'))
    .borderWidth(1)
    .borderColor($r('app.color.line'))
    .margin({ top: 6, bottom: this.frameOpen ? 0 : 6 })
  }
}

@Component
struct ProcessRow {
  @Prop @Watch('onMessageChanged') message: DisplayMessage = { id: '', role: 'assistant', kind: 'message', parts: [] };
  @StorageLink('appIsDark') isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 本行所属过程组是否为「活动组」（正在生成）；同时作为"流式中"判据 → 渲染前自愈未闭合标记
  @Prop @Watch('onGeneratingChanged') generating: boolean = false;
  // 本行是否为组内末位（活动组里正在被写入的那条思考行 → 行首转圈）
  @Prop last: boolean = false;
  // 本行是否为组内首行（组框顶部与组头底边相接，不画顶分隔线）
  @Prop first: boolean = true;
  // 本行结构键（组传入：组键#序号）：开合取证探针的键
  rowKey: string = '';
  // 收起逐帧高度差 → 页面补偿列表滚动（行头钉住，收起 = 展开的镜像）
  onCollapseStep: (deltaVp: number) => void = (): void => {};
  // 工具行：展开参数 / 结果详情；思考行：展开思考正文（默认收起，console OperateCard 口径）
  @State detailExpanded: boolean = false;
  // 喂给 Markdown 的节流文本（见 MD_THROTTLE_MS 注释）
  @State mdShown: string = '';
  private mdTimer: number = -1;

  // 行级 body 两阶段开合（机制见 CollapsibleBody 注释）：视口高 0↔自然高弹簧插值；
  // 内容只在 bodyMounted 期驻留树上（收起动画结束即摘除，等价 console destroy-on-close，
  // 思考正文可达十余万 vp，全行常驻不可接受）
  @State @Watch('onBodyHChanged') bodyH: number = 0;
  private prevBodyH: number = 0;
  // 收起逐帧高度差 → 页面补偿滚动，使行头屏内不动（否则贴底 regime 下底边钉住、
  // 行头也随之移动 = 观感"上下从中间收"）
  private onBodyHChanged(): void {
    const d: number = this.bodyH - this.prevBodyH;
    this.prevBodyH = this.bodyH;
    if (d !== 0 && !this.bodyOpenTarget() && this.bodyMounted) {
      this.onCollapseStep(d);
    }
  }
  @State bodyMounted: boolean = false;
  // 视口上间距：与 bodyH 走同一弹簧（开 PROC_BODY_GAP / 收 0），见 PROC_BODY_GAP 注释
  @State bodyGap: number = 0;
  private bodyNaturalH: number = 0;
  private bodyOpened: boolean = false;
  private bodyAnimId: number = 0;
  // 开合动画是否进行中
  private bodyAnimRunning: boolean = false;
  private bodyScroller: Scroller = new Scroller();
  // 思考行流式期间的显式开合意图：一旦用户点过头部，开合只认 detailExpanded（不再被
  // generating 自动态顶开）；流结束一并复位，回到 console 的「回合结束自动收起」口径
  private userToggled: boolean = false;

  // 资源文案取字符串（工程统一口径：resourceManager.getStringSync）

  // 渲染用 markdown：先剥离里程碑标题行（⟦ … ⟧，见 stripScrollHeadlines 注释），
  // 流式中再自愈未闭合标记，落定后用剥离后的原文（落盘文本剥离后才是事实）
  private mdForRender(): string {
    const raw: string = stripScrollHeadlines(this.text());
    return this.generating ? healStreamingMarkdown(raw) : raw;
  }

  // Markdown 选项对象必须复用（理由同 MessageRow.renderOptions）：每次 build 新建对象会触发
  // Markdown 的 @Monitor('options') → 整块子树重渲染，流式期间表现为"一直在重绘/闪"。
  private optsKey: string = '';
  private optsCache: MarkdownOptions | null = null;

  private renderReasoningOptions(): MarkdownOptions {
    const key: string = `${this.isDark ? 'd' : 'l'}|${this.theme.accent}|${this.theme.accentDark}`;
    let out: MarkdownOptions | null = this.optsCache;
    if (out === null || this.optsKey !== key) {
      out = this.mdReasoning();
      this.optsCache = out;
      this.optsKey = key;
    }
    return out;
  }

  // 中间结果行（kind='message'）：中间输出不是思考过程 → 与正文同一档（buildBodyMdOptions，
  // 16pt 深墨），与思考行（renderReasoningOptions，11pt 灰）区分
  private midOptsKey: string = '';
  private midOptsCache: MarkdownOptions | null = null;

  private renderMidOptions(): MarkdownOptions {
    const key: string = `${this.isDark ? 'd' : 'l'}|${this.theme.accent}|${this.theme.accentDark}`;
    let out: MarkdownOptions | null = this.midOptsCache;
    if (out === null || this.midOptsKey !== key) {
      out = buildBodyMdOptions(this.isDark, this.theme.accent, this.theme.accentDark);
      this.midOptsCache = out;
      this.midOptsKey = key;
    }
    return out;
  }

  // 行 body 目标态是否开启（驱动两阶段动画；行尾箭头同读此值，点时即翻不等动画走完）：
  // 思考行 = 用户显式开合过则只认手动态，否则流式中自动开 或 手动展开；
  // 工具行 = 手动展开且可展开（短详情不可展开，无 body）
  private bodyOpenTarget(): boolean {
    if (this.thinking()) {
      return this.userToggled ? this.detailExpanded : (this.generating || this.detailExpanded);
    }
    return this.detailExpanded && this.detailCollapsible();
  }

  // 行尾箭头显示的目标态 = 开合目标态（箭头渲染条件已保证工具行只在可展开时出现）
  private bodyShown(): boolean {
    return this.bodyOpenTarget();
  }

  // 开合入口（在 detailExpanded 翻转之后调用，读目标态）
  private flipBody(): void {
    if (this.bodyOpenTarget()) {
      this.openBody();
    } else {
      this.closeBody();
    }
  }

  // 两阶段「开」：已挂载且测得高 → 直接播（动画途中再点=从当前值重定向，animId 守卫旧
  // onFinish）；否则挂载 0 高视口，等首帧 onAreaChange 测得自然高再播
  private openBody(): void {
    if (this.bodyMounted && this.bodyOpened) {
      return;
    }
    if (!this.bodyMounted) {
      // 新挂载：间距自 0 起（随开合弹簧升到 PROC_BODY_GAP）——挂载当帧布局零变化
      this.bodyGap = 0;
      this.bodyMounted = true;
    }
    if (this.bodyNaturalH > 0) {
      this.bodyOpened = true;
      this.startBodyAnim(this.bodyNaturalH);
    }
  }

  // 两阶段「收」：弹簧滑合 → onFinish 摘除内容（未挂载/零高 = 无动画直接复位）
  private closeBody(): void {
    if (!this.bodyMounted || this.bodyH <= 0) {
      this.bodyMounted = false;
      this.bodyOpened = false;
      this.bodyNaturalH = 0;
      this.bodyGap = 0;
      return;
    }
    this.bodyOpened = false;
    this.startBodyAnim(0);
  }

  // 行级开合统一曲线：springMotion（官方推荐物理弹簧——达终点速度为 0 不「戛然而止」，
  // 时长由位移与参数自动计算，指定 duration 不生效；response 0.4 + 临界阻尼不越冲）。
  // 与组级 frame、文件卡展开同一曲线，一个节奏。
  private startBodyAnim(toH: number): void {
    this.bodyAnimId++;
    const id: number = this.bodyAnimId;
    this.bodyAnimRunning = true;
    this.getUIContext().animateTo({
      curve: curves.springMotion(0.4, 1),
      onFinish: (): void => {
        if (id !== this.bodyAnimId) {
          return;
        }
        this.bodyAnimRunning = false;
        if (toH <= 0) {
          this.bodyMounted = false;
          // 内容已摘除，测量值作废：重展开时重挂载后必以新首测为准（工具行收起/展开态
          // 的 maxLines 不同，旧值会指错动画终点）
          this.bodyNaturalH = 0;
        } else {
          // 开完成：校到最新自然高（消除残留裁切）
          this.bodyH = this.bodyNaturalH;
        }
      }
    }, (): void => {
      this.bodyH = toH;
      // 间距与高度同一弹簧、同帧归位：收合末帧间距已是 0，内容摘除不产生布局跳变
      this.bodyGap = toH > 0 ? PROC_BODY_GAP : 0;
    });
  }

  // 停掉在跑的行级 body 动画并裸对齐最新自然高（官方「持续时间为 0 的动画闭包中改变
  // 属性」= 停动画机制；闭包内必须写属性才生效。先自增 id 使旧动画 onFinish 被守卫作废）。
  // 用途：流式增长期间进行中的开合弹簧先停掉再裸跟随——
  // 逐测量重定向的弹簧永远追不上移动目标（springMotion 时长随位移与在先速度自动计算，
  // 追赶窗口内新内容不断产生），视口滞后内容 → Scroll 裁底「展示不全」
  private stopBodyAnim(): void {
    this.bodyAnimId++;
    this.getUIContext().animateTo({ duration: 0 }, (): void => {
      this.bodyH = this.bodyNaturalH;
    });
    this.bodyAnimRunning = false;
  }

  // 内层内容列实测高（Scroll 主轴内容大小 = 子布局后总高，不被 0 高视口钳制，口径见
  // CollapsibleBody 注释）：首测 → 目标态为开则播开合动画；已开（目标态开）→ 内容增长
  // （流式逐帧）先停掉进行中的弹簧再裸跟随不补间（与组级 frame 同铁律，补间/追赶弹簧
  // 会造成「呼吸」闪与裁底）；收起动画中 → 不写，任其滑到 0
  private onBodyMeasured(h: number): void {
    if (h <= 0) {
      return;
    }
    // 同值复测（布局期/滚动期的重复 onAreaChange）不做任何事：省掉状态写入、重排与日志
    // （真机取证曾出现单行 1s 内 28 次同值回调）
    if (h === this.bodyNaturalH) {
      return;
    }
    this.bodyNaturalH = h;
    if (this.bodyOpened) {
      if (!this.bodyOpenTarget()) {
        // 收起动画进行中：不写，任其滑到 0
        return;
      }
      if (this.bodyAnimRunning) {
        this.stopBodyAnim();
      } else {
        this.bodyH = h;
      }
      return;
    }
    if (this.bodyMounted && this.bodyOpenTarget()) {
      this.bodyOpened = true;
      this.startBodyAnim(h);
    }
  }

  aboutToAppear(): void {
    this.mdShown = this.mdForRender();
    // 活动思考行（新流式段）入树即展开：先挂载（间距自 0 起），onBodyMeasured 首测后播开合动画
    if (this.thinking() && this.generating) {
      this.bodyGap = 0;
      this.bodyMounted = true;
    }
  }

  aboutToDisappear(): void {
    if (this.mdTimer >= 0) {
      clearTimeout(this.mdTimer);
      this.mdTimer = -1;
    }
  }

  // 文本/流态变化 → 节流落盘（窗口内只安排一次）；流一停立刻落盘，不等窗口
  private onMessageChanged(): void {
    this.refreshMd();
  }

  // 对齐 console Thinking 的 remount 语义（SDK 用 key={loading} 让加载态翻转时重置开合）：
  // 流一结束思考行自动收起（播收合动画，与手动收起同一出口）；期间照常刷新渲染文本
  private onGeneratingChanged(): void {
    if (!this.generating) {
      // 流结束：显式开合意图一并复位（下一段流式重新回到「自动开」口径）
      this.userToggled = false;
      this.detailExpanded = false;
      if (this.thinking() && this.bodyMounted) {
        this.closeBody();
      }
    }
    this.refreshMd();
  }

  private refreshMd(): void {
    if (!this.generating) {
      if (this.mdTimer >= 0) {
        clearTimeout(this.mdTimer);
        this.mdTimer = -1;
      }
      this.mdShown = this.mdForRender();
      return;
    }
    if (this.mdTimer >= 0) {
      return;
    }
    this.mdTimer = setTimeout((): void => {
      this.mdTimer = -1;
      this.mdShown = this.mdForRender();
    }, MD_THROTTLE_MS);
  }

  private accentColor(): string {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private title(): ResourceStr {
    if (this.message.kind === 'reasoning') {
      return $r('app.string.chat_process_thinking_label');
    }
    if (this.message.kind === 'tool') {
      const name: string = toolLabel(this.message.toolName);
      return name.length > 0 ? name : $r('app.string.chat_tool_default');
    }
    return $r('app.string.chat_process_mid');
  }

  private stateLevel(): number {
    return toolStateLevel(this.message);
  }

  // 行尾状态文案随执行态变：进行中（活动组且未出结果）/ 失败 / 完成。
  // 非活动组里的无结果工具行按「调用」呈现（对齐 console：非活动组状态一律视为已完成）。
  private stateLabel(): ResourceStr {
    const lv: number = this.stateLevel();
    if (lv === 0) {
      return this.generating ? $r('app.string.chat_process_running') : $r('app.string.chat_process_call');
    }
    if (lv === 1) {
      return $r('app.string.chat_process_failed');
    }
    return $r('app.string.chat_process_done');
  }

  private stateColor(): ResourceColor {
    const lv: number = this.stateLevel();
    if (lv === 1) {
      return $r('app.color.status_error');
    }
    if (lv === 2) {
      return $r('app.color.text_secondary');
    }
    return $r('app.color.text_tertiary');
  }

  // 思考行：整行以灰底卡片呈现（对齐 console 的 OperateCard），与工具行区分
  private thinking(): boolean {
    return this.message.kind === 'reasoning';
  }

  // 行首图标槽（对齐 console ToolCardShell 的 summary 图标）：思考行 = 灯泡；
  // 工具行 = 成功对勾 / 失败叉（console 的 toolCallIconSuccess / toolCallIconError）
  private leadIcon(): Resource {
    if (this.message.kind === 'reasoning') {
      return $r('app.media.lightbulb');
    }
    return this.stateLevel() === 1 ? $r('app.media.circle_x') : $r('app.media.circle_check');
  }

  private leadIconColor(): ResourceColor {
    return this.stateLevel() === 1 ? $r('app.color.status_error') : this.accentColor();
  }

  // 行首标题：调用中追加「处理中...」（对齐 console：{title} {t("tool.loading")}）
  private leadTitle(): ResourceStr {
    if (!this.running()) {
      return this.title();
    }
    const loading: string = t($r('app.string.chat_tool_loading'));
    if (this.message.kind === 'tool') {
      const name: string = toolLabel(this.message.toolName);
      const base: string = name.length > 0 ? name : t($r('app.string.chat_tool_default'));
      return `${base} ${loading}`;
    }
    return `${t($r('app.string.chat_process_thinking_label'))} ${loading}`;
  }

  // 调用中（对齐 console ToolCardShell：status === "calling" && isStreaming）→ 行首转圈：
  // ① 活动组里尚未返回结果的工具行；② 活动组末位那条（正在被写入的思考行）。
  private running(): boolean {
    if (!this.generating) {
      return false;
    }
    if (this.message.kind === 'tool') {
      return this.stateLevel() === 0;
    }
    return this.message.kind === 'reasoning' && this.last;
  }

  // 思考行的 markdown 选项：字号与配色压到次级（浅/深各自给显式色，理由见 MessageRow.mdOptions）。
  // 正文只在展开态挂载（console OperateCard 口径），不存在截断选项——库的 maxLines 只作用于
  // 单个行内 Text，截不住代码块/列表等块级结构，"6 行预览"实际是全量渲染（长思考行撑出
  // 十余万 vp 的组卡即因此）。
  // 字号 11（比正文 16 小五档）、行距收紧到 8（库默认 12）、墨色更灰：
  // 思考过程是过程性信息，视觉权重应低于回复正文。
  // 段落正文读 theme.fontStyle（见 mdOptions 注释）；themeColor 只影响列表符号色（MList），保留。
  private mdReasoning(): MarkdownOptions {
    const lightInk: ResourceColor = '#8C8C8C';
    const darkInk: ResourceColor = '#9A9A9A';
    const size: number = UiTokens.fsCaption - 1;
    const l1: MarkdownFontStyle = { fontSize: size + 2, fontColor: lightInk, fontWeight: FontWeight.Bold };
    const d1: MarkdownFontStyle = { fontSize: size + 2, fontColor: darkInk, fontWeight: FontWeight.Bold };
    const light: MarkdownTheme = {
      themeColor: lightInk,
      fontStyle: { fontSize: size, fontColor: lightInk },
      headingStyle: [l1, l1, l1],
      linkColor: this.theme.accent,
      // 浅色底同正文档口径（见 buildBodyMdOptions 代码块注释），字号随思考档 -1
      code: {
        backgroundColor: '#FFFDF9', borderColor: '#E4DDD4', fontSize: size - 1, borderRadius: 10, fontColor: lightCodeFont
      },
      codeSpan: { backgroundColor: '#EEEAE2', borderRadius: 4 },
      // drive 色对齐 console blockquote 的 accent 左线（此前 #999999 与正文档口径不一）；
      // 底色同 code 改卡面色——引用块同在思考行（卡基色底）上，同色底会吃掉"框"
      blockQuoteStyle: { backgroundColor: '#FFFDF9', driveColor: this.theme.accent, driveWidth: 3 },
      hrStyle: { driveColor: '#E4DDD4' }
    };
    const dark: MarkdownTheme = {
      themeColor: darkInk,
      fontStyle: { fontSize: size, fontColor: darkInk },
      headingStyle: [d1, d1, d1],
      linkColor: this.theme.accentDark,
      code: { backgroundColor: '#1C1917', borderColor: '#37332E', fontSize: size - 1, borderRadius: 10 },
      codeSpan: { backgroundColor: '#2A2723', borderRadius: 4 },
      blockQuoteStyle: { backgroundColor: '#2A2723', driveColor: '#8A8A8A', driveWidth: 3 },
      hrStyle: { driveColor: '#37332E' }
    };
    const opts: MarkdownOptions = { theme: light, darkTheme: dark, darkMode: this.isDark };
    // 行距口径对齐 console 思考块（OperateCard Thinking：12px 字 / 20px 行高 = 1.67× 倍率，
    // 纯文本节奏、无块 margin）：本侧 11pt → 行盒 ≈18.4、块缝 6（=0.571em）；
    // 倍率设了后覆盖加性行距（此前 8vp 加性 + 空行 token 占缝造成"宽窄不一"的分档）
    opts.lineHeightMultiple = 1.67;
    opts.lineSpace = 6;
    return opts;
  }

  private text(): string {
    return textOfParts(this.message.parts);
  }

  private toolDetailText(which: string): string {
    if (which === 'input') {
      return this.message.toolInput !== undefined ? this.message.toolInput : '';
    }
    return this.message.toolOutput !== undefined ? this.message.toolOutput : '';
  }

  private detailCollapsible(): boolean {
    const a: number = this.message.toolInput !== undefined ? this.message.toolInput.length : 0;
    const b: number = this.message.toolOutput !== undefined ? this.message.toolOutput.length : 0;
    // 有内容即可展开：此前 >420 阈值下短输入/短输出无箭头、无「查看全部」、无任何入口，
    // 即现网「有些工具调用无法展开」的结构性根因
    return a + b > 0;
  }

  @Builder
  ToolDetailBlock(which: string) {
    if (this.toolDetailText(which).length > 0) {
      Column() {
        Text(which === 'input' ? $r('app.string.chat_tool_input_label') : $r('app.string.chat_tool_output_label'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ bottom: 2 })
        Text(this.toolDetailText(which))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_secondary'))
          .lineHeight(18)
          .wordBreak(WordBreak.BREAK_ALL)
          .maxLines(this.detailExpanded ? NO_LINE_LIMIT : 6)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .padding(8)
      .borderRadius(UiTokens.chipRadius)
      .backgroundColor($r('app.color.card_bg'))
      .margin({ top: 6 })
    }
  }

  // 两阶段开合 body 视口（组级 ProcessGroup 同机制的**行级**版，且内容非常驻）：
  // 非交互 Scroll（enableScrollInteraction(false) + 滚动条 Off）当视口，官方《Scroll》参考
  // 口径「主轴方向内容大小为所有子组件布局后的总大小」——内层 Column 不被 0 高视口钳制，
  // onAreaChange 恒测得自然高 → 首测驱动弹簧开合动画（展开）；收起滑合到 0 后摘除内容
  // （destroy-on-close，思考正文可达十余万 vp 不能全行常驻）。交互关闭后 Scroll 不吃竖直
  // 手势，外层 List 照常滚动；markdown 内代码块的横向 Scroll 与视口不冲突（方向不同）。
  @Builder
  CollapsibleBody() {
    if (this.bodyMounted) {
      Scroll(this.bodyScroller) {
        Column() {
          if (this.message.kind === 'tool') {
            this.ToolDetailBlock('input')
            this.ToolDetailBlock('output')
          } else {
            // 思考正文走 markdown 渲染（console HostMessage 对 text 项用 DeferredMarkdown），
            // 配色压到次级灰；内容走节流副本（见 MD_THROTTLE_MS）不重起解析任务
            Markdown({ content: this.mdShown, options: this.renderReasoningOptions() })
              .width('100%')
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        // 思考正文套带左竖线的块（console OperateCard LineBody = 左侧 1px 竖线 + 内容内缩，
        // 灰底由外层卡片承载）；工具详情块自带底色盒，无竖线
        .padding({ left: this.message.kind === 'tool' ? 0 : 16 })
        .border({
          width: { left: this.message.kind === 'tool' ? 0 : 1 },
          color: $r('app.color.line')
        })
        .onAreaChange((_oldValue: Area, newValue: Area): void => {
          this.onBodyMeasured(newValue.height as number);
        })
      }
      .width('100%')
      .height(this.bodyH)
      // 内容跟随盒高动画的贴合边（官方《显式动画 animateTo》条款：改变宽高的动画，内容直接
      // 跳到最终尺寸；RenderFit 默认 CENTER = 内容始终与组件中心对齐）。默认值下盒高收小
      // 时内容上下两端同时内收（观感"从中间收"）；改 TOP 后内容顶边钉住、只在底边被视口
      // 裁掉 ⇒ 收起 = 展开的镜像（自下而上合拢）。
      .renderFit(RenderFit.TOP)
      .scrollBar(BarState.Off)
      .enableScrollInteraction(false)
      .margin({ top: this.bodyGap })
    }
  }

  // 行内容三分流：
  // 工具行 = 两阶段视口（可展开时才存在）+「展开全部」入口（视口外恒显，开合目标态文案）；
  // 思考行 = 两阶段视口（流式中自动展开 / 点行首开合，回合结束自动收起，console 口径）；
  // 中间结果行 = 正文恒渲染（不可开合），字号墨色走正文档级（renderMidOptions）
  @Builder
  ProcessContent() {
    if (this.message.kind === 'tool') {
      if (this.detailCollapsible()) {
        this.CollapsibleBody()
        Text(this.detailExpanded ? $r('app.string.chat_tool_collapse') : $r('app.string.chat_tool_view_full'))
          .fontSize(UiTokens.fsCaption)
          .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
          .margin({ top: 4 })
          // 显式开合入口与头部行同语义（头部行之外唯一可点开合的位置）
          .onClick((): void => {
            if (this.detailCollapsible()) {
              this.detailExpanded = !this.detailExpanded;
              this.flipBody();
            }
          })
      }
    } else if (this.thinking()) {
      this.CollapsibleBody()
    } else {
      Column() {
        Markdown({ content: this.mdShown, options: this.renderMidOptions() })
          .width('100%')
      }
      .width('100%')
      .padding({ left: 16 })
      .border({ width: { left: 1 }, color: $r('app.color.line') })
      .margin({ top: 6 })
    }
  }

  build() {
    Row() {
      // 行首图标槽：调用中转圈，其余按状态给图标（转圈与图标同一位置交替，不额外占位）
      if (this.running()) {
        LoadingProgress()
          .width(15).height(15)
          .color(this.accentColor())
          .margin({ right: 8, bottom: 2 })
      } else {
        Image(this.leadIcon())
          .width(15).height(15)
          .fillColor(this.leadIconColor())
          .margin({ right: 8 })
      }
      Column() {
        Row() {
          Text(this.leadTitle())
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_secondary'))
            .fontWeight(FontWeight.Medium)
            .layoutWeight(1)
          // 调用中不叠状态标签（对齐 console：isLoading 时不显示 badges，加载态由转圈 + 「处理中...」表达）
          if (this.message.kind === 'tool' && !this.running()) {
            Row({ space: 4 }) {
              Text(this.stateLabel())
                .fontSize(UiTokens.fsCaption)
                .fontColor(this.stateColor())
                .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                .borderRadius(6)
                .backgroundColor($r('app.color.card_bg'))
            }
            .alignItems(VerticalAlign.Center)
          }
          // 行尾开合箭头：思考行（对齐 console OperateCard 头部箭头按钮）与可展开工具行
          // （箭头态 = detailExpanded，点击目标=头部行）
          if (this.thinking() || (this.message.kind === 'tool' && this.detailCollapsible())) {
            Text(this.bodyShown() ? '▲' : '▼')
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .margin({ left: 8 })
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        // 开合点击目标只限头部行（对齐 console OperateCard：仅 header 可点）——正文/详情区
        // 不可点：阅读长思考正文或选中工具输出时，点内容不会把整行收起（整行可点会误触）。
        // 翻转顺序：先翻 detailExpanded 再 flipBody（openTarget 在测量回调里读目标态）
        .onClick((): void => {
          if (this.thinking()) {
            if (this.text().length > 0) {
              // 首次显式开合前，把当前显示态（流式中=自动开）同步进 detailExpanded，
              // 让第一次点击的翻转方向与用户所见一致（所见为开 → 这次点击 = 收）
              if (!this.userToggled) {
                this.detailExpanded = this.bodyOpenTarget();
              }
              this.userToggled = true;
              this.detailExpanded = !this.detailExpanded;
              this.flipBody();
            }
          } else if (this.message.kind === 'tool' && this.detailCollapsible()) {
            this.detailExpanded = !this.detailExpanded;
            this.flipBody();
          }
        })
        this.ProcessContent()
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    // 行首槽垂直对齐：调用中转圈贴**左下角**（思考块长高时转圈随内容下缘走，
    // "还在这里继续想"的视觉锚点；Row 默认 Center 会把高块里的转圈吊在左边中间），
    // 转圈的内外边距 = 卡片内边距（左 12 / 底 8）+ 转圈自身 margin（右 8 / 底 2）；
    // 非运行态图标贴顶（与行首标题齐平，不在高块中间悬空）
    .alignItems(this.running() ? VerticalAlign.Bottom : VerticalAlign.Top)
    // 组框逐行拼装（proc 行只在组展开时存在，恒在组框内；console 口径：Accordion 展开 =
    // 容器边框包住 header + body，body 内缩；7378 = processCard 单卡 + 行间 hairline 分隔）：
    // 左右 1px 边框与组头边框同线相接成整块圆角矩形；顶分隔线只非首行画（首行与组头底边
    // 相接不叠线）；末行画底边框、收底部圆角、给组框留 6vp 底 margin（与组头 top 6 对称）。
    // 内容左右内缩 20 = 12 基线 + 8 缩进（组头图标在 12，子行内容退进 8，包含关系一眼可读）。
    // 思考行在组框内仍是整行灰底嵌套块（对齐 console 嵌套 Accordion = fillTertiary 底），
    // 与工具行（组框面底色 card_surface，与组头同面连续）区分。
    .padding(this.thinking()
      ? { left: 20, right: 20, top: 8, bottom: 8 }
      : { left: 20, right: 20, top: 10, bottom: 10 })
    .borderWidth({
      left: 1,
      right: 1,
      top: this.first ? 0 : 1,
      bottom: this.last ? 1 : 0
    })
    .borderColor($r('app.color.line'))
    .borderRadius(this.last
      ? { bottomLeft: UiTokens.cardRadius, bottomRight: UiTokens.cardRadius }
      : 0)
    .backgroundColor(this.thinking() ? $r('app.color.card_bg') : $r('app.color.card_surface'))
    .margin({ bottom: this.last ? 6 : 0 })
  }
}

// ============ 过程组（单一列表项：组头 + body 盒） ============
// 开合契约（对齐 console LazyAccordion：点组头后点击位置不动、body 向下滑开/向上滑合，
// 弹簧动画，手动与自动都要动画）：组头与 body 盒同在一个 ListItem。
// 此前"组内每行一个 ListItem + 条目增删"的做法里，条目插入/移除是离散布局事件——官方
// 《List》参考对 stackFromEnd 的原文口径是「显示区域内有 ListItem 变高，或有 ListItem
// 插入时，内容上方的 ListItem 往上移动」：开卡瞬间 body 行插入 + 高度 0→全高插值双重触发
// 该重锚，组头被整体推走（真机反馈"一点开被折叠的执行过程，直接往上刷到天上"）。本结构
// 消除插入事件本身：body 盒**常驻** ListItem 内，开合只是其高度在 0↔内容自然高之间插值，
// List 层面没有任何条目增删；高度插值用显式数值 + animateTo（官方 FAQ faqs-arkui-1400：
// 容器高度动画时内容直接到终点状态、容器盒插值）。
// 手动开合"点击位置不动"由 List 的 stackFromEnd regime（atBottom 驱动，见
// ChatDetailPage List 注释）保证：未贴底时 offset 恒定、组头停在按点、body 向下滑开/
// 向上滑合（镜像）；贴底时走官方 stackFromEnd(true) 重锚语义（底边钉住、顶边随内容
// 上移/下移），与流式跟随同观感，开合自镜像。
// 自动展开（活动组首现）不改变 regime——该场景底部跟随才是预期。
// body 盒用**非交互 Scroll 视口**（enableScrollInteraction(false) + 滚动条 Off）：官方
// 《Scroll》参考口径「主轴方向内容大小为所有子组件布局后的总大小」——内容不被视口高度钳制，
// 内层 onAreaChange 恒能测得自然高（普通 Column 盒的显式 height 会把同轴最大约束下发给子组件，
// 0 高盒内恒测得 0，首测永不回正——执行过程卡点不开的结构根因）；交互关闭后 Scroll 不再吃
// 竖直手势，外层 List 照常滚动（此前"划不动"是交互型嵌套 Scroll 吃手势）。内容按自然高平铺、
// 视口高小于内容高时视口裁切——动画余量期间是纯视觉裁剪，动画结束视口高=内容高，无滚动差。
// body 内容**常驻树上**（与 console LazyAccordion 的 destroy-on-close 不同——测量要在 0 高钳制
// 之外进行，内容必须恒在树上；代价是收起态组的 body 驻留渲染，组在 List 可视/缓存窗口内才
// 实例化，成本有界）。
@Component
export struct ProcessGroup {
  @ObjectLink row: ConversationRow;
  @StorageLink('appIsDark') isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 目标态：true = 展开。页面翻行对象的 expanded 后分发器 @Prop 更新，@Watch 接住播动画
  @Prop @Watch('onTargetOpen') targetOpen: boolean = false;
  // 本次开合是否播动画：用户手动展开 / 活动组首次出现时页面置 true；
  // 虚拟化重入（滚出再滚回）不重播 —— 由页面 bodySeen 判定
  @Prop animateOpen: boolean = false;
  // 组头点击（页面翻转 expandedGroups/collapsedGroups 账本；锚定 regime 跟随用户真实位置，
  // 见 ChatDetailPage List 的 stackFromEnd 注释）
  onToggle: () => void = (): void => {};
  // 本组件挂载（页面登记 bodySeen + 消费手动展开标记）
  onBodyMounted: (key: string) => void = (): void => {};
  // 收起动画逐帧高度差（vp，负值 = 正在变矮）：页面据此补偿列表滚动，把组头钉在原位，
  // 使「收起」成为「展开」的镜像（展开 = 组头不动、正文向下滑开；收起 = 正文向上滑合）
  onCollapseStep: (deltaVp: number) => void = (): void => {};

  // 当前动画高度（vp）；0 = 收起。内容自然高由常驻内容 Column 的 onAreaChange 测得
  @State @Watch('onAnimHChanged') animH: number = 0;
  private prevAnimH: number = 0;
  // 收起逐帧上报：只在「目标已收起且 body 处于展开几何」时有效（展开/初始成形不补偿）
  private onAnimHChanged(): void {
    const d: number = this.animH - this.prevAnimH;
    this.prevAnimH = this.animH;
    if (d !== 0 && !this.targetOpen && this.bodyOpened) {
      this.onCollapseStep(d);
    }
  }
  // 内容自然高：内容常驻树上，此值恒为最新测量值；收起不清零——再展开要直接用它播动画
  //（清零后会永远等一个不会再来的"首测"）
  @State measuredH: number = 0;
  // body 盒是否处于展开几何（驱动组头顶盖几何，见 ProcessHeader 的 frameOpen 说明）
  @State frameOpen: boolean = false;

  // 已开且稳定：后续内容变化（流式增长）裸高度跟随，禁 animateTo —— 流式 flush 同帧的
  // 布局变化若被补间，整块"呼吸"闪（与 flushDeltas 的数据写入禁 animateTo 同一铁律）
  private bodyOpened: boolean = false;
  // 动画序号：快速双击时旧动画被重定向，其 onFinish 不得误收尾（误摘内容/误报动画完成）
  private animId: number = 0;
  // 开合动画是否进行中：进行中禁止裸写视口高（裸写会被旧动画终点值覆盖，高度停在旧
  // 测量值），改走 stopAnim 停弹簧 + 裸对齐（行级同构）
  private animRunning: boolean = false;
  // body 盒 Scroll 控制器：仅作文档化句柄，用户手势已禁用（见 build 注释）
  private bodyScroller: Scroller = new Scroller();

  aboutToAppear(): void {
    this.onBodyMounted(this.row.groupKey);
    if (this.targetOpen) {
      // 挂载时即展开（活动组首现 / 虚拟化重入）：组头直接进展开几何，播不播动画由首次
      // 测量时的 followOrOpen 按 animateOpen 决定
      this.frameOpen = true;
    }
  }

  build() {
    Column() {
      ProcessHeader({
        process: this.row.messages, theme: this.theme,
        generating: this.row.generating,
        expanded: this.targetOpen,
        frameOpen: this.frameOpen,
        onToggle: (): void => {
          this.onToggle();
        }
      })
      // body 盒 = 非交互 Scroll 视口（视口高 = 动画高度，0 = 收起，视口自然裁掉内容）；
      // 内层内容恒在树上且不被视口钳制 → onAreaChange 恒测得自然高（见 struct 头注释）
      Scroll(this.bodyScroller) {
        Column() {
          // 正在增长的末行必须直挂 ForEach 之外：ForEach 只在键变化时重跑 itemGenerator，
          // 键稳定（b${idx}）时子组件的 @Prop message 不会更新 → 流式思考停在开头几个字
          //（官方 faqs-arkui-41 键值更新判定；真机复报「只显示前面一段甚至几个字」即此）
          ForEach(this.row.bodyMessages.slice(0,
            this.row.bodyMessages.length > 0 ? this.row.bodyMessages.length - 1 : 0),
            (m: DisplayMessage, idx: number) => {
            ProcessRow({
              message: m, theme: this.theme,
              generating: this.row.generating,
              last: false,
              first: idx === 0,
              rowKey: this.row.groupKey + '#' + idx.toString(),
              onCollapseStep: (d: number): void => {
                this.onCollapseStep(d);
              }
            })
            // 键 = 组内序号（结构键），不用消息 id：服务端每次读会话都重发全新消息 id
            //（两次间隔 2s 的读，187 条 id 全部不同），按 id 做键会让每次快照刷新整组行
            // 销毁重建——用户展开的思考行被重置收起、全部 markdown 重解析闪帧。回合定稿后
            // 组内消息顺序不变（在途只追加尾部），序号键稳定，与顶层行「键只含结构信息」同纪律
          }, (m: DisplayMessage, idx: number): string => `b${idx}`)
          if (this.row.bodyMessages.length > 0) {
            // 末行直挂：父组件重渲染时按常规更新路径把新的 message 传下去（流式逐字增长）
            ProcessRow({
              message: this.row.bodyMessages[this.row.bodyMessages.length - 1],
              theme: this.theme,
              generating: this.row.generating,
              last: true,
              first: this.row.bodyMessages.length === 1,
              rowKey: this.row.groupKey + '#' + (this.row.bodyMessages.length - 1).toString(),
              onCollapseStep: (d: number): void => {
                this.onCollapseStep(d);
              }
            })
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .onAreaChange((_oldValue: Area, newValue: Area): void => {
          const h: number = newValue.height as number;
          if (h > 0 && h !== this.measuredH) {
            this.measuredH = h;
            this.followOrOpen();
          }
        })
      }
      .width('100%')
      .height(this.animH)
      // 同行级 CollapsibleBody：盒高动画期间内容贴合顶边（RenderFit 默认 CENTER 会让内容
      // 上下两端同时内收 = "从中间收"），收起才是展开的镜像
      .renderFit(RenderFit.TOP)
      .scrollBar(BarState.Off)
      .enableScrollInteraction(false)
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  // 测得内容自然高后的推进逻辑：
  // 已开（目标态开）→ 先停掉进行中的弹簧再裸跟随（流式增长，不补间；追赶弹簧追不上
  // 移动目标会裁底，行级同型）；收起动画中 → 不写任其滑到 0；
  // 未开且目标态为开 → 按 animateOpen 决定播弹簧展开动画还是直接成形（重入屏）
  private followOrOpen(): void {
    if (this.measuredH <= 0) {
      return;
    }
    if (this.bodyOpened) {
      if (!this.targetOpen) {
        // 收起动画进行中：不写，任其滑到 0
        return;
      }
      if (this.animRunning) {
        this.stopAnim();
      } else {
        this.animH = this.measuredH;
      }
      return;
    }
    if (!this.targetOpen) {
      // 目标已回收且高度未起：落回 chip 几何。measuredH 保留——内容常驻树上，值仍有效，
      // 再展开时直接用它播动画（清零后会永远等一个不会再来的首测）。
      if (this.animH <= 0) {
        this.frameOpen = false;
      }
      return;
    }
    this.bodyOpened = true;
    if (this.animateOpen) {
      this.startAnim(this.measuredH);
    } else {
      // 重入屏：直接成形，不重播动画
      this.animH = this.measuredH;
    }
  }

  // 目标态翻转（页面 rows() 更新行对象的 expanded → 分发器 @Prop 变化 → 这里接住）
  private onTargetOpen(): void {
    if (this.targetOpen) {
      // 开 / 收起动画途中再展开：组头进展开几何；animateTo 对同属性从当前值重定向，
      // 从收起中途接住继续滑开（点击位置不动由 List 的 stackFromEnd regime 保证，见 struct 头注释）
      this.frameOpen = true;
      if (this.measuredH > 0) {
        // 内容常驻树上且已测得自然高：立即从当前高度滑开；已开稳定期 bodyOpened 保持
        // true，流式增长走裸跟随
        this.bodyOpened = true;
        this.startAnim(this.measuredH);
      }
      // 首测未回（挂载同帧即被点击的极限情形）：等首次测量，followOrOpen 按
      // animateOpen 决定是否播动画
      return;
    }
    // 收起：与展开同曲线滑合；收尾组头回 chip 几何。
    // 内容与 measuredH 都保留：再展开时直接重放动画
    if (this.animH <= 0) {
      this.frameOpen = false;
      return;
    }
    this.animId++;
    const id: number = this.animId;
    this.animRunning = true;
    this.getUIContext().animateTo({
      curve: curves.springMotion(0.4, 1),
      onFinish: (): void => {
        if (id !== this.animId) {
          return;
        }
        this.animRunning = false;
        this.bodyOpened = false;
        // 收起 = 展开的逆序：body 先自下而上滑合到 0，收尾组头再回 chip 几何。
        // 若与高度同帧插值（底圆角归零 + 底 margin 渐开），上下两端会同时内收，
        // 观感即"从中间收"（真机复报）
        this.frameOpen = false;
        // measuredH 保留（内容常驻树上）：再展开时直接重放动画
      }
    }, (): void => {
      // 只动高度：内容自下而上滑合（与展开同一弹簧曲线，方向严格相反）
      this.animH = 0;
    });
  }

  // 组级开合「开」的高度插值（曲线口径见 ProcessRow.startBodyAnim；收走 onTargetOpen
  // 内联动画）。onFinish 带动画 id 判重守卫（被后续动画重定向的旧回调作废），校到最新
  // 自然高（消除残留裁切）
  private startAnim(toH: number): void {
    this.animId++;
    const id: number = this.animId;
    this.animRunning = true;
    this.getUIContext().animateTo({
      curve: curves.springMotion(0.4, 1),
      onFinish: (): void => {
        if (id !== this.animId) {
          return;
        }
        this.animRunning = false;
        this.animH = this.measuredH;
      }
    }, (): void => {
      this.animH = toH;
    });
  }

  // 停掉在跑的组级 frame 动画并裸对齐最新自然高（官方「持续时间为 0 的动画闭包中改变
  // 属性」= 停动画机制；闭包内必须写属性才生效。先自增 id 使旧动画 onFinish 被守卫作废）。
  // 用途：流式增长期间进行中的展开弹簧先停掉再裸跟随——追赶弹簧追不上移动目标，
  // 视口滞后内容 → Scroll 裁底「展示不全」（行级 stopBodyAnim 同构）
  private stopAnim(): void {
    this.animId++;
    this.getUIContext().animateTo({ duration: 0 }, (): void => {
      this.animH = this.measuredH;
    });
    this.animRunning = false;
  }
}

// ============ 行分发器 ============
// 一个 ConversationRow → 一个 ListItem 的子树。行数据经 @ObjectLink 接收：流式期间页面把新数据
// 赋到同一行对象上，本组件原地重渲染（ForEach 键不变 ⇒ 不重建子树，不闪、不打断滚动与展开态）。
@Component
export struct ChatRow {
  @ObjectLink row: ConversationRow;
  @StorageLink('appIsDark') isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @Prop baseUrl: string = '';
  // 过程组展开/收起：展开态由页面决定（组头点击 → 页面翻态）
  onToggleSteps: (key: string) => void = (): void => {};
  // 过程组挂载（页面登记 bodySeen + 消费手动展开标记）
  onBodyMounted: (key: string) => void = (): void => {};
  // 过程组收起逐帧高度差 → 页面补偿滚动锚定（组头钉住 = 展开的镜像）
  onCollapseStep: (deltaVp: number) => void = (): void => {};
  // 选择文本态（页面单一事实源 selectingId，见 ChatDetailPage）：本页行是否在选择态
  @Prop selecting: boolean = false;
  // 行内「选择文本」→ 上报页面按行键置位（工具栏完成 / 点气泡外 / 返回手势都由页面直接清退）
  onSelectingChange: (key: string, on: boolean) => void = (): void => {};

  build() {
    Column() {
      if (this.row.kind === 'user') {
        UserRow({
          message: this.row.messages[0], theme: this.theme, baseUrl: this.baseUrl,
          selecting: this.selecting,
          onRequestSelect: (): void => {
            this.onSelectingChange(this.row.key, true);
          }
        })
      } else if (this.row.kind === 'message') {
        // 空内容的消息行不出卡（数据层已过滤，这里再兜一层：卡底色在深色下会把空行显成一张空白卡）
        if (rowHasVisibleContent(this.row.messages[0])) {
          MessageRow({
            message: this.row.messages[0], streaming: this.row.pending, last: this.row.last,
            theme: this.theme, baseUrl: this.baseUrl,
            selecting: this.selecting,
            onRequestSelect: (): void => {
              this.onSelectingChange(this.row.key, true);
            }
          })
        }
      } else if (this.row.kind === 'stepsGroup') {
        ProcessGroup({
          row: this.row,
          theme: this.theme,
          targetOpen: this.row.expanded === true,
          animateOpen: this.row.animateOpen === true,
          onToggle: (): void => {
            this.onToggleSteps(this.row.groupKey !== undefined ? this.row.groupKey : '');
          },
          onBodyMounted: (k: string): void => {
            this.onBodyMounted(k);
          },
          onCollapseStep: (d: number): void => {
            this.onCollapseStep(d);
          }
        })
      } else if (this.row.kind === 'media') {
        MediaRow({ parts: this.row.parts, baseUrl: this.baseUrl,
          rowKey: this.row.key
        })
      } else {
        PendingRow()
      }
    }
    .width('100%')
    .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
  }
}
