/*
 * 工作台模块 · Agent 配置 —— 对齐 PR #7378 features/workbench/AgentSettings.tsx
 *                       + AgentAdvancedSettings.tsx。
 *   GET  /api/agents/{id}                        → 身份 / 审批等级 / 思考等级 / workspace
 *   PUT  /api/agents/{id}                        → 名称、描述、审批等级
 *   PATCH /api/agents/{id}/model-settings        → 思考等级
 *   POST /api/agents/{id}/memory/reindex         → 重建记忆索引
 *   GET/PUT /api/workspace/running-config        → 运行限流 / Shell 上下文 / Memory 压缩
 *   GET/PUT /api/workspace/language              → Agent 语言
 *   GET/PUT /api/config/user-timezone            → 时区
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { OptionsSheet, SheetOption, optionOf } from './OptionsSheet';
import { SheetGate, moduleSheetOptions } from './SheetGate';

// 打开中的编辑器：'' = 无
const EDIT_NONE: string = '';
const EDIT_IDENTITY: string = 'identity';
const EDIT_RUNTIME: string = 'runtime';
const EDIT_CONTEXT: string = 'context';
const EDIT_MEMORY: string = 'memory';
const EDIT_LOCALE: string = 'locale';
const EDIT_APPROVAL: string = 'approval';
const EDIT_THINKING: string = 'thinking';

function recOf(value: Object): Record<string, Object> {
  if (value === null || value === undefined || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, Object>;
}

function numOf(value: Object, fallback: number): number {
  const n: number = Number(value !== undefined && value !== null ? value : fallback);
  return Number.isFinite(n) ? n : fallback;
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

@Component
export struct ModuleAgentConfig {
  @State agentId: string = '';
  @State name: string = '';
  @State description: string = '';
  @State workspaceDir: string = '';
  @State approvalLevel: string = 'AUTO';
  @State thinkingLevel: string = 'inherit';
  @State language: string = 'zh';
  @State timezone: string = 'Asia/Shanghai';
  @State running: Record<string, Object> = {};
  @State hasRunning: boolean = false;
  @State loaded: boolean = false;
  @State error: string = '';
  @State editor: string = EDIT_NONE;
  // 半模态单向绑定（不用 $$）：框架回退动画结束时会回写 isShow，会把随后打开的新面板关掉
  @State sheetShown: boolean = false;
  private gate: SheetGate = new SheetGate();

  // 打开/关闭半模态的唯一入口：目标先落字段，闸门只决定打开时机（回退动画期间排队）
  private openSheet(editor: string): void {
    this.editor = editor;
    if (!this.gate.request()) {
      return;
    }
    this.sheetShown = true;
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }
  private conn: QpConnection | null = null;
  // GET /agents/{id} 的完整原文：审批等级等修改走整表回写（后端 body 必填 id/name，
  // 只送单字段会 422 —— 见下方 saveApproval 注释）
  private profile: Record<string, Object> = {};

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      await this.loadAgent(c);
      await this.loadAdvanced(c);
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private async get(path: string): Promise<Record<string, Object>> {
    const c: QpConnection = this.conn as QpConnection;
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    return jsonOf(resp);
  }

  private async send(method: http.RequestMethod, path: string,
    body: string | null): Promise<Record<string, Object>> {
    const c: QpConnection = this.conn as QpConnection;
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      method, body, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    return jsonOf(resp);
  }

  private async loadAgent(c: QpConnection): Promise<void> {
    const data: Record<string, Object> = await this.get(`/api/agents/${encodeURIComponent(c.agentId)}`);
    this.applyAgent(data);
  }

  private applyAgent(data: Record<string, Object>): void {
    this.profile = data;
    this.agentId = strOf(data['id'], this.agentId);
    this.name = strOf(data['name'], this.name);
    const desc: Object = data['description'];
    this.description = typeof desc === 'string' ? desc as string : '';
    this.workspaceDir = strOf(data['workspace_dir'], '');
    this.approvalLevel = strOf(data['approval_level'], 'AUTO');
    this.thinkingLevel = strOf(data['thinking_level'], 'inherit');
  }

  private async loadAdvanced(c: QpConnection): Promise<void> {
    // 三个接口各自独立：任一失败不影响其余（对齐 7378 Promise.allSettled 口径）
    try {
      const running: Record<string, Object> = await this.get('/api/workspace/running-config');
      this.running = running;
      this.hasRunning = true;
    } catch (e) {
      this.hasRunning = false;
    }
    try {
      const lang: Record<string, Object> = await this.get('/api/workspace/language');
      this.language = strOf(lang['language'], 'zh');
    } catch (e) {
      this.language = 'zh';
    }
    try {
      const tz: Record<string, Object> = await this.get('/api/config/user-timezone');
      this.timezone = strOf(tz['timezone'], 'Asia/Shanghai');
    } catch (e) {
      this.timezone = 'Asia/Shanghai';
    }
  }

  // —— 默认行为 ——

  private approvalOptions(): SheetOption[] {
    return [
      optionOf('STRICT', this.t($r('app.string.module_agent_approval_strict'))),
      optionOf('SMART', this.t($r('app.string.module_agent_approval_smart'))),
      optionOf('AUTO', this.t($r('app.string.module_agent_approval_auto'))),
      optionOf('OFF', this.t($r('app.string.module_agent_approval_off')))
    ];
  }

  private thinkingOptions(): SheetOption[] {
    return [
      optionOf('inherit', this.t($r('app.string.module_agent_think_inherit'))),
      optionOf('off', this.t($r('app.string.module_agent_think_off'))),
      optionOf('low', this.t($r('app.string.module_agent_think_low'))),
      optionOf('medium', this.t($r('app.string.module_agent_think_medium'))),
      optionOf('high', this.t($r('app.string.module_agent_think_high')))
    ];
  }

  // 审批等级走 PUT /agents/{id} 整表回写：该接口 body 必填 id/name（AgentProfileConfig），
  // 只送 { approval_level } 会被拒（实测 HTTP 422 missing id/name），必须带完整 profile 原文。
  private async saveApproval(level: string): Promise<void> {
    const c: QpConnection = this.conn as QpConnection;
    const body: Record<string, Object> = this.copyOf(this.profile);
    body['approval_level'] = level;
    try {
      const data: Record<string, Object> = await this.send(http.RequestMethod.PUT,
        `/api/agents/${encodeURIComponent(c.agentId)}`, JSON.stringify(body));
      this.applyAgent(data);
    } catch (e) {
      this.toast($r('app.string.module_agent_save_failed'));
    }
  }

  // 思考等级走 PATCH /agents/{id}/model-settings（该路由只接受模型类字段，支持单字段）
  private async saveThinking(level: string): Promise<void> {
    const c: QpConnection = this.conn as QpConnection;
    try {
      const data: Record<string, Object> = await this.send(http.RequestMethod.PATCH,
        `/api/agents/${encodeURIComponent(c.agentId)}/model-settings`,
        JSON.stringify({ 'thinking_level': level }));
      this.applyAgent(data);
    } catch (e) {
      this.toast($r('app.string.module_agent_save_failed'));
    }
  }

  private confirmReindex(): void {
    this.getUIContext().showAlertDialog({
      title: this.t($r('app.string.module_agent_reindex_confirm_title')),
      message: this.t($r('app.string.module_agent_reindex_confirm_msg')),
      primaryButton: {
        value: this.t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: this.t($r('app.string.module_agent_reindex_start')),
        action: (): void => {
          this.reindex();
        }
      }
    });
  }

  private async reindex(): Promise<void> {
    const c: QpConnection = this.conn as QpConnection;
    try {
      await this.send(http.RequestMethod.POST,
        `/api/agents/${encodeURIComponent(c.agentId)}/memory/reindex`, null);
      this.alert($r('app.string.module_agent_reindex_started_title'),
        $r('app.string.module_agent_reindex_started_msg'));
    } catch (e) {
      this.alert($r('app.string.module_agent_reindex_failed'), (e as Error).message);
    }
  }

  // —— 高级设置（running-config） ——

  private loop(): Record<string, Object> {
    return recOf(this.running['loop']);
  }

  private iteration(): Record<string, Object> {
    return recOf(this.loop()['iteration']);
  }

  private lightContext(): Record<string, Object> {
    return recOf(this.running['light_context_config']);
  }

  private compact(): Record<string, Object> {
    return recOf(this.lightContext()['context_compact_config']);
  }

  private pruning(): Record<string, Object> {
    return recOf(this.lightContext()['tool_result_pruning_config']);
  }

  private visual(): Record<string, Object> {
    return recOf(this.lightContext()['visual_compact_config']);
  }

  private memory(): Record<string, Object> {
    return recOf(this.running['reme_light_memory_config']);
  }

  private memorySearch(): Record<string, Object> {
    return recOf(this.memory()['auto_memory_search_config']);
  }

  private runtimeDefs(): FieldDef[] {
    return [
      fieldDef('iteration_enabled', this.t($r('app.string.module_agent_f_iter_enabled')), 'boolean'),
      fieldDef('max_iterations', this.t($r('app.string.module_agent_f_max_iterations')), 'number', true),
      fieldDef('llm_retry_enabled', this.t($r('app.string.module_agent_f_retry_enabled')), 'boolean'),
      fieldDef('llm_max_retries', this.t($r('app.string.module_agent_f_max_retries')), 'number', true),
      fieldDef('llm_backoff_base', this.t($r('app.string.module_agent_f_backoff_base')), 'number', true),
      fieldDef('llm_backoff_cap', this.t($r('app.string.module_agent_f_backoff_cap')), 'number', true),
      fieldDef('llm_max_concurrent', this.t($r('app.string.module_agent_f_max_concurrent')), 'number', true),
      fieldDef('llm_max_qpm', this.t($r('app.string.module_agent_f_max_qpm')), 'number', true),
      fieldDef('llm_acquire_timeout', this.t($r('app.string.module_agent_f_acquire_timeout')), 'number', true)
    ];
  }

  private contextDefs(): FieldDef[] {
    const effort: FieldDef = fieldDef('visual_compact_effort',
      this.t($r('app.string.module_agent_f_visual_effort')), 'select', false, '', '',
      ['low', 'medium', 'high']);
    effort.defText = 'low';
    return [
      fieldDef('shell_command_timeout', this.t($r('app.string.module_agent_f_shell_timeout')), 'number', true),
      fieldDef('shell_command_executable', this.t($r('app.string.module_agent_f_shell_exec')), 'text'),
      fieldDef('max_input_length', this.t($r('app.string.module_agent_f_max_input')), 'number', true),
      fieldDef('history_max_length', this.t($r('app.string.module_agent_f_history_max')), 'number', true),
      fieldDef('context_compact_enabled', this.t($r('app.string.module_agent_f_compact_enabled')), 'boolean'),
      fieldDef('compact_threshold_ratio', this.t($r('app.string.module_agent_f_compact_ratio')), 'number', true),
      fieldDef('tool_pruning_enabled', this.t($r('app.string.module_agent_f_pruning_enabled')), 'boolean'),
      fieldDef('pruning_recent_n', this.t($r('app.string.module_agent_f_pruning_n')), 'number', true),
      fieldDef('visual_compact_enabled', this.t($r('app.string.module_agent_f_visual_enabled')), 'boolean'),
      effort
    ];
  }

  private memoryDefs(): FieldDef[] {
    const backend: FieldDef = fieldDef('memory_manager_backend',
      this.t($r('app.string.module_agent_f_mem_backend')), 'select', false, '', '',
      ['remelight', 'adbpg']);
    backend.defText = 'remelight';
    return [
      backend,
      fieldDef('auto_memory_interval', this.t($r('app.string.module_agent_f_mem_interval')), 'number', true),
      fieldDef('memory_search_enabled', this.t($r('app.string.module_agent_f_mem_search')), 'boolean'),
      fieldDef('auto_search_enabled', this.t($r('app.string.module_agent_f_auto_search')), 'boolean'),
      fieldDef('auto_search_max_results', this.t($r('app.string.module_agent_f_auto_search_max')), 'number', true),
      fieldDef('dream_cron_enabled', this.t($r('app.string.module_agent_f_dream_enabled')), 'boolean'),
      fieldDef('dream_cron', this.t($r('app.string.module_agent_f_dream_cron')), 'text'),
      fieldDef('daily_paper_cron_enabled', this.t($r('app.string.module_agent_f_paper_enabled')), 'boolean'),
      fieldDef('daily_paper_cron', this.t($r('app.string.module_agent_f_paper_cron')), 'text'),
      fieldDef('daily_paper_topics', this.t($r('app.string.module_agent_f_paper_topics')), 'textarea')
    ];
  }

  private localeDefs(): FieldDef[] {
    const lang: FieldDef = fieldDef('language', this.t($r('app.string.module_agent_f_language')), 'select',
      false, '', '', ['zh', 'en', 'id', 'ru']);
    lang.defText = 'zh';
    return [
      lang,
      fieldDef('timezone', this.t($r('app.string.module_agent_f_timezone')), 'text', true, 'Asia/Shanghai')
    ];
  }

  private identityDefs(): FieldDef[] {
    const desc: FieldDef = fieldDef('description', this.t($r('app.string.module_agent_form_desc')), 'textarea',
      false, this.t($r('app.string.module_agent_form_desc_ph')));
    return [
      fieldDef('name', this.t($r('app.string.module_agent_form_name')), 'text', true),
      desc
    ];
  }

  private initialValues(): Record<string, Object> {
    const out: Record<string, Object> = {};
    if (this.editor === EDIT_IDENTITY) {
      out['name'] = this.name;
      out['description'] = this.description;
    } else if (this.editor === EDIT_RUNTIME) {
      out['iteration_enabled'] = this.iteration()['enabled'] === true;
      out['max_iterations'] = numOf(this.iteration()['max_iterations'],
        numOf(this.running['max_iters'], 0));
      out['llm_retry_enabled'] = this.running['llm_retry_enabled'] === true;
      out['llm_max_retries'] = numOf(this.running['llm_max_retries'], 0);
      out['llm_backoff_base'] = numOf(this.running['llm_backoff_base'], 0);
      out['llm_backoff_cap'] = numOf(this.running['llm_backoff_cap'], 0);
      out['llm_max_concurrent'] = numOf(this.running['llm_max_concurrent'], 0);
      out['llm_max_qpm'] = numOf(this.running['llm_max_qpm'], 0);
      out['llm_acquire_timeout'] = numOf(this.running['llm_acquire_timeout'], 0);
    } else if (this.editor === EDIT_CONTEXT) {
      out['shell_command_timeout'] = numOf(this.running['shell_command_timeout'], 0);
      out['shell_command_executable'] = strOf(this.running['shell_command_executable'], '');
      out['max_input_length'] = numOf(this.running['max_input_length'], 0);
      out['history_max_length'] = numOf(this.running['history_max_length'], 0);
      out['context_compact_enabled'] = this.compact()['enabled'] === true;
      out['compact_threshold_ratio'] = numOf(this.compact()['compact_threshold_ratio'], 0);
      out['tool_pruning_enabled'] = this.pruning()['enabled'] === true;
      out['pruning_recent_n'] = numOf(this.pruning()['pruning_recent_n'], 0);
      out['visual_compact_enabled'] = this.visual()['enabled'] === true;
      out['visual_compact_effort'] = strOf(this.visual()['effort'], 'low');
    } else if (this.editor === EDIT_MEMORY) {
      out['memory_manager_backend'] = strOf(this.running['memory_manager_backend'], 'remelight');
      out['auto_memory_interval'] = numOf(this.memory()['auto_memory_interval'], 0);
      out['memory_search_enabled'] = this.memory()['memory_search_enabled'] === true;
      out['auto_search_enabled'] = this.memorySearch()['enabled'] === true;
      out['auto_search_max_results'] = numOf(this.memorySearch()['max_results'], 0);
      out['dream_cron_enabled'] = this.memory()['dream_cron_enabled'] === true;
      out['dream_cron'] = strOf(this.memory()['dream_cron'], '');
      out['daily_paper_cron_enabled'] = this.memory()['daily_paper_cron_enabled'] === true;
      out['daily_paper_cron'] = strOf(this.memory()['daily_paper_cron'], '');
      out['daily_paper_topics'] = strOf(this.memory()['daily_paper_topics'], '');
    } else {
      out['language'] = this.language;
      out['timezone'] = this.timezone;
    }
    return out;
  }

  private defsFor(editor: string): FieldDef[] {
    if (editor === EDIT_IDENTITY) {
      return this.identityDefs();
    }
    if (editor === EDIT_RUNTIME) {
      return this.runtimeDefs();
    }
    if (editor === EDIT_CONTEXT) {
      return this.contextDefs();
    }
    if (editor === EDIT_MEMORY) {
      return this.memoryDefs();
    }
    return this.localeDefs();
  }

  private titleFor(editor: string): string {
    if (editor === EDIT_IDENTITY) {
      return this.t($r('app.string.module_agent_edit_title'));
    }
    if (editor === EDIT_RUNTIME) {
      return this.t($r('app.string.module_agent_loop'));
    }
    if (editor === EDIT_CONTEXT) {
      return this.t($r('app.string.module_agent_shell'));
    }
    if (editor === EDIT_MEMORY) {
      return this.t($r('app.string.module_agent_mem_row'));
    }
    return this.t($r('app.string.module_agent_g_locale'));
  }

  private async save(values: Record<string, Object>): Promise<void> {
    const c: QpConnection = this.conn as QpConnection;
    if (this.editor === EDIT_IDENTITY) {
      const body: Record<string, Object> = {
        'name': strOf(values['name'], '').trim(),
        'description': strOf(values['description'], '').trim()
      };
      this.applyAgent(await this.send(http.RequestMethod.PUT,
        `/api/agents/${encodeURIComponent(c.agentId)}`, JSON.stringify(body)));
      return;
    }
    if (this.editor === EDIT_LOCALE) {
      await this.send(http.RequestMethod.PUT, '/api/workspace/language',
        JSON.stringify({ 'language': strOf(values['language'], 'zh') }));
      await this.send(http.RequestMethod.PUT, '/api/config/user-timezone',
        JSON.stringify({ 'timezone': strOf(values['timezone'], '').trim() }));
      await this.loadAdvanced(c);
      return;
    }
    // 运行限流 / Shell 上下文 / Memory：整表回写 running-config（保持未编辑字段原值）
    const next: Record<string, Object> = {};
    for (const k of Object.keys(this.running)) {
      next[k] = this.running[k];
    }
    if (this.editor === EDIT_RUNTIME) {
      next['llm_retry_enabled'] = values['llm_retry_enabled'] === true;
      next['llm_max_retries'] = values['llm_max_retries'];
      next['llm_backoff_base'] = values['llm_backoff_base'];
      next['llm_backoff_cap'] = values['llm_backoff_cap'];
      next['llm_max_concurrent'] = values['llm_max_concurrent'];
      next['llm_max_qpm'] = values['llm_max_qpm'];
      next['llm_acquire_timeout'] = values['llm_acquire_timeout'];
      const loop: Record<string, Object> = this.copyOf(this.loop());
      const iteration: Record<string, Object> = this.copyOf(this.iteration());
      iteration['enabled'] = values['iteration_enabled'] === true;
      iteration['max_iterations'] = values['max_iterations'];
      loop['iteration'] = iteration;
      next['loop'] = loop;
    } else if (this.editor === EDIT_CONTEXT) {
      next['shell_command_timeout'] = values['shell_command_timeout'];
      next['shell_command_executable'] = values['shell_command_executable'];
      next['max_input_length'] = values['max_input_length'];
      next['history_max_length'] = values['history_max_length'];
      const light: Record<string, Object> = this.copyOf(this.lightContext());
      const compact: Record<string, Object> = this.copyOf(this.compact());
      compact['enabled'] = values['context_compact_enabled'] === true;
      compact['compact_threshold_ratio'] = values['compact_threshold_ratio'];
      const pruning: Record<string, Object> = this.copyOf(this.pruning());
      pruning['enabled'] = values['tool_pruning_enabled'] === true;
      pruning['pruning_recent_n'] = values['pruning_recent_n'];
      const visual: Record<string, Object> = this.copyOf(this.visual());
      visual['enabled'] = values['visual_compact_enabled'] === true;
      visual['effort'] = values['visual_compact_effort'];
      light['context_compact_config'] = compact;
      light['tool_result_pruning_config'] = pruning;
      light['visual_compact_config'] = visual;
      next['light_context_config'] = light;
    } else if (this.editor === EDIT_MEMORY) {
      next['memory_manager_backend'] = values['memory_manager_backend'];
      const memory: Record<string, Object> = this.copyOf(this.memory());
      memory['auto_memory_interval'] = values['auto_memory_interval'];
      memory['memory_search_enabled'] = values['memory_search_enabled'] === true;
      memory['dream_cron_enabled'] = values['dream_cron_enabled'] === true;
      memory['dream_cron'] = values['dream_cron'];
      memory['daily_paper_cron_enabled'] = values['daily_paper_cron_enabled'] === true;
      memory['daily_paper_cron'] = values['daily_paper_cron'];
      memory['daily_paper_topics'] = values['daily_paper_topics'];
      const search: Record<string, Object> = this.copyOf(this.memorySearch());
      search['enabled'] = values['auto_search_enabled'] === true;
      search['max_results'] = values['auto_search_max_results'];
      memory['auto_memory_search_config'] = search;
      next['reme_light_memory_config'] = memory;
    }
    this.running = await this.send(http.RequestMethod.PUT, '/api/workspace/running-config',
      JSON.stringify(next));
    this.hasRunning = true;
  }

  private copyOf(src: Record<string, Object>): Record<string, Object> {
    const out: Record<string, Object> = {};
    for (const k of Object.keys(src)) {
      out[k] = src[k];
    }
    return out;
  }

  private approvalLabel(value: string): string {
    if (value === 'STRICT') {
      return this.t($r('app.string.module_agent_approval_strict'));
    }
    if (value === 'SMART') {
      return this.t($r('app.string.module_agent_approval_smart'));
    }
    if (value === 'OFF') {
      return this.t($r('app.string.module_agent_approval_off'));
    }
    return this.t($r('app.string.module_agent_approval_auto'));
  }

  private thinkingLabel(value: string): string {
    if (value === 'off') {
      return this.t($r('app.string.module_agent_think_off'));
    }
    if (value === 'low') {
      return this.t($r('app.string.module_agent_think_low'));
    }
    if (value === 'medium') {
      return this.t($r('app.string.module_agent_think_medium'));
    }
    if (value === 'high') {
      return this.t($r('app.string.module_agent_think_high'));
    }
    return this.t($r('app.string.module_agent_think_inherit'));
  }

  private languageLabel(value: string): string {
    if (value === 'zh') {
      return '中文';
    }
    if (value === 'en') {
      return 'English';
    }
    if (value === 'id') {
      return 'Bahasa Indonesia';
    }
    if (value === 'ru') {
      return 'Русский';
    }
    return value;
  }

  private alert(title: Resource, message: Resource | string): void {
    this.getUIContext().showAlertDialog({
      title: title,
      message: message,
      confirm: {
        value: this.t($r('app.string.common_confirm')),
        action: (): void => {}
      }
    });
  }

  private toast(res: Resource): void {
    this.getUIContext().getPromptAction().showToast({ message: this.t(res) });
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  private fill(pattern: string, value: string): string {
    return pattern.replace('%d', value);
  }

  // 菜单高度：单选项少 → 矮半模态；表单字段多 → 高半模态
  private sheetHeight(): number {
    return (this.editor === EDIT_APPROVAL || this.editor === EDIT_THINKING) ? 400 : 640;
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.editor === EDIT_APPROVAL) {
        OptionsSheet({
          title: this.t($r('app.string.module_agent_approval')),
          options: this.approvalOptions(),
          current: this.approvalLevel,
          onPick: (value: string): void => {
            this.saveApproval(value);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else if (this.editor === EDIT_THINKING) {
        OptionsSheet({
          title: this.t($r('app.string.module_agent_thinking')),
          options: this.thinkingOptions(),
          current: this.thinkingLevel,
          onPick: (value: string): void => {
            this.saveThinking(value);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else {
        FieldSheet({
          title: this.titleFor(this.editor),
          defs: this.defsFor(this.editor),
          initial: this.initialValues(),
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.save(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      }
    }
    .width('100%')
    .height('100%')
  }

  build() {
    Column() {
      if (this.error.length > 0) {
        ModuleError(this.error, (): void => {
          this.load();
        })
      } else if (!this.loaded) {
        ModuleLoading(this.t($r('app.string.module_loading')))
      } else {
        IosGroup({ title: this.t($r('app.string.module_agent_identity')) }) {
          IosRow({
            icon: $r('sys.symbol.person'),
            label: this.name,
            subtitle: this.description.length > 0 ? this.description
              : this.t($r('app.string.module_agent_no_desc')),
            trailing: this.agentId,
            tappable: true,
            onPress: (): void => {
              this.openSheet(EDIT_IDENTITY);
            }
          })
          IosRow({
            icon: $r('sys.symbol.square_and_pencil'),
            label: this.t($r('app.string.module_agent_edit')),
            tappable: true,
            onPress: (): void => {
              this.openSheet(EDIT_IDENTITY);
            }
          })
        }
        IosGroup({ title: this.t($r('app.string.module_agent_defaults')) }) {
          IosRow({
            icon: $r('sys.symbol.gauge_with_dots_needle_33percent'),
            label: this.t($r('app.string.module_agent_approval')),
            subtitle: this.t($r('app.string.module_agent_approval_hint')),
            trailing: this.approvalLabel(this.approvalLevel),
            tappable: true,
            onPress: (): void => {
              this.openSheet(EDIT_APPROVAL);
            }
          })
          IosRow({
            icon: $r('sys.symbol.lightbulb'),
            label: this.t($r('app.string.module_agent_thinking')),
            subtitle: this.t($r('app.string.module_agent_thinking_hint')),
            trailing: this.thinkingLabel(this.thinkingLevel),
            tappable: true,
            onPress: (): void => {
              this.openSheet(EDIT_THINKING);
            }
          })
        }
        IosGroup({ title: this.t($r('app.string.module_agent_memory')) }) {
          IosRow({
            icon: $r('sys.symbol.arrow_2_circlepath'),
            label: this.t($r('app.string.module_agent_reindex')),
            subtitle: this.t($r('app.string.module_agent_reindex_hint')),
            tappable: true,
            onPress: (): void => {
              this.confirmReindex();
            }
          })
        }
        if (this.hasRunning) {
          IosGroup({ title: this.t($r('app.string.module_agent_g_runtime')) }) {
            IosRow({
              icon: $r('sys.symbol.bolt'),
              label: this.t($r('app.string.module_agent_loop')),
              subtitle: this.fill(this.t($r('app.string.module_agent_loop_hint')),
                `${numOf(this.iteration()['max_iterations'], numOf(this.running['max_iters'], 0))}`)
                .replace('%m', `${numOf(this.running['llm_max_retries'], 0)}`),
              tappable: true,
              onPress: (): void => {
                this.openSheet(EDIT_RUNTIME);
              }
            })
            IosRow({
              icon: $r('sys.symbol.doc_text'),
              label: this.t($r('app.string.module_agent_shell')),
              subtitle: this.fill(this.t($r('app.string.module_agent_shell_hint')),
                `${numOf(this.running['shell_command_timeout'], 0)}`)
                .replace('%m', `${numOf(this.running['max_input_length'], 0)}`),
              tappable: true,
              onPress: (): void => {
                this.openSheet(EDIT_CONTEXT);
              }
            })
          }
          IosGroup({ title: this.t($r('app.string.module_agent_g_memory_view')) }) {
            IosRow({
              icon: $r('sys.symbol.list_book'),
              label: this.t($r('app.string.module_agent_mem_row')),
              subtitle: this.fill(this.t($r('app.string.module_agent_mem_hint')),
                `${numOf(this.memory()['auto_memory_interval'], 0)}`)
                .replace('%b', strOf(this.running['memory_manager_backend'], 'remelight')),
              tappable: true,
              onPress: (): void => {
                this.openSheet(EDIT_MEMORY);
              }
            })
          }
          IosGroup({ title: this.t($r('app.string.module_agent_g_locale')) }) {
            IosRow({
              icon: $r('sys.symbol.translate'),
              label: this.languageLabel(this.language),
              subtitle: this.t($r('app.string.module_agent_lang_hint')),
              trailing: this.timezone,
              tappable: true,
              onPress: (): void => {
                this.openSheet(EDIT_LOCALE);
              }
            })
          }
        }
        ModuleFooter(this.workspaceDir.length > 0 ? this.workspaceDir
          : this.t($r('app.string.module_agent_workspace')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(this.sheetHeight(), this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }
}
