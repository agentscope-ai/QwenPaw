/*
 * AgentScope Platform 登录 —— 移植 PR #7378 app/community/login.tsx + features/platform/PlatformAuthForm.tsx
 * 的账号密码/注册路径（登录 / 注册分段、获取邮箱验证码倒计时、密码二次确认、隐私说明）。
 * 成功后：returnTo = 'compose' 时替换为发布页（对齐 7378 router.replace("/community/compose")），
 * 否则退回上一页（点赞/评论等操作在会话建立后即可继续）。
 *
 * 与 7378 的差异（有意）：GitHub OAuth（浏览器/回跳）一期未移植，见 services/PlatformSession.ets 说明。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { areaWidthOf, wideClampW } from '../theme/Breakpoints';
import { common } from '@kit.AbilityKit';
import {
  platformLogin, registerPlatform, sendPlatformVerificationCode, PlatformSession,
  loadPlatformSession
} from '../services/PlatformSession';
import { CommunityComposeParam } from '../components/CommunityTab';
import { SegmentedControl } from '../components/SegmentedControl';
import { ThemeManager, ThemeSnapshot } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';

import { uiMaterial } from '@kit.ArkUI';
import { pushRoute, popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { t } from '../services/I18n';

const CODE_COUNTDOWN: number = 60;
// 登录/注册连排按钮几何（与首页社区工具条同结构、按本页 44vp 高度给内边距）
const SEG_H: number = 36;

@Builder
export function PlatformLoginPageBuilder(_name: string, param: Object) {
  PlatformLoginPage({ params: param })
}

@Component
export struct PlatformLoginPage {
  params: Object = new Object();
  @State mode: string = 'login';      // 'login' | 'register'
  @State account: string = '';
  @State password: string = '';
  @State confirmPassword: string = '';
  @State verifyCode: string = '';
  @State countdown: number = 0;
  @State busy: boolean = false;
  @State oauthBusy: boolean = false;
  @State codeBusy: boolean = false;
  @State error: string = '';
  @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 沉浸材质（内容区要让材质真生效只有 Toggle(ToggleType.Button) 外壳这条路）：
  // 玻璃底色 + 主行动（带主题色，对齐社区页「发布」按钮口径）；只建一次，主题/深浅变化时重建
  private glassMaterial: SystemUiMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THIN,
    interactive: true,
    lightEffect: {}
  });
  private accentMaterial: SystemUiMaterial = this.glassMaterial;
  private returnTo: string = '';
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  private timer: number = -1;

  // 大屏（平板/电脑）内容列限宽：官方《页面布局场景》缩进布局 —— 空间充足时内容列居中、两侧留白；
  // 宽度由外层满宽容器 onAreaChange 实时上报（跟随窗口缩放），实现见 theme/Breakpoints
  @State pageW: number = 0;

  private onPageArea = (_old: Area, now: Area): void => {
    this.pageW = areaWidthOf(now, this.pageW);
  };

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const rt: Object = rec['returnTo'];
    this.returnTo = typeof rt === 'string' ? rt as string : '';
    const st: Object = rec['stack'];
    this.stack = (st === undefined || st === null) ? null : st as NavPathStack;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.buildMaterials();
  }

  private buildMaterials(): void {
    this.glassMaterial = new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.THIN,
      interactive: true,
      lightEffect: {}
    });
    this.accentMaterial = new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.THIN,
      interactive: true,
      lightEffect: {},
      materialColor: this.accentGlass()
    });
  }

  // 主题色玻璃（30% 透明度）：材质底色用，取法与首页工具条同口径
  private accentGlass(): ResourceColor {
    const a: ResourceColor = this.accent();
    if (typeof a === 'string' && a.length === 7) {
      return `#4D${(a as string).substring(1)}`;
    }
    return a;
  }

  aboutToDisappear(): void {
    if (this.timer >= 0) {
      clearInterval(this.timer);
      this.timer = -1;
    }
  }

  private accent(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private toast(message: string): void {
    this.getUIContext().getPromptAction().showToast({ message: message });
  }

  private startCountdown(): void {
    this.countdown = CODE_COUNTDOWN;
    if (this.timer >= 0) {
      clearInterval(this.timer);
    }
    this.timer = setInterval((): void => {
      const next: number = this.countdown - 1;
      this.countdown = next > 0 ? next : 0;
      if (next <= 0 && this.timer >= 0) {
        clearInterval(this.timer);
        this.timer = -1;
      }
    }, 1000);
  }

  private async sendCode(): Promise<void> {
    const account: string = this.account.trim();
    if (account.length === 0) {
      this.error = t($r('app.string.platform_login_need_account'));
      return;
    }
    if (this.codeBusy || this.countdown > 0) {
      return;
    }
    this.codeBusy = true;
    this.error = '';
    try {
      await sendPlatformVerificationCode(account);
      this.startCountdown();
      this.toast(t($r('app.string.platform_login_code_sent')));
    } catch (e) {
      this.error = (e as Error).message;
    } finally {
      this.codeBusy = false;
    }
  }

  private async submit(): Promise<void> {
    if (this.busy) {
      return;
    }
    const account: string = this.account.trim();
    if (account.length === 0) {
      this.error = t($r('app.string.platform_login_need_account'));
      return;
    }
    if (this.password.length === 0) {
      this.error = t($r('app.string.platform_login_need_password'));
      return;
    }
    if (this.mode === 'register') {
      if (this.verifyCode.trim().length === 0) {
        this.error = t($r('app.string.platform_login_need_code'));
        return;
      }
      if (this.password !== this.confirmPassword) {
        this.error = t($r('app.string.platform_login_password_mismatch'));
        return;
      }
    }
    this.busy = true;
    this.error = '';
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    try {
      if (this.mode === 'register') {
        await registerPlatform(account, this.password, this.verifyCode.trim());
        this.toast(t($r('app.string.platform_login_registered')));
        this.mode = 'login';
        this.verifyCode = '';
        this.confirmPassword = '';
        return;
      }
      const session: PlatformSession = await platformLogin(ctx, account, this.password);
      this.afterLogin(session.username);
    } catch (e) {
      this.error = (e as Error).message;
    } finally {
      this.busy = false;
    }
  }

  // GitHub 授权登录：跳内嵌授权页（pages/PlatformOAuthPage.ets），成功后由 afterOAuthReturn 收尾
  private openGitHub(): void {
    const stack: NavPathStack | null = this.stack;
    if (stack === null || this.oauthBusy) {
      return;
    }
    this.error = '';
    this.oauthBusy = true;
    const param: Record<string, Object> = { 'stack': stack };
    pushRoute(stack, 'platform-oauth', param);
  }

  // 从授权页返回：已建立会话则按登录成功继续（与账号密码路径同一个收尾），否则只解除忙碌态
  private async afterOAuthReturn(): Promise<void> {
    if (!this.oauthBusy) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    try {
      const session: PlatformSession | null = await loadPlatformSession(ctx);
      if (session !== null) {
        this.afterLogin(session.username);
        return;
      }
    } catch (e) {
      // 复查失败按未登录处理，留在本页
    }
    this.oauthBusy = false;
  }

  private afterLogin(username: string): void {
    this.toast(username.length > 0
      ? `${t($r('app.string.platform_login_ok'))} · ${username}`
      : t($r('app.string.platform_login_ok')));
    const stack: NavPathStack | null = this.stack;
    if (stack === null) {
      return;
    }
    if (this.returnTo === 'compose') {
      const composeParam: CommunityComposeParam = { stack: stack };
      stack.replacePath({ name: 'community-compose', param: composeParam });
      return;
    }
    stack.pop();
  }

  build() {
    HdsNavDestination() {
      Row() {
        Scroll() {
          Column() {
            Column() {
              // 图标 = 7378 community/login.tsx 同一枚 lucide LogIn（白色画在主色块上）
              Image($r('app.media.log_in'))
                .width(28)
                .height(28)
                .fillColor(Color.White)
            }
            .width(58)
            .height(58)
            .borderRadius(18)
            .backgroundColor(this.accent())
            .justifyContent(FlexAlign.Center)

            Text($r('app.string.platform_login_heading'))
              .fontSize(27)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary_strong'))
              .margin({ top: 18 })
            Text($r('app.string.platform_login_copy'))
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.text_secondary'))
              .lineHeight(22)
              .margin({ top: 8 })

            // 登录 / 注册：连排按钮（共用组件 components/SegmentedControl.ets —— 一个框 + 跟手滑块 +
            // 沉浸材质 + 点击/拖动两入口）；切换带补间，注册专属字段随之进场
            Row() {
              SegmentedControl({
                labels: [$r('app.string.platform_login_segment_login'),
                  $r('app.string.platform_login_segment_register')],
                selectedIndex: this.mode === 'register' ? 1 : 0,
                segHeight: SEG_H,
                material: this.glassMaterial,
                onChange: (index: number): void => {
                  this.switchMode(index === 1 ? 'register' : 'login');
                }
              })
            }
            .width('100%')
            .margin({ top: 22 })

            Text($r('app.string.platform_login_account'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .width('100%')
              .margin({ top: 18, bottom: 6 })
            TextInput({
              placeholder: this.mode === 'register'
                ? $r('app.string.platform_login_account_hint_register')
                : $r('app.string.platform_login_account_hint'),
              text: $$this.account
            })
              .fontSize(UiTokens.fsBody)
              .caretColor(this.accent())
              .backgroundColor($r('app.color.card_bg'))
              .fontColor($r('app.color.input_text'))
              .placeholderColor($r('app.color.placeholder'))
              .placeholderFont({ size: UiTokens.fsBody })
              .height(46)
              .borderRadius(12)
              .padding({ left: 12, right: 12 })

            if (this.mode === 'register') {
              // 注册专属字段：随模式切换补间进场（配合 SegmentedControl 的补间，避免硬切）
              Column() {
                Text($r('app.string.platform_login_code'))
                  .fontSize(UiTokens.fsCaption)
                  .fontColor($r('app.color.text_tertiary'))
                  .width('100%')
                  .margin({ top: 14, bottom: 6 })
                Row({ space: 8 }) {
                  TextInput({
                    placeholder: $r('app.string.platform_login_code_placeholder'),
                    text: $$this.verifyCode
                  })
                    .fontSize(UiTokens.fsBody)
                    .caretColor(this.accent())
                    .backgroundColor($r('app.color.card_bg'))
                    .fontColor($r('app.color.input_text'))
                    .placeholderColor($r('app.color.placeholder'))
                    .placeholderFont({ size: UiTokens.fsBody })
                    .height(46)
                    .borderRadius(12)
                    .padding({ left: 12, right: 12 })
                    .layoutWeight(1)
                  Text(this.countdown > 0
                    ? `${this.countdown}s` : $r('app.string.platform_login_send_code'))
                    .fontSize(UiTokens.fsSecondary)
                    .fontColor(this.countdown > 0
                      ? $r('app.color.text_tertiary') : this.accent())
                    .textAlign(TextAlign.Center)
                    .height(46)
                    .padding({ left: 14, right: 14 })
                    .borderRadius(12)
                    .backgroundColor($r('app.color.card_bg'))
                    .onClick((): void => {
                      this.sendCode();
                    })
                }
                .width('100%')
              }
              .width('100%')
              .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: -8 })))
            }

            Text($r('app.string.platform_login_password'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .width('100%')
              .margin({ top: 14, bottom: 6 })
            TextInput({
              placeholder: $r('app.string.platform_login_password_hint'),
              text: $$this.password
            })
              .type(InputType.Password)
              .fontSize(UiTokens.fsBody)
              .caretColor(this.accent())
              .backgroundColor($r('app.color.card_bg'))
              .fontColor($r('app.color.input_text'))
              .placeholderColor($r('app.color.placeholder'))
              .placeholderFont({ size: UiTokens.fsBody })
              .height(46)
              .borderRadius(12)
              .padding({ left: 12, right: 12 })

            if (this.mode === 'register') {
              Text($r('app.string.platform_login_confirm_password'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .width('100%')
                .margin({ top: 14, bottom: 6 })
              TextInput({
                placeholder: $r('app.string.platform_login_confirm_hint'),
                text: $$this.confirmPassword
              })
                .type(InputType.Password)
                .fontSize(UiTokens.fsBody)
                .caretColor(this.accent())
                .backgroundColor($r('app.color.card_bg'))
                .fontColor($r('app.color.input_text'))
                .placeholderColor($r('app.color.placeholder'))
                .placeholderFont({ size: UiTokens.fsBody })
                .height(46)
                .borderRadius(12)
                .padding({ left: 12, right: 12 })
            }

            if (this.error.length > 0) {
              Text(this.error)
                .fontSize(UiTokens.fsSecondary)
                .fontColor($r('app.color.status_error'))
                .width('100%')
                .lineHeight(19)
                .margin({ top: 12 })
            }

            // 主行动（提交）：Toggle(ToggleType.Button) 外壳承载「主题色沉浸材质」——内容区只有
            // Toggle 外壳能让材质真生效（官方豁免名单），材质自带交互形变 + 点光源反馈，无需自绘
            Toggle({ type: ToggleType.Button, isOn: false }) {
              Text(this.busy
                ? $r('app.string.platform_login_submitting')
                : (this.mode === 'register'
                  ? $r('app.string.platform_login_submit_register')
                  : $r('app.string.platform_login_submit')))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
                .fontColor(Color.White)
                .textAlign(TextAlign.Center)
                .width('100%')
                .height(48)
            }
            .width('100%')
            .height(48)
            .borderRadius(24)
            .backgroundColor(Color.Transparent)
            .systemMaterial(this.accentMaterial)
            .selectedColor(Color.Transparent)
            .enabled(!this.busy)
            .opacity(this.busy ? 0.6 : 1)
            .margin({ top: 18 })
            .onChange((isOn: boolean): void => {
              this.submit();
            })

            // GitHub 授权登录（内嵌 ArkWeb 授权页）：与账号密码并列的第二条登录路径。
            // 图标 = 7378 同一枚 lucide GitBranch（lucide 官方几何落在 resources/base/media/git_branch.svg，
            // 按主题色 fillColor 上色；不用系统符号里语义相近的替代件）。
            Toggle({ type: ToggleType.Button, isOn: false }) {
              Row({ space: 9 }) {
                Image($r('app.media.git_branch'))
                  .width(20)
                  .height(20)
                  .fillColor($r('app.color.text_primary_strong'))
                Text($r('app.string.platform_login_github'))
                  .fontSize(UiTokens.fsBody)
                  .fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.text_primary_strong'))
              }
              .width('100%')
              .height(50)
              .justifyContent(FlexAlign.Center)
            }
            .width('100%')
            .height(50)
            .borderRadius(14)
            .backgroundColor(Color.Transparent)
            .systemMaterial(this.glassMaterial)
            .selectedColor(Color.Transparent)
            .enabled(!(this.oauthBusy || this.busy))
            .opacity(this.oauthBusy || this.busy ? 0.6 : 1)
            .margin({ top: 12 })
            .onChange((isOn: boolean): void => {
              this.openGitHub();
            })

            Text($r('app.string.platform_login_github_hint'))
              .fontSize(UiTokens.fsChip)
              .fontColor($r('app.color.text_tertiary'))
              .textAlign(TextAlign.Center)
              .width('100%')
              .margin({ top: 8 })

            Row({ space: 9 }) {
              // 图标 = 7378 同一枚 lucide ShieldCheck
              Image($r('app.media.shield_check'))
                .width(17)
                .height(17)
                .fillColor(this.accent())
              Text($r('app.string.platform_login_security_note'))
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
            .margin({ top: 18, bottom: 24 })
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
        title: { mainTitle: $r('app.string.platform_login_title') }
      },
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
    .backgroundColor($r('app.color.page_bg'))
    .expandSafeArea([SafeAreaType.SYSTEM],
      [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
    .onShown((): void => {
      // 从 GitHub 授权页返回：若已建立会话则按登录成功收尾
      this.afterOAuthReturn();
    })
  }

  // 登录 / 注册切换：带补间（滑块跑过去 + 注册字段随之进场）；点击与滑动两个入口共用
  private switchMode(next: string): void {
    if (this.mode === next) {
      return;
    }
    this.getUIContext().animateTo({ duration: 220, curve: Curve.EaseOut }, (): void => {
      this.mode = next;
      this.error = '';
    });
  }
}
