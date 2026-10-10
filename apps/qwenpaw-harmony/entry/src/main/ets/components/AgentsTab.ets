/*
 * 智能体 tab —— 移植 PR #7378 移动端 agents 页数据源与选择功能：
 *   GET /api/agents（全部智能体）；点行 = 切换当前智能体
 *   （selectAgent 持久化 agentId + 广播 AGENT_CHANGE_EVENT，
 *   会话列表/审批经 X-Agent-Id 头按新 agent 重载）。
 * 布局对齐 RN 内容流 + iOS 大标题式滚动：
 *   整页只有一条 List（首项 = 标题栏 + 搜索条 + 呼吸边距的占位 spacer，用空 item 而非 padding：
 *   padding 会裁剪列表，内容就滚不到标题栏/搜索条之下，沉浸与渐变模糊无从生效）；
 *   当前智能体卡作为列表次项，随上滑一起滚走，滚出后名称由标题栏名字胶囊常驻接管
 *   （onHeaderState 上报滚动进度 p，Index 据此显隐胶囊）；
 *   搜索框常驻标题栏 bottomBuilder（见 Index.titleSearchArea），上滑随标题收至 MINI 后停在其下方。
 * 列表区 = List 内滚 + Refresh 下拉刷新；List 内容走 listPhase() 状态机
 *   （0 错误 / 1 未连接 / 2 首载 / 3 正常），避免多层 if-else 嵌套。
 */

import { common, Configuration, ConfigurationConstant } from '@kit.AbilityKit';
import { emitter } from '@kit.BasicServicesKit';
import { uiMaterial } from '@kit.ArkUI';
import { loadConnection, QpConnection } from '../services/ConnectionStore';
import {
  fetchAgents, selectAgent, mutateAgent, createAgent, copyAgent, AgentInfo, AgentAction,
  AGENT_CHANGE_EVENT, AGENT_CREATE_EVENT
} from '../services/AgentsService';
import {
  AgentProfile, loadProfiles, saveProfile, profileName, profileColor, firstChar, AVATAR_COLORS
} from '../services/AgentProfileStore';
import { hostOf } from '../services/PairingModel';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { GlassCard } from './GlassCard';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { CONN_CHANGE_EVENT } from './WorkbenchTab';

@Component
export struct AgentsTab {
  scroller: Scroller = new Scroller();
  // 搜索词（由 Index 标题栏搜索区输入，@Prop 单向同步驱动列表过滤）
  @Prop query: string = '';
  // 状态上报：p = 滚动进度∈[0,1]；agentName = 当前智能体名；
  // takeover = 首行智能体卡已上滑碰到搜索框（Index 据此把标题接管为智能体名）
  onHeaderState: (p: number, agentName: string, takeover: boolean) => void =
    (_p: number, _n: string, _t: boolean): void => {};
  @State agents: AgentInfo[] = [];
  @State loading: boolean = false;
  @State error: string = '';
  @State conn: QpConnection | null = null;
  @State connHost: string = '';
  @State activeAgentId: string = '';
  @State switchingId: string = '';
  @State refreshing: boolean = false;
  // 滚动进度：0=列表在顶 → 1=滚过 144vp（用于标题栏/键盘联动）
  @State headerP: number = 0;
  // 标题接管态（首行卡碰到搜索框）——仅用于变更判定，不直接驱动 UI
  private headerTakeover: boolean = false;
  // —— 智能体管理（行内 ⋯ 菜单 / 创建 / 复制 / 头像昵称）——
  @State profiles: Map<string, AgentProfile> = new Map<string, AgentProfile>();
  @State sheetShown: boolean = false;
  // 半模态开关统一走闸门（单向绑定 + 回退动画期间排队；材质由 moduleSheetOptions 统一给）
  private gate: SheetGate = new SheetGate();

  private openSheet(): void {
    if (!this.gate.request()) {
      return;
    }
    this.sheetShown = true;
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  @State sheetMode: string = '';                 // create / copy / profile
  @State formName: string = '';
  @State formId: string = '';
  @State formDesc: string = '';
  @State formWorkspace: string = '';
  @State formCopyMd: boolean = true;
  @State formCopySkills: boolean = false;
  @State formCopyJobs: boolean = false;
  @State profileAgentId: string = '';
  @State profileNick: string = '';
  @State profileColorPick: string = '';
  @State copyFrom: string = '';                  // 复制的源智能体 id
  @State busy: boolean = false;
  @State isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  private themeListener: ThemeListener | null = null;
  private agentListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};
  private connListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};
  private createListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {
    this.openCreate();
  };

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.isDark = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
    };
    ThemeManager.get().subscribe(this.themeListener);
    // 「会话」页连接/断开 → 重载智能体列表
    this.connListener = (_data: emitter.EventData): void => {
      this.refresh(false);
    };
    // 智能体切换（本页发起）→ 同步当前智能体状态（智能体列表本身全局不变）
    this.agentListener = (_data: emitter.EventData): void => {
      loadConnection(ctx).then((c: QpConnection | null) => {
        if (c !== null) {
          this.conn = c;
          this.connHost = hostOf(c.baseUrl);
          this.activeAgentId = c.agentId;
        } else {
          this.conn = null;
          this.connHost = '';
        }
        this.syncHeaderState();
      });
    };
    emitter.on(CONN_CHANGE_EVENT, this.connListener);
    emitter.on(AGENT_CHANGE_EVENT, this.agentListener);
    emitter.on(AGENT_CREATE_EVENT, this.createListener);
    this.reloadProfiles();
    this.refresh(false);
  }

  aboutToDisappear(): void {
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
    emitter.off(CONN_CHANGE_EVENT, this.connListener);
    emitter.off(AGENT_CHANGE_EVENT, this.agentListener);
    emitter.off(AGENT_CREATE_EVENT, this.createListener);
  }

  onConfigurationUpdate(newConfig: Configuration): void {
    this.isDark = newConfig.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
  }

  private async refresh(fromPull: boolean): Promise<void> {
    if (this.loading) {
      if (fromPull) {
        // 已有请求在途：直接收起下拉态，避免转圈卡死
        this.refreshing = false;
      }
      return;
    }
    this.loading = true;
    this.error = '';
    try {
      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      const conn: QpConnection | null = await loadConnection(ctx);
      if (conn === null) {
        this.conn = null;
        this.connHost = '';
        this.agents = [];
      } else {
        this.conn = conn;
        this.connHost = hostOf(conn.baseUrl);
        if (this.activeAgentId.length === 0) {
          this.activeAgentId = conn.agentId;
        }
        this.agents = await fetchAgents(conn.baseUrl, conn.token, conn.agentId);
      }
    } catch (e) {
      this.error = String((e as Error).message);
    } finally {
      this.loading = false;
      this.refreshing = false;
    }
    this.syncHeaderState();
  }

  // 数据变化后同步标题栏（接管态下 mainTitle 名称可能已变）
  private syncHeaderState(): void {
    this.headerTakeover = this.nameTakeover();
    this.onHeaderState(this.headerP, this.agentName(), this.headerTakeover);
  }

  // 标题接管判定：首行智能体卡可见顶越过 MINI 标题栏 + 搜索条下缘（= "碰到搜索框"）。
  // 口径与 Index 共用 UiTokens.nameTakeover（几何实测钉死），不依赖逐帧 onAreaChange
  private nameTakeover(): boolean {
    const y: number = this.scroller.currentOffset().yOffset as number;
    return UiTokens.nameTakeover(y);
  }

  // 对齐 RN visibleAgents：名称 + 描述 客户端过滤
  private visibleAgents(): AgentInfo[] {
    const normalized: string = this.query.trim().toLowerCase();
    if (normalized.length === 0) {
      return this.agents;
    }
    const out: AgentInfo[] = [];
    for (const a of this.agents) {
      if (`${a.name} ${a.description}`.toLowerCase().includes(normalized)) {
        out.push(a);
      }
    }
    return out;
  }

  // 对齐 RN activeAgent：当前 agentId 命中，否则首个
  private activeAgent(): AgentInfo | null {
    for (const a of this.agents) {
      if (a.id === this.activeAgentId) {
        return a;
      }
    }
    return this.agents.length > 0 ? this.agents[0] : null;
  }

  // —— 展示档案（本地昵称/头像底色，不改服务端数据）——
  private agentNameOf(a: AgentInfo): string {
    return profileName(this.profiles, a.id, a.name);
  }

  private agentColorOf(a: AgentInfo): string {
    return profileColor(this.profiles, a.id);
  }

  private async reloadProfiles(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.profiles = await loadProfiles(ctx);
  }

  private agentName(): string {
    const a: AgentInfo | null = this.activeAgent();
    return a === null ? '' : this.agentNameOf(a);
  }

  private agentInitial(): string {
    return firstChar(this.agentName());
  }

  // 对齐 RN currentCard meta：workspaceName · 新会话与工作台跟随此智能体
  private agentMeta(): string {
    if (this.activeAgent() === null) {
      return '';
    }
    return `${this.connHost}${this.t($r('app.string.agents_current_follow'))}`;
  }

  // —— 管理动作 ——
  private canDelete(a: AgentInfo): boolean {
    return a.id !== 'default' && a.id !== this.activeAgentId;
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private async doMutate(action: AgentAction, a: AgentInfo): Promise<void> {
    if (this.conn === null || this.busy) {
      return;
    }
    this.busy = true;
    try {
      await mutateAgent(this.conn.baseUrl, this.conn.token, this.conn.agentId, action, a);
      await this.refresh(false);
    } catch (e) {
      this.toast((e as Error).message);
    } finally {
      this.busy = false;
    }
  }

  private confirmDelete(a: AgentInfo): void {
    this.getUIContext().showAlertDialog({
      title: this.t($r('app.string.agents_delete_title')),
      message: `${this.agentNameOf(a)}：${this.t($r('app.string.agents_delete_msg'))}`,
      primaryButton: {
        value: this.t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: this.t($r('app.string.common_confirm_delete')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.doMutate('delete', a);
        }
      }
    });
  }

  // 行内 ⋯ 菜单（数据驱动 MenuElement，随行状态变化）
  private menuOf(a: AgentInfo): MenuElement[] {
    const items: MenuElement[] = [
      {
        value: $r('app.string.agents_menu_copy'),
        action: (): void => {
          this.openCopy(a);
        }
      },
      {
        value: a.pinned ? $r('app.string.agents_menu_unpin') : $r('app.string.agents_menu_pin'),
        action: (): void => {
          this.doMutate('pin', a);
        }
      },
      {
        value: a.enabled ? $r('app.string.agents_menu_disable') : $r('app.string.agents_menu_enable'),
        action: (): void => {
          this.doMutate('toggle', a);
        }
      }
    ];
    if (this.canDelete(a)) {
      items.push({
        value: $r('app.string.agents_menu_delete'),
        action: (): void => {
          this.confirmDelete(a);
        }
      });
    }
    return items;
  }

  private openProfile(a: AgentInfo): void {
    this.sheetMode = 'profile';
    this.profileAgentId = a.id;
    this.profileNick = this.agentNameOf(a) === a.name ? '' : this.agentNameOf(a);
    this.profileColorPick = this.agentColorOf(a);
    this.openSheet();
  }

  private openCopy(a: AgentInfo): void {
    this.sheetMode = 'copy';
    this.copyFrom = a.id;
    this.formName = `${this.agentNameOf(a)} Copy`;
    this.formCopyMd = true;
    this.formCopySkills = false;
    this.formCopyJobs = false;
    this.openSheet();
  }

  private openCreate(): void {
    this.sheetMode = 'create';
    this.formName = '';
    this.formId = '';
    this.formDesc = '';
    this.formWorkspace = '';
    this.openSheet();
  }

  private async submitSheet(): Promise<void> {
    if (this.conn === null || this.busy) {
      return;
    }
    const conn: QpConnection = this.conn;
    this.busy = true;
    try {
      if (this.sheetMode === 'profile') {
        const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
        await saveProfile(ctx, {
          id: this.profileAgentId,
          name: this.profileNick.trim(),
          color: this.profileColorPick
        });
        await this.reloadProfiles();
        this.syncHeaderState();
      } else if (this.sheetMode === 'create') {
        const name: string = this.formName.trim();
        if (name.length === 0) {
          this.toast(this.t($r('app.string.agents_form_name')));
          return;
        }
        await createAgent(conn.baseUrl, conn.token, conn.agentId, name, this.formId.trim(),
          this.formDesc.trim(), this.formWorkspace.trim());
        await this.refresh(false);
      } else if (this.sheetMode === 'copy') {
        const name: string = this.formName.trim();
        if (name.length === 0) {
          this.toast(this.t($r('app.string.agents_form_name')));
          return;
        }
        await copyAgent(conn.baseUrl, conn.token, conn.agentId, this.copyFrom, name,
          this.formCopyMd, this.formCopySkills, this.formCopyJobs);
        await this.refresh(false);
      }
      this.closeSheet();
    } catch (e) {
      this.toast((e as Error).message);
    } finally {
      this.busy = false;
    }
  }


  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  // 切换当前智能体 —— 对齐 RN switchAgent 守卫（当前项/切换中不重复触发）
  private async switchAgent(agentId: string): Promise<void> {
    if (this.conn === null || agentId === this.activeAgentId || this.switchingId.length > 0) {
      return;
    }
    this.switchingId = agentId;
    try {
      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      const next: QpConnection = await selectAgent(ctx, this.conn, agentId);
      this.conn = next;
      this.activeAgentId = agentId;
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({
        message: this.t($r('app.string.agents_switch_failed'))
      });
    } finally {
      this.switchingId = '';
    }
  }

  // 列表相位状态机：0=错误 1=未连接 2=首载 3=正常（有数据可渲染节头/行卡）
  private listPhase(): number {
    if (this.error.length > 0) {
      return 0;
    }
    if (this.conn === null) {
      return 1;
    }
    if (this.loading && this.agents.length === 0) {
      return 2;
    }
    return 3;
  }

  // 相位 0/1/2 的面板（错误 / 未连接 / 首载），与列表主体解耦
  @Builder
  phasePanel(phase: number) {
    if (phase === 0) {
      Text(this.error)
        .fontSize(13)
        .fontColor($r('app.color.status_error'))
        .textAlign(TextAlign.Center)
        .padding({ top: 48, left: 32, right: 32 })
        .wordBreak(WordBreak.BREAK_ALL)
    } else if (phase === 1) {
      Text($r('app.string.agents_empty'))
        .fontSize(14)
        .fontColor($r('app.color.text_secondary'))
        .textAlign(TextAlign.Center)
        .padding({ top: 64, left: 40, right: 40 })
        .lineHeight(22)
    } else {
      Text($r('app.string.agents_loading'))
        .fontSize(13)
        .fontColor($r('app.color.text_tertiary'))
        .padding({ top: 32, left: 32, right: 32 })
    }
  }

  // —— 表单 Sheet：创建 / 复制 / 头像昵称（同一 Sheet 三态）——
  @Builder
  manageSheet() {
    Column() {
      Text(this.sheetMode === 'profile' ? $r('app.string.agents_profile_title')
        : (this.sheetMode === 'copy' ? $r('app.string.agents_copy_title')
          : $r('app.string.agents_create_title')))
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .width('100%')
        .margin({ top: 6, bottom: 2 })

      if (this.sheetMode === 'profile') {
        Text($r('app.string.agents_profile_name'))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_secondary'))
          .margin({ top: 12, bottom: 6 })
        TextInput({ text: $$this.profileNick, placeholder: $r('app.string.agents_profile_name') })
          .width('100%')
          .height(44)
          .fontSize(UiTokens.fsBody)
          .backgroundColor($r('app.color.card_bg'))
          .fontColor($r('app.color.input_text'))
          .placeholderColor($r('app.color.placeholder'))
          .borderRadius(12)
        Text($r('app.string.agents_profile_color'))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_secondary'))
          .margin({ top: 16, bottom: 8 })
        Row() {
          ForEach(AVATAR_COLORS, (c: string) => {
            Circle()
              .width(30)
              .height(30)
              .fill(c)
              .stroke(this.profileColorPick === c ? $r('app.color.text_primary_strong') : Color.Transparent)
              .strokeWidth(3)
              .margin({ right: 12 })
              .onClick((): void => {
                this.profileColorPick = this.profileColorPick === c ? '' : c;
              })
          }, (c: string) => c)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
      } else {
        Text($r('app.string.agents_form_name'))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_secondary'))
          .margin({ top: 12, bottom: 6 })
        TextInput({ text: $$this.formName, placeholder: $r('app.string.agents_form_name') })
          .width('100%')
          .height(44)
          .fontSize(UiTokens.fsBody)
          .backgroundColor($r('app.color.card_bg'))
          .fontColor($r('app.color.input_text'))
          .placeholderColor($r('app.color.placeholder'))
          .borderRadius(12)

        if (this.sheetMode === 'create') {
          Text($r('app.string.agents_form_id'))
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_secondary'))
            .margin({ top: 14, bottom: 6 })
          TextInput({ text: $$this.formId, placeholder: $r('app.string.agents_form_id') })
            .width('100%')
            .height(44)
            .fontSize(UiTokens.fsBody)
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.input_text'))
            .placeholderColor($r('app.color.placeholder'))
            .borderRadius(12)
          Text($r('app.string.agents_form_desc'))
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_secondary'))
            .margin({ top: 14, bottom: 6 })
          TextInput({ text: $$this.formDesc, placeholder: $r('app.string.agents_form_desc') })
            .width('100%')
            .height(44)
            .fontSize(UiTokens.fsBody)
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.input_text'))
            .placeholderColor($r('app.color.placeholder'))
            .borderRadius(12)
          Text($r('app.string.agents_form_workspace'))
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_secondary'))
            .margin({ top: 14, bottom: 6 })
          TextInput({ text: $$this.formWorkspace, placeholder: $r('app.string.agents_form_workspace') })
            .width('100%')
            .height(44)
            .fontSize(UiTokens.fsBody)
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.input_text'))
            .placeholderColor($r('app.color.placeholder'))
            .borderRadius(12)
        } else {
          Row() {
            Text($r('app.string.agents_form_copy_md'))
              .fontSize(UiTokens.fsBody)
              .layoutWeight(1)
            Toggle({ type: ToggleType.Switch, isOn: $$this.formCopyMd })
          }
          .width('100%')
          .margin({ top: 16 })
          Row() {
            Text($r('app.string.agents_form_copy_skills'))
              .fontSize(UiTokens.fsBody)
              .layoutWeight(1)
            Toggle({ type: ToggleType.Switch, isOn: $$this.formCopySkills })
          }
          .width('100%')
          .margin({ top: 12 })
          Row() {
            Text($r('app.string.agents_form_copy_jobs'))
              .fontSize(UiTokens.fsBody)
              .layoutWeight(1)
            Toggle({ type: ToggleType.Switch, isOn: $$this.formCopyJobs })
          }
          .width('100%')
          .margin({ top: 12 })
        }
      }

      Row() {
        Button($r('app.string.common_cancel'))
          .layoutWeight(1)
          .height(42)
          .backgroundColor($r('app.color.card_glass'))
          .fontColor($r('app.color.btn_gray_text'))
          .stateEffect(true)
          .onClick((): void => {
            this.closeSheet();
          })
        Button($r('app.string.common_save'))
          .layoutWeight(1)
          .height(42)
          .margin({ left: 10 })
          // 主操作与其余半模态一致走主题色实底（此前未给底色 → 回落系统蓝）
          .backgroundColor(this.isDark ? this.theme.accentDark : this.theme.accent)
          .fontColor(Color.White)
          .enabled(!this.busy)
          .stateEffect(true)
          .onClick((): void => {
            this.submitSheet();
          })
      }
      .width('100%')
      .margin({ top: 20 })
    }
    .width('100%')
    // 顶部留出系统关闭叉（✕）与拖拽条的高度
    .padding({ left: 18, right: 18, top: 64, bottom: 20 })
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    Column() {
      // 整页单一可滚动列表（对齐 RN 内容流 + iOS 大标题式滚动）：
      //   首项 = 标题栏下缘 + 搜索条 + 呼吸边距的占位（用空 item 而非 padding ——
      //          padding 会裁剪列表，内容就滚不到标题栏/搜索条之下，沉浸与渐变模糊也就无从生效）；
      //   次项 = 当前智能体卡，随上滑一起滚走（滚出后名称由标题栏名字胶囊常驻接管）；
      //   其后 = 「全部智能体」节头 + 行卡 + 底部留白。
      Refresh({ refreshing: $$this.refreshing }) {
        List({ scroller: this.scroller }) {
          ListItem() {
            Column()
              .width('100%')
              .height(UiTokens.agentsTopInset)
          }
          if (this.listPhase() < 3) {
            ListItem() {
              this.phasePanel(this.listPhase())
            }
          } else {
            if (this.conn !== null && this.activeAgent() !== null) {
              ListItem() {
                // 卡片壳统一走 GlassCard（含水平留白与上下间距）：gapTop=0 / gapBottom=12 保持不变，
                // 否则会移动首行卡几何、破坏「首行卡碰搜索框」的标题接管判定
                GlassCard({
                  padH: 0,
                  padV: 0,
                  gapTop: 0,
                  gapBottom: 12,
                  onTap: (): void => {
                    const a: AgentInfo | null = this.activeAgent();
                    if (a !== null) {
                      this.openProfile(a);
                    }
                  }
                }) {
                  this.currentCardInner()
                }
              }
            }
            // 「全部智能体」节头：与卡片一起向上滚（对齐 RN 内容流布局）
            ListItem() {
              Row() {
                Text($r('app.string.agents_all'))
                  .fontSize(14)
                  .fontWeight(FontWeight.Bold)
                Text(this.visibleAgents().length.toString())
                  .fontSize(UiTokens.fsChip)
                  .fontColor($r('app.color.tab_faint'))
                  .margin({ left: 7 })
              }
              .width('100%')
              .alignItems(VerticalAlign.Center)
              .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
              // 定高（UiTokens.agentsSectionH，实测自然高即 38vp）：保证「首行卡内容偏移」
              // 几何确定 → 标题接管判定（首行卡碰搜索框）不随字体/内容漂移
              .height(UiTokens.agentsSectionH)
            }
            if (this.agents.length === 0) {
              ListItem() {
                Text($r('app.string.agents_none'))
                  .fontSize(14)
                  .fontColor($r('app.color.text_secondary'))
                  .textAlign(TextAlign.Center)
                  .padding({ top: 32, left: 40, right: 40 })
                  .lineHeight(22)
              }
            } else if (this.visibleAgents().length === 0) {
              ListItem() {
                Column() {
                  Text($r('app.string.agents_search_empty'))
                    .fontSize(17)
                    .fontWeight(FontWeight.Medium)
                  Text($r('app.string.agents_search_empty_copy'))
                    .fontSize(13)
                    .fontColor($r('app.color.text_secondary'))
                    .margin({ top: 6 })
                    .textAlign(TextAlign.Center)
                }
                .width('100%')
                .alignItems(HorizontalAlign.Center)
                .padding({ top: 48, left: 32, right: 32 })
              }
            } else {
              ForEach(this.visibleAgents(), (agent: AgentInfo) => {
                ListItem() {
                  // 卡片壳统一走 GlassCard（含水平留白与上下间距，避免卡片溢出滚动容器）
                  AgentRow({
                    agent: agent,
                    active: agent.id === this.activeAgentId,
                    loading: agent.id === this.switchingId,
                    displayName: this.agentNameOf(agent),
                    avatarColor: this.agentColorOf(agent),
                    accentText: this.isDark ? this.theme.accentDark : this.theme.accent,
                    accentBg: this.isDark ? this.theme.accentBgDark : this.theme.accentBg,
                    onSwitch: () => {
                      this.switchAgent(agent.id);
                    },
                    onEdit: () => {
                      this.openProfile(agent);
                    },
                    menuOf: (a: AgentInfo): MenuElement[] => this.menuOf(a)
                  })
                }
              }, (agent: AgentInfo) => `${agent.id}|${agent.id === this.activeAgentId ? 'cur' : ''}`)
            }
          }
          // 底部留白：滚动到底时末项不被悬浮 tab 栏遮挡
          ListItem() {
            Column()
              .width('100%')
              .height(UiTokens.bottomInset)
          }
        }
        .edgeEffect(EdgeEffect.Spring, { alwaysEnabled: true })
        .scrollBar(BarState.Auto)
        .onDidScroll(() => {
          // 标题栏联动：p = 偏移 0→144vp 映射 0→1（下拉刷新负偏移钳 0）；
          // takeover = 首行卡已碰到搜索框 → Index 把 mainTitle 换成「智能体：名字」（带滑入动画）
          const y: number = this.scroller.currentOffset().yOffset as number;
          const p: number = Math.max(0, Math.min(1, y / UiTokens.agentsHeaderScrollVp));
          const takeover: boolean = UiTokens.nameTakeover(y);
          if (Math.abs(p - this.headerP) >= 0.005 || takeover !== this.headerTakeover) {
            this.headerP = p;
            this.headerTakeover = takeover;
            this.onHeaderState(p, this.agentName(), takeover);
          }
        })
        .width('100%')
        .height('100%')
      }
      .layoutWeight(1)
      .refreshOffset(64)
      .pullToRefresh(true)
      .onRefreshing(() => {
        this.refresh(true);
      })
      .backgroundColor($r('app.color.page_bg'))
    }
    .width('100%')
    .height('100%')
    // 列表从屏幕顶（y=0）起、左右不留白（滚动条贴屏右缘），水平留白改由条目各自承担
    .backgroundColor($r('app.color.page_bg'))
    // 管理与档案表单：创建 / 复制 / 头像昵称（同一 Sheet，三态由 sheetMode 决定）
    .bindSheet(this.sheetShown, this.manageSheet(),
      moduleSheetOptions(540, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  // 当前智能体卡内容（卡片壳 = GlassCard：内容区统一玻璃卡 + 按压弹性/点光源）
  // 进列表随上滑滚走，不再原地收缩/淡出
  @Builder
  currentCardInner() {
    Row() {
      Stack() {
        Circle()
          .fill(this.activeAgent() !== null && this.agentColorOf(this.activeAgent() as AgentInfo).length > 0
            ? this.agentColorOf(this.activeAgent() as AgentInfo)
            : (this.isDark ? this.theme.accentBgDark : this.theme.accentBg))
        Text(this.agentInitial())
          .fontSize(26)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.activeAgent() !== null && this.agentColorOf(this.activeAgent() as AgentInfo).length > 0
            ? Color.White
            : (this.isDark ? this.theme.accentDark : this.theme.accent))
      }
      .width(64)
      .height(64)

      Column() {
        Text($r('app.string.agents_current_eyebrow'))
          .fontSize(UiTokens.fsChip)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
        Text(this.agentName())
          .fontSize(UiTokens.fsTitle)
          .fontWeight(FontWeight.Bold)
          .margin({ top: 4 })
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(this.agentMeta())
          .fontSize(UiTokens.fsChip)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 5 })
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      .margin({ left: 12 })

      Text($r('app.string.agents_connected'))
        .fontSize(10)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
        .backgroundColor(this.isDark ? this.theme.accentBgDark : this.theme.accentBg)
        .borderRadius(12)
        .padding({ left: 8, right: 8, top: 4, bottom: 4 })
    }
    .width('100%')
    .height(108)
    .alignItems(VerticalAlign.Center)
    .padding(16)
  }
}

// 智能体行卡（独立组件：切换 spinner / 「当前」徽标 + 管理入口；卡片壳走 GlassCard）
@Component
export struct AgentRow {
  agent: AgentInfo = { id: '', name: '', description: '', enabled: false,
    pinned: false, startupStatus: '', activeModel: '', backend: '' };
  active: boolean = false;
  loading: boolean = false;
  displayName: string = '';
  avatarColor: string = '';      // 空 = 用主题色底
  accentText: string = '#ff7f16';
  accentBg: string = '#1aff7f16';
  onSwitch: () => void = () => {};
  onEdit: () => void = () => {};
  menuOf: (agent: AgentInfo) => MenuElement[] = (_a: AgentInfo): MenuElement[] => [];
  // 弹出菜单材质（菜单属弹窗类，可在全页面生效；MenuOptions 继承 ContextMenuOptions.systemMaterial）
  agentMenuMaterial: uiMaterial.ImmersiveMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THIN,
    interactive: true
  });

  private nameOf(): string {
    return this.displayName.length > 0 ? this.displayName : this.agent.name;
  }

  private initialOf(): string {
    const n: string = this.nameOf();
    return n.length > 0 ? n.substring(0, 1).toUpperCase() : '?';
  }

  private fallbackDesc(): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync($r('app.string.agents_fallback_desc').id);
    } catch (e) {
      return '';
    }
  }

  build() {
    // 卡片壳统一走 GlassCard（同参数与三页一致：玻璃底 + 圆角 + 按压弹性/点光源）
    GlassCard({
      onTap: (): void => {
        this.onSwitch();
      }
    }) {
      Row() {
      // 头像：点按 = 编辑昵称/头像（对齐 PR 行内头像编辑）
      Stack() {
        Circle()
          .fill(this.avatarColor.length > 0 ? this.avatarColor : this.accentBg)
        Text(this.initialOf())
          .fontSize(18)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.avatarColor.length > 0 ? Color.White : this.accentText)
      }
      .width(46)
      .height(46)
      .onClick((): void => {
        this.onEdit();
      })

      Column() {
        Text(this.nameOf())
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(this.agent.description.length > 0 ? this.agent.description : this.fallbackDesc())
          .fontSize(12)
          .fontColor($r('app.color.text_secondary'))
          .margin({ top: 3 })
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      .margin({ left: 12 })

      if (this.loading) {
        LoadingProgress()
          .width(20)
          .height(20)
          .color(this.accentText)
      } else if (this.active) {
        Text($r('app.string.agents_active_badge'))
          .fontSize(10)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.accentText)
          .backgroundColor(this.accentBg)
          .borderRadius(12)
          .padding({ left: 8, right: 8, top: 4, bottom: 4 })
      }

      // 管理入口（⋯）：内层 Button 承载 bindMenu —— 外层卡片是 Button，
      // 非内建可点击组件（如 Text）的点击会被外层吞掉，故内层也用 Button（内建手势优先）
      Button() {
        Text('⋯')
          .fontSize(20)
          .fontColor($r('app.color.text_tertiary'))
      }
      .type(ButtonType.Normal)
      .width(36)
      .height(36)
      .padding(0)
      .backgroundColor(Color.Transparent)
      .margin({ left: 4 })
      .bindMenu(this.menuOf(this.agent), { systemMaterial: this.agentMenuMaterial })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
  }
}
