/*
 * 社区文章详情 —— 移植 PR #7378 app/community/[id].tsx：
 *   文章卡（类型/问答状态、标题、作者、封面、正文、标签、浏览/点赞/评论统计）+ 全部评论列表
 *   + 底部互动条（评论输入、发送、点赞、分享）。
 * 正文取 body_text（纯文本，可选中复制）——与 7378 同口径；body_html 不在这里渲染。
 * 键盘避让：官方 KeyboardAvoidMode.NONE + avoidAreaChange 自让底部（与聊天页同一套）。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { common } from '@kit.AbilityKit';
import { window, KeyboardAvoidMode, curves, uiMaterial } from '@kit.ArkUI';
import { systemShare } from '@kit.ShareKit';
import { uniformTypeDescriptor as utd } from '@kit.ArkData';
import { BusinessError } from '@kit.BasicServicesKit';
import {
  CommunityComment, CommunityArticleDetail, getCommunityArticle, getCommunityComments,
  createCommunityComment, likeCommunityArticle, communityArticleUrl, communityInitials,
  formatCommunityDate, normalizeCommunityText, removeCommunityEmoji
} from '../services/CommunityService';
import { getPlatformAccessToken } from '../services/PlatformSession';
import { PlatformLoginParam } from '../components/CommunityTab';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens, pxPerVp } from '../theme/UiTokens';
import { areaWidthOf, BP_LG, CONTENT_MAX } from '../theme/Breakpoints';
import { pushRoute, popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { blendHex } from '../theme/Accent';
import { sampleFabBackdropIsDark, FabSampleRegionVp } from '../theme/FabContrast';
import { t } from '../services/I18n';

// 底部系统导航区保底值（vp）
const NAV_FALLBACK_INSET: number = 12;
// 底部互动条的渐变模糊：最大半径（fractionStops 末段比例见使用处）
const DOCK_BLUR_RADIUS: number = 40;
// 悬浮互动条离底间距（vp）；栏体高度随输入行高实测联动（dockCapsuleH，与聊天页同口径）
const DOCK_BOTTOM_MARGIN: number = 12;

// 「回到顶部」按钮：直径 / 进出场过渡 / 出现阈值（距顶滚动超过该值才出现）——
// 与聊天页「回到底部」按钮同一套规格（同直径、同过渡时长、同材质载体），判据反过来
const BACK_TOP_SIZE: number = 36;
const BACK_TOP_ANIM_MS: number = 200;
const BACK_TOP_THRESHOLD: number = 300;

// 评论正文的一段：url = true 表示这段是链接（单独上色 + 可点）
interface LinkSpan {
  text: string;
  url: boolean;
}

@Builder
export function CommunityArticlePageBuilder(_name: string, param: Object) {
  CommunityArticlePage({ params: param })
}

@Component
export struct CommunityArticlePage {
  params: Object = new Object();
  @State detail: CommunityArticleDetail | null = null;
  @State comments: CommunityComment[] = [];
  @State loading: boolean = true;
  @State error: string = '';
  @State commentText: string = '';
  @State submitting: boolean = false;
  @State keyboardInset: number = 0;
  // 输入态磨砂背板级别（0–1 过渡值）：0 = 系统沉浸光感（基础材质透出），1 = 磨砂背板全显。
  // 系统材质档位切换无动画接口 → 基础材质常驻，背板做 opacity 交叉淡变（背板在 TabContent
  // 的 Stack 内、材质之下、列表之上，见 build 的「磨砂背板」），与聊天页 composer 同机制
  @State kbFrost: number = 0;
  @State navInset: number = NAV_FALLBACK_INSET;
  @StorageLink('appIsDark') isDark: boolean = false;
  // 底部互动条四键的自绘按压态（-1 = 未按；与聊天页 + 键同一机制：缩放 + 点光源，静止无边框）
  @State dockPressed: number = -1;
  // 输入行内容区高度（vp）：文本换行实测驱动（与聊天页 inputBlockH 同机制）——
  // 单行 = 基线 50，每多一行加一个实测行高，封顶 5 行（maxLines(5, SCROLL)：超出在框内滚动）
  @State commentBlockH: number = UiTokens.chatComposerBarInner;
  // 评论框实测文本宽度（onAreaChange 缓存）：measureTextSize 的 constraintWidth
  private commentFieldW: number = 0;
  // 键盘弹起态：驱动点赞/分享缩放消失（applyKeyboardFrost 与背板淡变同源）
  @State dockKb: boolean = false;
  // 「回到顶部」按钮呈现态（正文距顶超过阈值才出现，见 syncBackTop）
  @State showBackTop: boolean = false;
  // 「回到顶部」按钮字色档位：底下内容深（图片/深色模式）→ 白字，否则主题深字
  // （采样翻转，见 requestFabContrast；字色插值由按钮既有的 .animation 完成）
  @State fabDark: boolean = false;
  private fabSampleBusy: boolean = false;
  private fabSampleTimer: number = -1;
  private fabHostWVp: number = 0;
  private fabHostHVp: number = 0;
  // 正文滚动控制器：窄屏单 List 与宽屏正文列互斥实例化，同一控制器任一时刻只绑一个
  private articleScroller: Scroller = new Scroller();
  // 评论框控制器：长按系统选择菜单点"复制"后把光标归位到选区末端以取消选中态
  private taController: TextAreaController = new TextAreaController();
  // 最近一次选区末端（onTextSelectionChange 记录）
  private taSelEnd: number = 0;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  private articleId: string = '';
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  private themeListener: ThemeListener | null = null;
  private kbWindow: window.Window | null = null;
  private kbListener: ((data: window.AvoidAreaOptions) => void) | null = null;
  private prevKeyboardAvoidMode: KeyboardAvoidMode | null = null;
  private dockLatch: PressLatch = new PressLatch();

  private onDockPress(idx: number, e: TouchEvent): void {
    pressTouch(this.getUIContext(), e, this.dockLatch, (v: boolean): void => {
      this.dockPressed = v ? idx : -1;
    });
  }

  // 大屏（平板/电脑）横屏判定：官方《页面布局场景》的横向断点；与会话页分栏同一判据
  //（宽度 ≥ 840vp 且横屏），同一设备上两处行为的切换条件保持一致
  @State pageW: number = 0;
  @State pageH: number = 0;

  private isWide(): boolean {
    return this.pageW >= BP_LG && this.pageW > this.pageH;
  }

  // 评论区栏宽：官方侧边栏口径 lg 档 = 屏宽的 40%，夹在 320–600vp 之间
  private commentsPaneW(): number {
    return Math.min(600, Math.max(320, Math.round(this.pageW * 0.4)));
  }

  // 「回到顶部」出现判定 = 正文距顶滚动距离超过阈值（聊天页「回到底部」按钮用 isAtEnd，
  // 这里是它的反向判据：离顶足够远才出现，回顶后隐藏）
  private syncBackTop(): void {
    const y: number = this.articleScroller.currentOffset().yOffset as number;
    const show: boolean = y > BACK_TOP_THRESHOLD;
    if (show !== this.showBackTop) {
      this.showBackTop = show;
    }
  }

  // ──「回到顶部」按钮字体对比度采样（机制见 theme/FabContrast.ets）──
  // 按钮浮在正文/评论区之上：底下是深图/深色模式时深字看不见。只在滚动停稳（onScrollStop）、
  // 内容更新、键盘升降、主题切换后采样（带去抖与在途守卫），翻转 fabDark；不逐帧。
  private fabGlyphColor(): ResourceColor {
    return this.fabDark ? Color.White : $r('app.color.text_primary_strong');
  }

  private requestFabContrast(delay: number): void {
    if (this.fabSampleTimer >= 0) {
      clearTimeout(this.fabSampleTimer);
      this.fabSampleTimer = -1;
    }
    this.fabSampleTimer = setTimeout((): void => {
      this.fabSampleTimer = -1;
      this.doFabContrast();
    }, delay);
  }

  private doFabContrast(): void {
    if (this.fabSampleBusy || this.fabHostWVp <= 0 || this.fabHostHVp <= 0) {
      return;
    }
    this.fabSampleBusy = true;
    sampleFabBackdropIsDark(this.getUIContext(), 'articleBackTopHost',
      this.fabSampleRegion(), this.fabHostWVp, this.fabHostHVp)
      .then((dark: boolean | null): void => {
        if (dark !== null && dark !== this.fabDark) {
          this.fabDark = dark;
        }
      })
      .catch((): void => {
        // 采样失败（组件离屏等）：保持当前字色
      })
      .then((): void => {
        this.fabSampleBusy = false;
      });
  }

  // 采样区域 = 以按钮中心为心、两倍直径的盒（按钮边距：右 16 / 底 = 互动条高 + 12 + 10）
  private fabSampleRegion(): FabSampleRegionVp {
    const bottom: number = DOCK_BOTTOM_MARGIN + this.dockCapsuleH() + 10;
    return {
      x: this.fabHostWVp - UiTokens.pageHMargin - BACK_TOP_SIZE * 1.5,
      y: this.fabHostHVp - bottom - BACK_TOP_SIZE * 1.5,
      w: BACK_TOP_SIZE * 2,
      h: BACK_TOP_SIZE * 2
    };
  }

  // 悬浮互动条宽度（vp）：与正文列同一限宽口径（min(窗口宽, 840) − 两侧水平边距，
  // 与会话页 capsuleBarW() 同源）；窄屏 = 手机全宽形态（376vp → 344，与历史真机实测一致）；
  // 宽屏跟随窗口限宽，不再保持手机窄宽居中
  private dockBarW(): number {
    if (this.pageW <= 0) {
      return 344; // 首次 onAreaChange 前回落手机基线宽
    }
    const colW: number = Math.min(this.pageW, CONTENT_MAX);
    return Math.max(colW - UiTokens.pageHMargin * 2, 240);
  }

  private onPageArea = (_old: Area, now: Area): void => {
    this.pageW = areaWidthOf(now, this.pageW);
    const h: number = typeof now.height === 'number' ? now.height as number : 0;
    if (h > 0 && Math.abs(h - this.pageH) > 0.5) {
      this.pageH = h;
    }
  };

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const id: Object = rec['articleId'];
    this.articleId = typeof id === 'string' ? id as string : '';
    const st: Object = rec['stack'];
    this.stack = (st === undefined || st === null) ? null : st as NavPathStack;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
      // 主题（深浅色）切换：底下内容整幅换色，重渲染后补采按钮字色档位
      this.requestFabContrast(350);
    };
    ThemeManager.get().subscribe(this.themeListener);
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
      this.fabDark = this.isDark;
    });
    this.setupKeyboard();
    this.load();
  }

  aboutToDisappear(): void {
    // 待发的采样定时器随组件销毁清掉，避免回调落到已销毁组件上
    if (this.fabSampleTimer >= 0) {
      clearTimeout(this.fabSampleTimer);
      this.fabSampleTimer = -1;
    }
    if (this.kbWindow !== null && this.kbListener !== null) {
      this.kbWindow.off('avoidAreaChange', this.kbListener);
      this.kbWindow = null;
      this.kbListener = null;
    }
    const kb: KeyboardAvoidMode | null = this.prevKeyboardAvoidMode;
    if (kb !== null) {
      this.getUIContext().setKeyboardAvoidMode(kb);
      this.prevKeyboardAvoidMode = null;
    }
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
  }

  private setupKeyboard(): void {
    this.prevKeyboardAvoidMode = this.getUIContext().getKeyboardAvoidMode();
    window.getLastWindow(getContext(this)).then((w: window.Window): void => {
      this.kbWindow = w;
      const navPx: number = w.getWindowAvoidArea(window.AvoidAreaType.TYPE_NAVIGATION_INDICATOR)
        .bottomRect.height;
      this.navInset = navPx > 0 ? navPx / pxPerVp() : NAV_FALLBACK_INSET;
      const cb = (data: window.AvoidAreaOptions): void => {
        if (data.type === window.AvoidAreaType.TYPE_KEYBOARD) {
          const inset: number = data.area.bottomRect.height / pxPerVp();
          this.getUIContext().animateTo({ curve: curves.springMotion(0.4, 0.68) }, (): void => {
            this.keyboardInset = inset;
          });
          // 键盘升降只驱动输入条背板的淡入淡出（见 applyKeyboardFrost）；布局避让走
          // keyboardInset 底部让位，两套互不干扰
          this.applyKeyboardFrost(inset > 14);
        }
      };
      this.kbListener = cb;
      w.on('avoidAreaChange', cb);
      // 同步输入态材质到窗口**当前**键盘避让区（兜住进页时键盘已弹起等事件漏接的时点）
      w.getAvoidArea(window.AvoidAreaType.TYPE_KEYBOARD).then((a: window.AvoidArea): void => {
        this.applyKeyboardFrost(a.bottomRect.height / pxPerVp() > 14);
      });
    });
    this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.NONE);
  }

  // 键盘弹出时互动条磨砂背板渐显、收起时渐隐回系统沉浸光感。
  // 官方口径：系统材质（ImmersiveMaterial）档位切换无动画接口（瞬切），且材质层在
  // **backgroundColor** 之上、背景色与 opacity 均为可动画属性（《属性动画概述》）→
  // 基础材质常驻，输入态在与胶囊同几何的背板上做 opacity 交叉淡变，材质的实时磨砂
  // 模糊直接作用于背板 → 底色均匀且保留磨砂质感；收起再淡出。与聊天页 composer 同款。
  // 同一动画里驱动 dockKb：键盘弹起时点赞/分享缩放消失、输入区撑满（见 dockBar）
  private applyKeyboardFrost(up: boolean): void {
    const changed: boolean = up !== this.dockKb;
    this.getUIContext().animateTo({ duration: 260, curve: Curve.EaseInOut }, (): void => {
      this.kbFrost = up ? 1 : 0;
      this.dockKb = up;
    });
    // 键盘升降 → 互动条高度变 → 「回到顶部」按钮上移，落脚处内容换了，补采一次
    if (changed) {
      this.requestFabContrast(300);
    }
  }

  // 评论是否可发送（非空白）
  private canComment(): boolean {
    return this.commentText.trim().length > 0;
  }

  // 互动条栏体高度（vp）= 输入内容区实际高度 + 上下 chrome（与聊天页 capsuleBarH 同公式）；
  // 内容长高时栏体同步长高，Tabs barHeight / 磨砂背板同值联动
  private dockCapsuleH(): number {
    const inner: number = Math.max(this.commentBlockH, UiTokens.chatComposerBarInner);
    return inner + (UiTokens.chatComposerHeight + 1 - UiTokens.chatComposerBarInner);
  }

  // 按文本换行实测算输入内容区高度（每次输入变化 / 宽度变化时调用）。
  // 与聊天页 refreshDraftH 同机制：带约束宽度的 measureTextSize 实测行数，
  // 单行 = 基线 50（首帧不跳变），每多一行加一个实测行高，封顶 5 行（maxLines(5, SCROLL)
  // 同口径：超出在框内滚动，输入不受阻）；160ms EaseOut 过渡让栏体/背板/列表留白一次跟手
  private refreshCommentH(value: string): void {
    const base: number = UiTokens.chatComposerBarInner;
    if (value.length === 0 || this.commentFieldW <= 0) {
      if (this.commentBlockH !== base) {
        this.commentBlockH = base;
      }
      return;
    }
    const oneVal: Length | undefined = this.getUIContext().getMeasureUtils().measureTextSize({
      textContent: '测',
      constraintWidth: this.commentFieldW,
      fontSize: UiTokens.fsBody
    }).height;
    const totalVal: Length | undefined = this.getUIContext().getMeasureUtils().measureTextSize({
      textContent: value,
      constraintWidth: this.commentFieldW,
      fontSize: UiTokens.fsBody
    }).height;
    const oneVp: number = typeof oneVal === 'number' ? this.getUIContext().px2vp(oneVal) : 0;
    const totalVp: number = typeof totalVal === 'number' ? this.getUIContext().px2vp(totalVal) : 0;
    const per: number = oneVp > 0 ? oneVp : totalVp;
    const lines: number = per > 0 ? Math.max(1, Math.round(totalVp / per)) : 1;
    const capped: number = Math.min(lines, 5);
    const next: number = base + per * (capped - 1);
    if (Math.abs(next - this.commentBlockH) < 0.5) {
      return;
    }
    this.getUIContext().animateTo({ duration: 160, curve: Curve.EaseOut }, (): void => {
      this.commentBlockH = next;
    });
  }

  private accent(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private async load(): Promise<void> {
    if (this.articleId.length === 0) {
      this.loading = false;
      this.error = t($r('app.string.community_article_error_copy'));
      return;
    }
    this.loading = true;
    this.error = '';
    try {
      const detail: CommunityArticleDetail = await getCommunityArticle(this.articleId);
      const comments: CommunityComment[] = (await getCommunityComments(this.articleId)).items;
      this.detail = detail;
      this.comments = comments;
      this.requestFabContrast(400);
    } catch (e) {
      this.error = (e as Error).message;
    } finally {
      this.loading = false;
    }
  }

  private share(): void {
    const detail: CommunityArticleDetail | null = this.detail;
    if (detail === null) {
      return;
    }
    const url: string = communityArticleUrl(detail.article.id);
    try {
      const data: systemShare.SharedData = new systemShare.SharedData({
        utd: utd.UniformDataType.TEXT,
        content: `${detail.article.title}\n${url}`,
        title: detail.article.title
      });
      const controller: systemShare.ShareController = new systemShare.ShareController(data);
      controller.show(this.getUIContext().getHostContext() as common.UIAbilityContext, {
        selectionMode: systemShare.SelectionMode.SINGLE,
        previewMode: systemShare.SharePreviewMode.DETAIL
      }).catch((): void => {
      });
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({ message: url });
    }
  }

  // 未登录：提示后跳 Platform 登录页（对齐 7378 promptPlatformLogin）
  private promptPlatformLogin(): void {
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.community_login_required_title')),
      message: t($r('app.string.community_login_required_copy')),
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {
        }
      },
      secondaryButton: {
        value: t($r('app.string.community_login_action')),
        action: (): void => {
          const stack: NavPathStack | null = this.stack;
          if (stack !== null) {
            const param: PlatformLoginParam = { returnTo: '', stack: stack };
            pushRoute(stack, 'platform-login', param);
          }
        }
      }
    });
  }

  private async like(): Promise<void> {
    const detail: CommunityArticleDetail | null = this.detail;
    if (detail === null) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const token: string = await getPlatformAccessToken(ctx);
    if (token.length === 0) {
      this.promptPlatformLogin();
      return;
    }
    try {
      const updated = await likeCommunityArticle(ctx, detail.article.id);
      detail.article.liked = updated.liked;
      detail.article.likeCount = updated.likeCount;
      this.detail = detail;
    } catch (e) {
      this.getUIContext().showAlertDialog({
        title: t($r('app.string.community_like_failed_title')),
        message: (e as Error).message
      });
    }
  }

  private async submitComment(): Promise<void> {
    const detail: CommunityArticleDetail | null = this.detail;
    if (detail === null || this.commentText.trim().length === 0 || this.submitting) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const token: string = await getPlatformAccessToken(ctx);
    if (token.length === 0) {
      this.promptPlatformLogin();
      return;
    }
    this.submitting = true;
    try {
      const comment: CommunityComment =
        await createCommunityComment(ctx, detail.article.id, this.commentText);
      const next: CommunityComment[] = [comment];
      for (const item of this.comments) {
        next.push(item);
      }
      this.comments = next;
      detail.article.commentCount = detail.article.commentCount + 1;
      this.detail = detail;
      this.commentText = '';
    } catch (e) {
      this.getUIContext().showAlertDialog({
        title: t($r('app.string.community_comment_failed')),
        message: (e as Error).message
      });
    } finally {
      this.submitting = false;
    }
  }

  build() {
    HdsNavDestination() {
      Column() {
        if (this.loading) {
          this.stateCenter(false)
        } else if (this.error.length > 0 || this.detail === null) {
          this.stateCenter(true)
        } else {
          // 底部输入条 = ArkUI Tabs 的「悬浮页签栏」（与聊天页 composer 同一机制）：
          // 内容区（标题栏/End 位置 TabBar/弹窗之外）没有可直接上沉浸材质的 API，唯一官方路径就是
          // Tabs(barPosition=End) + barOverlap + barFloatingStyle.systemMaterial（见
          // 《沉浸光感典型场景》底部 Tabs 悬浮示例）。barFloatingStyle 里的交互材质同时给到
          // 按压弹性与手指跟随光；键盘避让沿用 KeyboardAvoidMode.NONE + avoidAreaChange。
          Tabs({ barPosition: BarPosition.End, index: 0 }) {
            TabContent() {
            // 分栏（官方《页面布局场景》侧边栏；图文详情 + 评论区即其典型场景）：
            // 左正文、右评论各自独立滚动，底部互动条仍通栏。
            // 内容套进与磨砂背板同级的 Stack（背板在系统材质之下、列表之上）
            Stack({ alignContent: Alignment.Bottom }) {
            if (this.isWide()) {
              Row() {
                List({ scroller: this.articleScroller }) {
                  this.articleItems()
                  this.dockSpacerItem()
                }
                .layoutWeight(1)
                .height('100%')
                .scrollBar(BarState.Off)
                .onDidScroll((): void => {
                  this.syncBackTop();
                })
                .onScrollStop((): void => {
                  // 滚动停稳 → 补采一次按钮脚下深浅（带去抖，不在滚动过程逐帧采）
                  this.requestFabContrast(150);
                })
                .linearGradientBlur(DOCK_BLUR_RADIUS, {
                  fractionStops: [[0, 0], [0, 0.88], [1, 1]],
                  direction: GradientDirection.Bottom
                })
                Column().width(1).height('100%').backgroundColor($r('app.color.line'))
                Column() {
                  // 右栏顶部让开沉浸标题栏带（与正文列首项 spacer 同口径）
                  Column().width('100%').height(UiTokens.topInset)
                  this.commentsHeaderRow()
                  List() {
                    this.commentItems()
                  }
                  .layoutWeight(1)
                  .width('100%')
                  .scrollBar(BarState.Off)
                  // 宽屏下「回到顶部」按钮浮在评论区这一列上：它停稳同样要补采
                  .onScrollStop((): void => {
                    this.requestFabContrast(150);
                  })
                  .linearGradientBlur(DOCK_BLUR_RADIUS, {
                    fractionStops: [[0, 0], [0, 0.88], [1, 1]],
                    direction: GradientDirection.Bottom
                  })
                }
                .width(this.commentsPaneW())
                .height('100%')
              }
              .width('100%')
              .height('100%')
              .alignItems(VerticalAlign.Top)
            } else {
            List({ scroller: this.articleScroller }) {
              ListItem() {
                this.articleBlock()
              }
                  ListItem() {
                    this.commentsHeaderRow()
                  }
                  this.commentItems()
            }
            .width('100%')
            .height('100%')
            .scrollBar(BarState.Off)
            .onDidScroll((): void => {
              this.syncBackTop();
            })
            .onScrollStop((): void => {
              // 滚动停稳 → 补采一次按钮脚下深浅（带去抖，不在滚动过程逐帧采）
              this.requestFabContrast(150);
            })
            // 渐变模糊挂在**滚动内容自身**（官方：linearGradientBlur 按位置逐段给半径）——
            // 评论往上滚到底部互动条之下时被渐隐；fractionStops = [[半径倍率, 位置], …]，
            // Bottom 方向下位置 0 = 顶、1 = 底；此处只在末端起糊（dock 那一段）
            // 起糊位置压到列表末端 ~12%（≈ 悬浮条带自身高度）：正文仍在清晰区，
            // 只有落到条带之下的评论被渐隐 —— 起糊过早会把正文也糊掉
            .linearGradientBlur(DOCK_BLUR_RADIUS, {
              fractionStops: [[0, 0], [0, 0.88], [1, 1]],
              direction: GradientDirection.Bottom
            })

            .width('100%')
            .height('100%')
            }
            // 磨砂背板（与聊天页 composer 同机制）：在系统材质之下、列表之上——栏体材质的
            // 实时磨砂模糊直接作用于背板，底色均匀且保留磨砂质感。
            // 为何不塞进 tabBar：框架把 tabBar 内容钳到胶囊内容区（真机实测四周内收），
            // 栏内覆盖层到不了胶囊边缘——后面亮内容从边缘漏出、覆盖层直边切亮边显方块。
            // 几何与胶囊一致（同宽/同高/同圆角/同离底间距）；opacity 随键盘升降 260ms
            // 淡入淡出（applyKeyboardFrost）：基础材质常驻、输入态背板交叉淡入；
            // hitTest None 不挡列表滚动。高度随输入长高（dockCapsuleH，与聊天页背板同口径）
            Column()
              .width(this.dockBarW())
              .height(this.dockCapsuleH())
              .borderRadius(this.dockCapsuleH() / 2)
              .backgroundColor($r('app.color.composer_frost_bg'))
              .margin({ bottom: DOCK_BOTTOM_MARGIN })
              .opacity(this.kbFrost)
              .hitTestBehavior(HitTestMode.None)
            // 「回到顶部」：浮于右下角、让开悬浮互动条（底距 = 条体高 + 离底间距 + 呼吸边）；
            // 隐藏态 = 下移自身高度 + 透明 + 不接收点击，进出场 200ms（与聊天页「回到底部」
            // 按钮同一规格，判据反向，见 syncBackTop）。载体用 Toggle(ToggleType.Button)：
            // 内容区里 Button 挂组件级 systemMaterial 不生效（官方口径 + 真机实证）
            Toggle({ type: ToggleType.Button, isOn: false }) {
              SymbolGlyph($r('sys.symbol.arrow_up'))
                .fontSize(20)
                // 字色随按钮脚下内容明暗采样切换（fabDark，见 requestFabContrast）；
                // 200ms 插值由下方既有 .animation 覆盖
                .fontColor([this.fabGlyphColor()])
            }
            .width(BACK_TOP_SIZE)
            .height(BACK_TOP_SIZE)
            .borderRadius(BACK_TOP_SIZE / 2)
            .backgroundColor(Color.Transparent)
            .systemMaterial(new uiMaterial.ImmersiveMaterial({
              style: uiMaterial.ImmersiveStyle.THIN,
              interactive: true,
              lightEffect: { color: this.theme.accent }
            }))
            .selectedColor(Color.Transparent)
            .shadow({ radius: 12, color: '#40000000', offsetX: 0, offsetY: 2 })
            .margin({ right: UiTokens.pageHMargin, bottom: DOCK_BOTTOM_MARGIN + this.dockCapsuleH() + 10 })
            .opacity(this.showBackTop ? 1 : 0)
            .translate({ y: this.showBackTop ? 0 : BACK_TOP_SIZE })
            .hitTestBehavior(this.showBackTop ? HitTestMode.Default : HitTestMode.None)
            .animation({ duration: BACK_TOP_ANIM_MS, curve: Curve.EaseOut })
            .onChange((isOn: boolean): void => {
              this.articleScroller.scrollToIndex(0, true, ScrollAlign.START);
              this.syncBackTop();
            })
            }
            .width('100%')
            .height('100%')
            // id 供字体对比度采样（theme/FabContrast）：截本 Stack 最近一帧 → 读按钮脚下区域判深浅
            .id('articleBackTopHost')
            .onAreaChange((_old: Area, now: Area): void => {
              const w: number = typeof now.width === 'number' ? now.width as number : 0;
              const h: number = typeof now.height === 'number' ? now.height as number : 0;
              if (w === this.fabHostWVp && h === this.fabHostHVp) {
                return;
              }
              const first: boolean = this.fabHostWVp <= 0;
              this.fabHostWVp = w;
              this.fabHostHVp = h;
              if (first && w > 0) {
                this.requestFabContrast(500);
              }
            })
            }
            .tabBar(this.dockBar())
          }
          .barOverlap(true)
          // 单页不滑动：避免"拖动一半"这种中间态（与聊天页一致）
          .scrollable(false)
          // 栏体高度与聊天页同一联动：dockCapsuleH() = 输入内容区实测高 + 上下 chrome 9vp
          //（单行时 = 基线 59 = chatComposerHeight + 1），输入长高时栏体/背板/列表留白同步长高
          .barHeight(this.dockCapsuleH())
          .barFloatingStyle({
            // 悬浮栏默认按内容自适应宽度（会把输入框压窄）→ 显式给宽度（dockBarW()：
            // 窄屏 = 手机全宽 344vp + 两侧 16vp，宽屏随窗口限宽，与正文列同口径）。
            // 真机实测：barWidth 小于可用宽度时栏体**水平居中**（248 档居中在 [64,312]）
            // → 胶囊两侧无空间放外部按钮，点赞/分享改为行内输入框右侧（见 dockBar）
            barWidth: { smallBarWidth: this.dockBarW(), mediumBarWidth: this.dockBarW(), largeBarWidth: this.dockBarW() },
            barSideMargin: UiTokens.pageHMargin,
            // 栏体遮罩默认近黑：按压/拖动时栏体形变会露出遮罩（表现为黑边）→ 置透明
            maskColor: Color.Transparent,
            barBottomMargin: DOCK_BOTTOM_MARGIN,
            // 按压光由栏材质 lightEffect 承载（官方口径：为"按压、触摸"提供主题色光反馈）：
            // 按压任一按键照出 accent 柔光；键体自身不挂点光源（预设光参在键外留方形轮廓，
            // 真机实测"圆形外面有个方形"）；保留 interactive 交互形变
            systemMaterial: new uiMaterial.ImmersiveMaterial({
              style: uiMaterial.ImmersiveStyle.THIN,
              interactive: true,
              lightEffect: { color: this.accent() }
            })
          })
          .width('100%')
          .layoutWeight(1)
        }
      }
      .width('100%')
      .height('100%')
      .padding({ bottom: this.keyboardInset })
      .backgroundColor($r('app.color.page_bg'))
      .alignItems(HorizontalAlign.Start)
      .onAreaChange(this.onPageArea)
    }
    // 内容也扩到安全区外（布局级，与 expandSafeArea 同设时优先）：二级页四边都扩，
    // 否则下端/左右两侧会露出窗口底色（页面底部输入条一带表现为黑带）
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM],
      [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM, LayoutSafeAreaEdge.START, LayoutSafeAreaEdge.END])
    // 二级页转场：整页自右水平覆盖进来（退出滑回右侧）——见 services/NavPush.slideCoverTransition。
    // 系统默认档在分栏下动的是"内容区左边缘 0 → 分栏位"，观感从左侧摊过来（判"方向反了"），
    // 故改用官方 customTransition（NavDestinationTransitionDelegate）自己定方向。
    .customTransition((op: NavigationOperation, isEnter: boolean)
      : Array<NavDestinationTransition> | undefined => slideCoverTransition(op, isEnter,
        (v: string): void => { this.pageX = v; }))
    .translate({ x: this.pageX })
    // 返回键：系统侧滑与标题栏左上角返回按钮都投递到当前 NavDestination 的 onBackPressed
    //（官方 FAQ faqs-arkui-1117：该回调"支持拦截系统侧滑及 NavDestination 标题栏的返回事件"）；
    // 没挂它时标题栏返回按钮点了没有反应 —— 这里自己出栈并消费。
    .onBackPressed((): boolean => popSelfOnBack(this.stack))
    .titleBar({
      style: {
        scrollEffectOpts: {
          // enableScrollEffect = false：官方口径「不随内容区滚动动态生效标题栏样式，仅生效 originalStyle」，
          // 且 GRADIENT_BLUR 下「直接生效模糊。此方式适用于列表型非沉浸式场景」。
          // 为什么不用 true：为 true 时样式会在 originalStyle→scrollEffectStyle 之间随滚动**插值**，
          // 上滚过程出现"先变暗、再慢慢回到主题色"的过渡观感（反复被报的"往上滑突然变黑然后慢慢
          // 出现主题色"）；关掉后底色/模糊只有一个状态，结构上不可能再出现滚动时变色。
          // 标题栏随滚动收起（titleMode FREE）与内容穿过时的模糊都不受影响。
          enableScrollEffect: false,
          scrollEffectType: ScrollEffectType.GRADIENT_BLUR
        },
        // blurStrategy 用 ENABLE 而不是 ADAPTIVE：官方口径 ADAPTIVE「根据系统策略调整…只有精美档位
        // 配置能够生效模糊效果」—— 系统策略落在轻柔/流畅档时标题栏模糊整块不生效，内容滚过时就露出
        // 未模糊的暗色内容（观感即"往上滑突然变黑"）；ENABLE 恒生效，观感才稳定。
        blurStrategy: BlurStrategy.ENABLE,
        // maskExtraHeight 必须写在生效态（enableScrollEffect=false 时只生效 originalStyle），
        // 否则退回平台默认外扩（实测比标题栏底边多约 56vp），在工具条下方留下中性灰带。
        originalStyle: {
          backgroundStyle: { blurRadius: 12.0, maskExtraHeight: 0.0, backgroundColor: this.accent() }
        },
        scrollEffectStyle: {
          backgroundStyle: { blurRadius: 12.0, backgroundColor: this.accent() }
        },
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: hdsMaterial.MaterialLevel.ADAPTIVE
        }
      },
      content: {
        title: { mainTitle: $r('app.string.community_detail_title') }
      },
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
    .expandSafeArea([SafeAreaType.SYSTEM],
      [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
  }

  @Builder
  stateCenter(isError: boolean) {
    Column() {
      if (isError) {
        Column() {
          Image($r('app.media.refresh_cw'))
            .width(27).height(27)
            .fillColor(this.accent())
        }
        .width(54)
        .height(54)
        .borderRadius(17)
        .backgroundColor($r('app.color.card_bg'))
        .justifyContent(FlexAlign.Center)
        .margin({ bottom: 12 })
        Text($r('app.string.community_article_error_title'))
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary_strong'))
        Text(this.error.length > 0
          ? this.error : t($r('app.string.community_article_error_copy')))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_tertiary'))
          .textAlign(TextAlign.Center)
          .lineHeight(19)
          .margin({ top: 6 })
        Text($r('app.string.community_reload'))
          .fontSize(UiTokens.fsSecondary)
          .fontWeight(FontWeight.Medium)
          .fontColor(Color.White)
          .height(44)
          .padding({ left: 24, right: 24 })
          .borderRadius(12)
          .backgroundColor(this.accent())
          .margin({ top: 16 })
          .onClick((): void => {
            this.load();
          })
      } else {
        LoadingProgress()
          .width(28)
          .height(28)
          .color(this.accent())
          .margin({ bottom: 12 })
        Text($r('app.string.community_loading_article'))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_tertiary'))
      }
    }
    .width('100%')
    .layoutWeight(1)
    .justifyContent(FlexAlign.Center)
    .padding({ bottom: 80, left: 32, right: 32 })
  }

  @Builder
  avatar(name: string, uri: string, official: boolean, size: number) {
    if (uri.length > 0) {
      Image(uri)
        .width(size)
        .height(size)
        .borderRadius(Math.round(size * 0.3))
        .objectFit(ImageFit.Cover)
        .backgroundColor($r('app.color.card_bg'))
    } else if (official) {
      Image($r('app.media.qwenpaw_symbol'))
        .width(size)
        .height(size)
        .borderRadius(Math.round(size * 0.3))
        .objectFit(ImageFit.Contain)
        .draggable(false)
        .backgroundColor($r('app.color.card_bg'))
    } else {
      Column() {
        Text(communityInitials(name))
          .fontSize(Math.max(11, Math.round(size * 0.29)))
          .fontWeight(FontWeight.Bold)
          .fontColor(Color.White)
      }
      .width(size)
      .height(size)
      .borderRadius(Math.round(size * 0.3))
      .backgroundColor(this.accent())
      .justifyContent(FlexAlign.Center)
    }
  }

  // label 走闭包：计数在点赞/发评论后就地更新，@Builder 简单值参数按值传递不会刷新（官方口径）
  @Builder
  statLine(icon: Resource, label: () => string) {
    Row({ space: 5 }) {
      Image(icon)
        .width(14).height(14)
        .fillColor($r('app.color.text_tertiary'))
      Text(label())
        .fontSize(UiTokens.fsChip)
        .fontColor($r('app.color.text_tertiary'))
    }
    .margin({ right: 16 })
  }

  @Builder
  articleBlock() {
    Column() {
      Row({ space: 8 }) {
        Text(this.detail !== null ? this.detail.article.articleTypeLabel : '')
          .fontSize(10)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.accent())
          .backgroundColor($r('app.color.card_bg'))
          .borderRadius(9)
          .padding({ left: 8, right: 8, top: 4, bottom: 4 })
        if (this.detail !== null && this.detail.article.qaStatus.length > 0) {
          Text(this.detail.article.qaStatus === 'solved'
            ? $r('app.string.community_qa_solved') : $r('app.string.community_qa_open'))
            .fontSize(UiTokens.fsChip)
            .fontColor(this.accent())
        }
      }
      .width('100%')

      Text(this.detail !== null ? normalizeCommunityText(this.detail.article.title) : '')
        .fontSize(25)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary_strong'))
        .lineHeight(34)
        .width('100%')
        .margin({ top: 12 })

      Row() {
        this.avatar(this.detail !== null ? this.detail.article.authorName : '',
          this.detail !== null ? this.detail.article.authorAvatarUrl : '',
          this.detail !== null && this.detail.article.identityBadge !== null &&
            this.detail.article.identityBadge.code === 'official', 38)
        Column() {
          Row({ space: 4 }) {
            Text(this.detail !== null && this.detail.article.authorName.length > 0
              ? this.detail.article.authorName : t($r('app.string.community_user')))
              .fontSize(14)
              .fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.text_primary_strong'))
              .maxLines(1)
            if (this.detail !== null && this.detail.article.identityBadge !== null) {
              Image($r('app.media.shield_check'))
                .width(14).height(14)
                .fillColor(this.accent())
            }
          }
          .alignItems(VerticalAlign.Center)
          Text(this.detail !== null
            ? formatCommunityDate(this.detail.article.publishedAt) : '')
            .fontSize(UiTokens.fsChip)
            .fontColor($r('app.color.text_tertiary'))
            .margin({ top: 2 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        .margin({ left: 10 })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 16 })

      if (this.detail !== null && this.detail.article.coverUrl.length > 0) {
        Image(this.detail.article.coverUrl)
          .width('100%')
          .aspectRatio(16 / 9)
          .objectFit(ImageFit.Cover)
          .borderRadius(15)
          .backgroundColor($r('app.color.card_bg'))
          .margin({ top: 14 })
      }

      // 正文（纯文本、可选中复制；对齐 7378 的 body_text + selectable）
      Text(this.detail !== null ? removeCommunityEmoji(this.detail.bodyText) : '')
        .fontSize(UiTokens.fsBody)
        .fontColor($r('app.color.text_primary_strong'))
        .lineHeight(24)
        .width('100%')
        .textSelectable(TextSelectableMode.SELECTABLE_UNFOCUSABLE)
        .margin({ top: 14 })

      if (this.detail !== null && this.detail.article.tags.length > 0) {
        Flex({ wrap: FlexWrap.Wrap }) {
          ForEach(this.detail.article.tags, (tag: string) => {
            Text(`#${normalizeCommunityText(tag)}`)
              .fontSize(10)
              .fontColor(this.accent())
              .backgroundColor($r('app.color.card_bg'))
              .borderRadius(7)
              .padding({ left: 7, right: 7, top: 4, bottom: 4 })
              .margin({ right: 6, top: 6 })
          }, (tag: string) => tag)
        }
        .width('100%')
        .margin({ top: 8 })
      }

      Row() {
        this.statLine($r('app.media.eye'), (): string => {
          return `${this.detail !== null ? this.detail.article.viewCount : 0}${t($r('app.string.community_views_suffix'))}`;
        })
        this.statLine($r('app.media.heart'), (): string => {
          return `${this.detail !== null ? this.detail.article.likeCount : 0}${t($r('app.string.community_likes_suffix'))}`;
        })
        this.statLine($r('app.media.message_square'), (): string => {
          return `${this.detail !== null ? this.detail.article.commentCount : 0}${t($r('app.string.community_comments_suffix'))}`;
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 14 })
    }
    .width('100%')
    // 官方《页面布局场景》缩进布局：空间充足时内容列限宽居中（两侧留白建立层次）
    .constraintSize({ maxWidth: CONTENT_MAX })
    .alignItems(HorizontalAlign.Start)
    .padding({
      left: UiTokens.pageHMargin, right: UiTokens.pageHMargin,
      top: UiTokens.topInset, bottom: 6
    })
  }

  // 正文列（列表项）：宽屏下内容列限宽并水平居中
  @Builder
  articleItems() {
    ListItem() {
      Row() {
        this.articleBlock()
      }
      .width('100%')
      .justifyContent(FlexAlign.Center)
    }
  }

  // 评论标题行：单列模式下作为列表项随正文一起滚动，分栏模式下固定在评论区顶部
  @Builder
  commentsHeaderRow() {
    Row() {
      Text($r('app.string.community_all_comments'))
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary_strong'))
      Text(this.detail !== null ? this.detail.article.commentCount.toString() : '0')
        .fontSize(UiTokens.fsCaption)
        .fontColor($r('app.color.text_tertiary'))
        .margin({ left: 6 })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .padding({
      left: UiTokens.pageHMargin, right: UiTokens.pageHMargin, top: 16, bottom: 8
    })
  }

  // 评论条目（列表项序列，含空态与末项 spacer）：两种布局共用
  @Builder
  commentItems() {
    if (this.comments.length === 0) {
      ListItem() {
        Text($r('app.string.community_no_comments'))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_tertiary'))
          .width('100%')
          .textAlign(TextAlign.Center)
          .padding({ top: 24, bottom: 24 })
      }
    }
    ForEach(this.comments, (comment: CommunityComment) => {
      ListItem() {
        this.commentRow(comment, false)
      }
    }, (comment: CommunityComment) => comment.id)
    this.dockSpacerItem()
  }

  // 末项 spacer：让开底部互动条（留白落在滚动内容里；容器 padding 会裁掉视口）
  @Builder
  dockSpacerItem() {
    ListItem() {
      Column().width('100%').height(this.dockInset())
    }
  }

  @Builder
  commentRow(comment: CommunityComment, nested: boolean) {
    Row() {
      this.avatar(comment.authorName, comment.authorAvatarUrl,
        false, nested ? 28 : 34)
      Column() {
        Row({ space: 6 }) {
          Text(comment.authorName.length > 0
            ? comment.authorName : t($r('app.string.community_user')))
            .fontSize(UiTokens.fsSecondary)
            .fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary_strong'))
            .maxLines(1)
          if (comment.accepted) {
            Text($r('app.string.community_accepted'))
              .fontSize(10)
              .fontColor(this.accent())
              .backgroundColor($r('app.color.card_bg'))
              .borderRadius(7)
              .padding({ left: 6, right: 6, top: 2, bottom: 2 })
          }
        }
        .alignItems(VerticalAlign.Center)

        // 评论正文：把其中的 URL 单独渲染成可点的链接（链接色 + 下划线，点击交系统打开）。
        // 7378 这里是纯文本（removeCommunityEmoji(comment.content)），URL 会以生字符串出现；
        // 改为按 URL 切段渲染，其余文字与 7378 一致（emoji 仍按社区口径剥掉）。
        Text() {
          ForEach(this.linkSpans(removeCommunityEmoji(comment.content)), (seg: LinkSpan) => {
            if (seg.url) {
              Span(seg.text)
                .fontColor(this.accent())
                .decoration({ type: TextDecorationType.Underline, color: this.accent() })
                .onClick((): void => {
                  this.openUrl(seg.text);
                })
            } else {
              Span(seg.text)
            }
          }, (seg: LinkSpan, idx: number) => `${idx}:${seg.url ? 'u' : 't'}`)
        }
        .fontSize(UiTokens.fsBody)
        .fontColor($r('app.color.text_primary_strong'))
        .lineHeight(22)
        .width('100%')
        .margin({ top: 5 })

        Text(`${formatCommunityDate(comment.createdAt)} · ${comment.likeCount}${t($r('app.string.community_likes_unit'))}`)
          .fontSize(UiTokens.fsChip)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 4 })

        // 回复（一级；对齐 7378 的嵌套渲染，深层回复折叠在一级之下）
        ForEach(comment.replies, (reply: CommunityComment) => {
          Row() {
            this.avatar(reply.authorName, reply.authorAvatarUrl, false, 26)
            Column() {
              Text(reply.authorName.length > 0
                ? reply.authorName : t($r('app.string.community_user')))
                .fontSize(UiTokens.fsCaption)
                .fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.text_primary_strong'))
              Text(removeCommunityEmoji(reply.content))
                .fontSize(UiTokens.fsSecondary)
                .fontColor($r('app.color.text_secondary'))
                .lineHeight(20)
                .width('100%')
                .margin({ top: 3 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            .margin({ left: 8 })
          }
          .width('100%')
          .alignItems(VerticalAlign.Top)
          .margin({ top: 10 })
        }, (reply: CommunityComment) => reply.id)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      .margin({ left: 10 })
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding({
      left: UiTokens.pageHMargin, right: UiTokens.pageHMargin,
      top: 12, bottom: 12
    })
    .margin({ left: nested ? 24 : 0 })
  }

  // 底部互动条：评论输入（多行，最多 5 行、超出框内滚动）+ 附件 + 发送 + 点赞 + 分享。
  // 形态与几何对齐聊天页 composerBar：
  //   行 = [附件][TextArea 弹性][点赞][分享][发送]；
  //   回车 = 换行（TextArea 默认，不设 EnterKeyType.Send）——发送只走发送按钮；
  //   非输入态显示点赞/分享（发送隐藏）；键盘弹起时点赞/分享缩放消失、发送出现
  //   （42vp 全高、固定宽 56vp，不被压缩）——两组键互斥显隐（宽度 → 0 + scale + opacity，
  //   与背板淡变同一 260ms 动画，见 applyKeyboardFrost），输入区撑满至聊天页同宽；
  //   按压反馈 = 跟手 scale 收缩：三个非发送键（附件/点赞/分享）均不画边框、不加点光源
  //   ——点光源光斑会在键外留方形轮廓（BRIGHT/SOFT 真机实测），按压只保留缩放形变；
  //   占位符双态（自绘覆盖层——官方 TextArea 的 placeholder 仅构造器参数、无响应式属性）：
  //   非输入"写评论" / 输入"平等交流，友好表达"；
  //   行高 refreshCommentH 实测驱动（单行 50 → 5 行封顶），栏体 dockCapsuleH() 联动
  //   （barHeight / 磨砂背板 / 列表让位 spacer 同值）。
  //   按压反馈 = 跟手 scale 收缩 + 栏材质 lightEffect 点光源（accent 主题色，见 barFloatingStyle）；
  //   键体自身不挂点光源——预设 BRIGHT/SOFT 光参真机实测在键外留方形轮廓光晕（"圆形外面
  //   有个方形"）；三个非发送键（附件/点赞/分享）均不画边框；
  @Builder
  dockBar() {
    Column() {
      Row() {
        // 附件：与聊天页附件键同形态（透明底、不画边框 + 20vp 图标）。平台上传端点契约
        // 未定，先只摆 UI（无点击动作）；按压反馈保留，外观与聊天页一致
        Button() {
          Image($r('app.media.icon_add_file'))
            .width(20)
            .height(20)
            .fillColor($r('app.color.btn_gray_text'))
            .draggable(false)
        }
        .type(ButtonType.Normal)
        .width(40)
        .height(40)
        .padding(0)
        // 透明底、不画边框：让悬浮栏的材质层（磨砂 + 受光渐层）连续透出
        .backgroundColor(Color.Transparent)
        .borderRadius(20)
        .scale({ x: this.dockPressed === 0 ? PRESS_SCALE : 1, y: this.dockPressed === 0 ? PRESS_SCALE : 1 })
        .stateEffect(false)
        .onTouch((e: TouchEvent): void => { this.onDockPress(0, e); })
        .margin({ right: 8 })

        // 多行输入：与聊天页 TextArea 同机制——高度由文本换行实测算（refreshCommentH）；
        // maxLines(5, SCROLL) 视觉封顶 5 行、超出在框内滚动（官方：SCROLL 需配合
        // textOverflow=None 才生效，漏配会落回 CLIP 截断）；回车保留换行，发送只走按钮。
        // 长按/双击弹系统选择菜单（复制/剪切/粘贴/全选，LocalDevice 免剪贴板读权限）
        Stack({ alignContent: Alignment.TopStart }) {
          TextArea({ text: $$this.commentText, controller: this.taController })
            .width('100%')
            .minLines(1)
            .textOverflow(TextOverflow.None)
            .maxLines(5, { overflowMode: MaxLinesMode.SCROLL })
            .copyOption(CopyOptions.LocalDevice)
            .fontSize(UiTokens.fsBody)
            .caretColor(this.accent())
            .backgroundColor(Color.Transparent)
            .fontColor($r('app.color.input_text'))
            .placeholderColor($r('app.color.placeholder'))
            .borderRadius(21)
            .onChange((value: string): void => {
              this.refreshCommentH(value);
            })
            // 选区变化记录末端：系统复制不会自动取消选中，复制后据此把光标归位
            .onTextSelectionChange((start: number, end: number): void => {
              if (end >= start) {
                this.taSelEnd = end;
              }
            })
            .onCopy((): void => {
              this.taController.caretPosition(this.taSelEnd);
            })
            // 实测文本宽度（vp）：宽度变化（旋转/分栏）时换行行数随之重算
            .onAreaChange((_old: Area, now: Area): void => {
              this.commentFieldW = areaWidthOf(now, this.commentFieldW);
              if (this.commentFieldW > 0) {
                this.refreshCommentH(this.commentText);
              }
            })
          // 双态占位覆盖层：键盘弹起"平等交流，友好表达"，收起"写评论"——仅在文本为空时
          // 显示；内边距对齐 TextArea 官方默认 {top:8, right:16, bottom:8, left:16}，
          // 触摸穿透到下层输入框
          Text(this.dockKb
            ? t($r('app.string.community_comment_placeholder'))
            : t($r('app.string.community_write_comment')))
            .fontSize(UiTokens.fsBody)
            .fontColor($r('app.color.placeholder'))
            .padding({ top: 8, right: 16, bottom: 8, left: 16 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .hitTestBehavior(HitTestMode.None)
            .visibility(this.commentText.length === 0 ? Visibility.Visible : Visibility.None)
        }
        .layoutWeight(1)

        // 点赞：非输入态在输入框右侧；键盘弹起时缩放消失（260ms，与背板淡变同源）
        Row() {
          Button() {
            Image(this.detail !== null && this.detail.article.liked
              ? $r('app.media.heart_fill') : $r('app.media.heart'))
              .width(20)
              .height(20)
              .fillColor(this.detail !== null && this.detail.article.liked
                ? this.accent() : $r('app.color.text_tertiary'))
              .draggable(false)
          }
          .type(ButtonType.Normal)
          .width(40)
          .height(40)
          .padding(0)
          // 不画边框；按压反馈 = 跟手 scale 收缩 + 栏材质 lightEffect 光斑（见 barFloatingStyle）
          .backgroundColor(Color.Transparent)
          .borderRadius(20)
          .stateEffect(false)
          .scale({ x: this.dockPressed === 1 ? PRESS_SCALE : 1, y: this.dockPressed === 1 ? PRESS_SCALE : 1 })
          .onTouch((e: TouchEvent): void => { this.onDockPress(1, e); })
          .onClick((): void => {
            this.like();
          })
        }
        .width(this.dockKb ? 0 : 40)
        .margin({ left: this.dockKb ? 0 : 8 })
        .clip(true)
        .scale({ x: this.dockKb ? 0.3 : 1, y: this.dockKb ? 0.3 : 1 })
        .opacity(this.dockKb ? 0 : 1)

        // 分享：与点赞同一套消失动画
        Row() {
          Button() {
            Image($r('app.media.share'))
              .width(20)
              .height(20)
              .fillColor($r('app.color.text_tertiary'))
              .draggable(false)
          }
          .type(ButtonType.Normal)
          .width(40)
          .height(40)
          .padding(0)
          // 不画边框；按压反馈 = 跟手 scale 收缩 + 栏材质 lightEffect 光斑（见 barFloatingStyle）
          .backgroundColor(Color.Transparent)
          .borderRadius(20)
          .stateEffect(false)
          .scale({ x: this.dockPressed === 2 ? PRESS_SCALE : 1, y: this.dockPressed === 2 ? PRESS_SCALE : 1 })
          .onTouch((e: TouchEvent): void => { this.onDockPress(2, e); })
          .onClick((): void => {
            this.share();
          })
        }
        .width(this.dockKb ? 0 : 40)
        .margin({ left: this.dockKb ? 0 : 8 })
        .clip(true)
        .scale({ x: this.dockKb ? 0.3 : 1, y: this.dockKb ? 0.3 : 1 })
        .opacity(this.dockKb ? 0 : 1)

        // 发送：仅键盘弹起时显示（42vp 全高、固定宽 56vp 不被压缩）；键盘收起时隐藏
        // （与点赞/分享同款缩放消失）；不可发送用不透明混色弱化（不用 enabled(false)/
        // opacity，口径见聊天页），提交中转圈
        Row() {
          Button() {
            if (this.submitting) {
              LoadingProgress()
                .width(20)
                .height(20)
                .color(Color.White)
            } else {
              Text(t($r('app.string.chat_send')))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
                .fontColor(Color.White)
            }
          }
          .type(ButtonType.Normal)
          .width(56)
          .height(42)
          .padding(0)
          .borderRadius(21)
          .backgroundColor(this.canComment()
            ? (this.isDark ? this.theme.accentDark : this.theme.accent)
            : blendHex(this.isDark ? this.theme.accentDark : this.theme.accent, '#000000', 0.55))
          // 显式关掉沉浸材质，避免材质层盖在实底上
          .systemMaterial(uiMaterial.Material.empty)
          .fontColor(Color.White)
          .scale({ x: this.dockPressed === 3 ? PRESS_SCALE : 1, y: this.dockPressed === 3 ? PRESS_SCALE : 1 })
          .stateEffect(false)
          .visualEffect(pressEffect(this.dockPressed === 3, false, true))
          .onTouch((e: TouchEvent): void => { this.onDockPress(3, e); })
          .onClick((): void => {
            if (this.canComment()) {
              this.submitComment();
            }
          })
        }
        .width(this.dockKb ? 56 : 0)
        .margin({ left: this.dockKb ? 8 : 0 })
        .clip(true)
        .scale({ x: this.dockKb ? 1 : 0.3, y: this.dockKb ? 1 : 0.3 })
        .opacity(this.dockKb ? 1 : 0)
      }
      .width('100%')
      // 与聊天页同口径：显式高度 = commentBlockH（实测驱动）；底内边距 8vp 是结构常数
      //（内容区比胶囊顶短 8vp、底部齐胶囊底，控件中心才落胶囊中心），任意行高下成立
      .padding({ left: 3, right: 3, bottom: 8 })
      .alignItems(VerticalAlign.Center)
      .height(this.commentBlockH)
    }
    .width('100%')
    .justifyContent(FlexAlign.Center)
    // 栏体高度 = dockCapsuleH()：与 Tabs 侧 barHeight 同值，磨砂背板/列表让位同量联动
    .height(this.dockCapsuleH())
    // 底色/圆角/离底/材质一律交给 barFloatingStyle（官方口径：设了悬浮材质后不要再叠
    // barBackgroundColor/barBackgroundBlurStyle，会遮住材质）
  }

  // 列表末端让位高度：悬浮条带（随输入长高，dockCapsuleH）+ 离底间距 + 系统导航区 + 一点呼吸
  private dockInset(): number {
    return this.dockCapsuleH() + DOCK_BOTTOM_MARGIN + this.navInset + 8;
  }

  // 把一段纯文本按 http(s):// 切成「文字 / 链接」段序列（供 Span 渲染成可点链接）。
  // 7378 正文与评论都是纯文本（生 URL 就是一串字符）；这里只把 URL 那一段单独上色 + 可点，
  // 其余文字原样。链接终点取到空白为止，尾部标点（)。,;）归回文字，避免吞进链接。
  private linkSpans(text: string): LinkSpan[] {
    const out: LinkSpan[] = [];
    let i: number = 0;
    while (i < text.length) {
      const at: number = text.indexOf('http', i);
      if (at < 0) {
        out.push({ text: text.substring(i), url: false });
        break;
      }
      const head: string = text.substring(at, at + 8).toLowerCase();
      if (!head.startsWith('http://') && !head.startsWith('https://')) {
        out.push({ text: text.substring(i, at + 4), url: false });
        i = at + 4;
        continue;
      }
      if (at > i) {
        out.push({ text: text.substring(i, at), url: false });
      }
      let end: number = at;
      while (end < text.length && ' \n\t'.indexOf(text.charAt(end)) < 0) {
        end++;
      }
      while (end > at && '),.;、，。）]'.indexOf(text.charAt(end - 1)) >= 0) {
        end--;
      }
      out.push({ text: text.substring(at, end), url: true });
      i = end;
    }
    if (out.length === 0) {
      out.push({ text: text, url: false });
    }
    return out;
  }

  // 链接交系统打开（应用内不内嵌浏览器；与「非文本文件交系统预览」同一取向）
  private openUrl(url: string): void {
    try {
      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      ctx.openLink(url, {}, (err: BusinessError): void => {
        if (err) {
          this.error = t($r('app.string.community_open_link_failed'));
        }
      });
    } catch (e) {
      this.error = t($r('app.string.community_open_link_failed'));
    }
  }
}
