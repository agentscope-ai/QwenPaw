/*
 * 社区发布文章 —— 移植 PR #7378 app/community/compose.tsx：
 *   文章类型胶囊（取 Platform meta，失败回落内置四类）+ 标题 + 正文 + 标签（空格/逗号分隔，最多 5 个）
 *   + 隐私说明 + 右上「发布」。发布前二次确认（会同步到公开社区）。
 * 与 7378 的差异（有意）：7378 的「发布」是页头右侧文字按钮；本工程 HDS 标题栏为通用样式，
 *   发布入口做成底部主按钮（内容区主操作），同样带「发布中」态与二次确认。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { areaWidthOf, wideClampW } from '../theme/Breakpoints';
import { common } from '@kit.AbilityKit';
import {
  CommunityArticleType, CommunityArticleDraft, CommunityMeta, getCommunityMeta,
  publishCommunityArticle
} from '../services/CommunityService';
import { CommunityArticleParam } from '../components/CommunityTab';
import { ThemeManager, ThemeSnapshot } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';

import { popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { t } from '../services/I18n';

const TITLE_MAX: number = 256;

@Builder
export function CommunityComposePageBuilder(_name: string, param: Object) {
  CommunityComposePage({ params: param })
}

@Component
export struct CommunityComposePage {
  params: Object = new Object();
  @State types: CommunityArticleType[] = [];
  @State articleType: string = 'work_share';
  @State title: string = '';
  @State body: string = '';
  @State tags: string = '';
  @State publishing: boolean = false;
  @State pressed: number = -1;
  @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  private latch: PressLatch = new PressLatch();

  // 大屏（平板/电脑）内容列限宽：官方《页面布局场景》缩进布局 —— 空间充足时内容列居中、两侧留白；
  // 宽度由外层满宽容器 onAreaChange 实时上报（跟随窗口缩放），实现见 theme/Breakpoints
  @State pageW: number = 0;

  private onPageArea = (_old: Area, now: Area): void => {
    this.pageW = areaWidthOf(now, this.pageW);
  };

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const st: Object = rec['stack'];
    this.stack = (st === undefined || st === null) ? null : st as NavPathStack;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    // 文章类型取 Platform meta（失败回落内置四类，见 typeOptions）
    getCommunityMeta().then((meta: CommunityMeta): void => {
      this.types = meta.filterTypes;
    }).catch((): void => {
    });
  }

  // 标签拆分（对齐 7378：逗号/中文逗号/空白都可分隔）
  private tagList(): string[] {
    const parts: string[] = this.tags.split(/[,，\s]+/);
    const out: string[] = [];
    for (const p of parts) {
      const v: string = p.trim();
      if (v.length > 0) {
        out.push(v);
      }
    }
    return out;
  }

  private accent(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private publish(): void {
    if (this.title.trim().length === 0) {
      this.getUIContext().getPromptAction().showToast({ message: t($r('app.string.community_need_title')) });
      return;
    }
    if (this.body.trim().length === 0) {
      this.getUIContext().getPromptAction().showToast({ message: t($r('app.string.community_need_body')) });
      return;
    }
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.community_publish_confirm_title')),
      message: t($r('app.string.community_publish_confirm_copy')),
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {
        }
      },
      secondaryButton: {
        value: t($r('app.string.community_publish_confirm_action')),
        action: (): void => {
          this.submitPublish();
        }
      }
    });
  }

  private async submitPublish(): Promise<void> {
    if (this.publishing) {
      return;
    }
    this.publishing = true;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    try {
      const draft: CommunityArticleDraft = {
        title: this.title,
        articleType: this.articleType,
        body: this.body,
        tags: this.tagList()
      };
      const id: string = await publishCommunityArticle(ctx, draft);
      const stack: NavPathStack | null = this.stack;
      if (stack !== null) {
        if (id.length > 0) {
          // 发布成功 → 用详情页替换本页（对齐 7378 router.replace 到文章详情）
          const param: CommunityArticleParam = { articleId: id, stack: stack };
          stack.replacePath({ name: 'community-article', param: param });
        } else {
          stack.pop();
        }
      }
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.community_published'))
      });
    } catch (e) {
      this.getUIContext().showAlertDialog({
        title: t($r('app.string.community_publish_failed')),
        message: (e as Error).message
      });
    } finally {
      this.publishing = false;
    }
  }

  build() {
    HdsNavDestination() {
      Row() {
        Scroll() {
          Column() {
            Text($r('app.string.community_field_type'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .width('100%')
              .margin({ top: 4, bottom: 8 })

            Row({ space: 7 }) {
              ForEach(this.typeOptions(), (type: CommunityArticleType) => {
                Text(type.label)
                  .fontSize(UiTokens.fsSecondary)
                  .fontColor(this.articleType === type.code
                    ? Color.White : $r('app.color.text_secondary'))
                  .height(34)
                  .padding({ left: 14, right: 14 })
                  .borderRadius(17)
                  .backgroundColor(this.articleType === type.code
                    ? this.accent() : $r('app.color.card_bg'))
                  .onClick((): void => {
                    this.articleType = type.code;
                  })
              }, (type: CommunityArticleType) => type.code)
            }
            .width('100%')

            TextInput({ placeholder: $r('app.string.community_title_placeholder'), text: $$this.title })
              .maxLength(TITLE_MAX)
              .fontSize(20)
              .fontWeight(FontWeight.Medium)
              .caretColor(this.accent())
              .backgroundColor(Color.Transparent)
              .fontColor($r('app.color.text_primary_strong'))
              .placeholderColor($r('app.color.placeholder'))
              .placeholderFont({ size: 20 })
              .padding({ left: 0, right: 0 })
              .height(52)
              .margin({ top: 18 })

            Divider()
              .color($r('app.color.line'))

            TextArea({ placeholder: $r('app.string.community_body_placeholder'), text: $$this.body })
              .fontSize(UiTokens.fsBody)
              .caretColor(this.accent())
              .backgroundColor(Color.Transparent)
              .fontColor($r('app.color.text_primary_strong'))
              .placeholderColor($r('app.color.placeholder'))
              .padding({ left: 0, right: 0, top: 12 })
              .height(240)

            Text($r('app.string.community_field_tags'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .width('100%')
              .margin({ top: 10, bottom: 6 })
            TextInput({ placeholder: $r('app.string.community_tags_placeholder'), text: $$this.tags })
              .fontSize(UiTokens.fsSecondary)
              .caretColor(this.accent())
              .backgroundColor($r('app.color.card_bg'))
              .fontColor($r('app.color.input_text'))
              .placeholderColor($r('app.color.placeholder'))
              .placeholderFont({ size: UiTokens.fsSecondary })
              .height(44)
              .borderRadius(12)
              .padding({ left: 12, right: 12 })

            Row({ space: 9 }) {
              Image($r('app.media.shield_check'))
                .width(17).height(17)
                .fillColor(this.accent())
              Text($r('app.string.community_privacy_note'))
                .fontSize(UiTokens.fsChip)
                .fontColor($r('app.color.text_tertiary'))
                .lineHeight(17)
                .layoutWeight(1)
            }
            .width('100%')
            .alignItems(VerticalAlign.Top)
            .padding(13)
            .borderRadius(12)
            .backgroundColor($r('app.color.card_bg'))
            .margin({ top: 16, bottom: 8 })

            Text(this.publishing
              ? $r('app.string.community_publishing') : $r('app.string.community_publish'))
              .fontSize(UiTokens.fsBody)
              .fontWeight(FontWeight.Medium)
              .fontColor(Color.White)
              .textAlign(TextAlign.Center)
              .width('100%')
              .height(48)
              .borderRadius(24)
              .backgroundColor(this.accent())
              .opacity(this.publishing ? 0.6 : 1)
              .scale({ x: this.pressed === 0 ? PRESS_SCALE : 1, y: this.pressed === 0 ? PRESS_SCALE : 1 })
              .visualEffect(pressEffect(this.pressed === 0))
              .margin({ top: 12, bottom: 24 })
              .onTouch((e: TouchEvent): void => {
                pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
                  this.pressed = v ? 0 : -1;
                });
              })
              .onClick((): void => {
                this.publish();
              })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
          .padding({
            top: UiTokens.topInset, left: UiTokens.pageHMargin, right: UiTokens.pageHMargin
          })
        }
        .width(wideClampW(this.pageW))
        .height('100%')
        .scrollBar(BarState.Off)
        .align(Alignment.Top)
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
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
        title: { mainTitle: $r('app.string.community_compose_title') }
      },
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
    .backgroundColor($r('app.color.page_bg'))
    .expandSafeArea([SafeAreaType.SYSTEM],
      [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
  }

  // 文章类型：Platform meta 优先，取不到时回落内置四类（对齐 7378 fallbackTypes）
  private typeOptions(): CommunityArticleType[] {
    if (this.types.length > 0) {
      return this.types;
    }
    const fallback: CommunityArticleType[] = [
      { code: 'work_share', label: t($r('app.string.community_type_work_share')) },
      { code: 'app_case', label: t($r('app.string.community_type_app_case')) },
      { code: 'beginner_tutorial', label: t($r('app.string.community_type_tutorial')) },
      { code: 'discussion', label: t($r('app.string.community_type_discussion')) }
    ];
    return fallback;
  }
}
