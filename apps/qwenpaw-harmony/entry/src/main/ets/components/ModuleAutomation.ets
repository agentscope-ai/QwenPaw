/*
 * 工作台模块 · Cron 与 Heartbeat —— 对齐 PR #7378 features/workbench/AutomationSettings.tsx。
 *   GET  /api/cron/jobs                          → 定时任务列表
 *   POST /api/cron/jobs                          新建；PUT /api/cron/jobs/{id} 更新；DELETE 删除
 *   POST /api/cron/jobs/{id}/{run|pause|resume}  立即运行 / 暂停 / 恢复
 *   GET  /api/cron/jobs/{id}/history             最近运行记录
 *   GET  /api/cron/dispatch-targets              可投递目标（channel · user_id · session_id）
 *   GET/PUT /api/config/heartbeat                心跳配置；POST /api/config/heartbeat/run 立即唤醒
 * 任务下发对象嵌套形状（schedule / request / dispatch / runtime）逐条对齐 7378，避免整表覆盖丢字段。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';

const DEFAULT_TIMEOUT: number = 120;

class CronJob {
  id: string = '';
  name: string = '';
  enabled: boolean = true;
  scheduleType: string = 'cron';
  cron: string = '';
  runAt: string = '';
  timezone: string = 'UTC';
  repeatEveryDays: number = 0;
  taskType: string = 'agent';
  content: string = '';
  dispatchChannel: string = 'console';
  dispatchUserId: string = 'mobile';
  dispatchSessionId: string = '';
  saveResultToInbox: boolean = true;
  timeoutSeconds: number = DEFAULT_TIMEOUT;
}

class DispatchTarget {
  channel: string = '';
  userId: string = '';
  sessionId: string = '';
}

// 心跳活跃时段（可空 = 不限制时段）
class ActiveHours {
  start: string = '';
  end: string = '';
}

class HeartbeatBody {
  enabled: boolean = false;
  every: string = '';
  target: string = '';
  timeoutSeconds: number = 0;
  activeHours: ActiveHours | null = null;
}

function recOf(value: Object): Record<string, Object> {
  if (value === null || value === undefined || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, Object>;
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

function numOf(value: Object, fallback: number): number {
  const n: number = Number(value !== undefined && value !== null ? value : fallback);
  return Number.isFinite(n) ? n : fallback;
}

@Component
export struct ModuleAutomation {
  @State jobs: CronJob[] = [];
  @State hasJobs: boolean = false;
  @State hasHeartbeat: boolean = false;
  @State hbEnabled: boolean = false;
  @State hbEvery: string = '';
  @State hbTarget: string = '';
  @State hbTimeout: number = 0;
  @State hbStart: string = '';
  @State hbEnd: string = '';
  @State targets: DispatchTarget[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State editor: string = '';
  @State sheetShown: boolean = false;
  // 半模态单向绑定（不用 $$）：框架回退动画结束时会回写 isShow，会把随后打开的新面板关掉
  private gate: SheetGate = new SheetGate();

  // 打开 / 关闭半模态唯一入口：目标字段已先置好，闸门只决定打开时机（回退动画期间排队）
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

  @State editingJob: string = '';
  private jobsRaw: Record<string, Object>[] = [];
  private conn: QpConnection | null = null;

  aboutToAppear(): void {
    this.load();
  }

  private async connect(): Promise<QpConnection | null> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    return await loadConnection(ctx);
  }

  private async get(path: string): Promise<Object> {
    const c: QpConnection = this.conn as QpConnection;
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    return resp.result as Object;
  }

  private async getJson(path: string): Promise<Record<string, Object>> {
    const c: QpConnection = this.conn as QpConnection;
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    return jsonOf(resp);
  }

  private async mutate(method: http.RequestMethod, path: string,
    body: string | null): Promise<Object> {
    const c: QpConnection = this.conn as QpConnection;
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      method, body, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    return resp.result as Object;
  }

  private async load(): Promise<void> {
    const c: QpConnection | null = await this.connect();
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    // 三路各自独立取值：任一失败不影响其余（对齐 7378 allSettled 口径）
    let jobsFailed: boolean = false;
    let hbFailed: boolean = false;
    try {
      const raw: Object = await this.get('/api/cron/jobs');
      const list: CronJob[] = [];
      const raws: Record<string, Object>[] = [];
      if (Array.isArray(raw)) {
        for (const item of raw as Object[]) {
          const rec: Record<string, Object> = recOf(item);
          raws.push(rec);
          list.push(this.parseJob(rec));
        }
      }
      this.jobsRaw = raws;
      this.jobs = list;
      this.hasJobs = true;
    } catch (e) {
      jobsFailed = true;
      this.jobs = [];
      this.jobsRaw = [];
      this.hasJobs = true;
    }
    try {
      const hb: Record<string, Object> = await this.getJson('/api/config/heartbeat');
      this.applyHeartbeat(hb);
      this.hasHeartbeat = true;
    } catch (e) {
      hbFailed = true;
      this.hasHeartbeat = false;
    }
    try {
      const t: Record<string, Object> = await this.getJson('/api/cron/dispatch-targets');
      const items: Object = t['items'];
      const out: DispatchTarget[] = [];
      if (Array.isArray(items)) {
        for (const item of items as Object[]) {
          const rec: Record<string, Object> = recOf(item);
          const d: DispatchTarget = new DispatchTarget();
          d.channel = strOf(rec['channel'], '');
          d.userId = strOf(rec['user_id'], '');
          d.sessionId = strOf(rec['session_id'], '');
          out.push(d);
        }
      }
      this.targets = out;
    } catch (e) {
      this.targets = [];
    }
    this.error = (jobsFailed && hbFailed) ? this.t($r('app.string.module_auto_read_failed')) : '';
    this.loaded = true;
  }

  private applyHeartbeat(hb: Record<string, Object>): void {
    this.hbEnabled = hb['enabled'] === true;
    this.hbEvery = strOf(hb['every'], '');
    this.hbTarget = strOf(hb['target'], '');
    this.hbTimeout = numOf(hb['timeoutSeconds'], 0);
    const hours: Object = hb['activeHours'];
    if (hours !== null && hours !== undefined && typeof hours === 'object') {
      const rec: Record<string, Object> = hours as Record<string, Object>;
      this.hbStart = strOf(rec['start'], '');
      this.hbEnd = strOf(rec['end'], '');
    } else {
      this.hbStart = '';
      this.hbEnd = '';
    }
  }

  private parseJob(rec: Record<string, Object>): CronJob {
    const job: CronJob = new CronJob();
    job.id = strOf(rec['id'], '');
    job.name = strOf(rec['name'], '');
    job.enabled = rec['enabled'] !== false;
    const schedule: Record<string, Object> = recOf(rec['schedule']);
    job.scheduleType = strOf(schedule['type'], 'cron') === 'once' ? 'once' : 'cron';
    job.cron = strOf(schedule['cron'], '');
    job.runAt = strOf(schedule['run_at'], '');
    job.timezone = strOf(schedule['timezone'], 'UTC');
    job.repeatEveryDays = numOf(schedule['repeat_every_days'], 0);
    job.taskType = strOf(rec['task_type'], 'agent') === 'text' ? 'text' : 'agent';
    const dispatch: Record<string, Object> = recOf(rec['dispatch']);
    job.dispatchChannel = strOf(dispatch['channel'], 'console');
    const target: Record<string, Object> = recOf(dispatch['target']);
    job.dispatchUserId = strOf(target['user_id'], 'mobile');
    job.dispatchSessionId = strOf(target['session_id'], '');
    job.saveResultToInbox = rec['save_result_to_inbox'] !== false;
    const runtime: Record<string, Object> = recOf(rec['runtime']);
    job.timeoutSeconds = numOf(runtime['timeout_seconds'], DEFAULT_TIMEOUT);
    // 任务内容：文本任务取 text；Agent 任务取 request.input[0].content[].text（对齐 7378 jobFormValues）
    if (job.taskType === 'text') {
      job.content = strOf(rec['text'], '');
    } else {
      const request: Record<string, Object> = recOf(rec['request']);
      const input: Object = request['input'];
      let content: string = '';
      if (Array.isArray(input) && (input as Object[]).length > 0) {
        const first: Record<string, Object> = recOf((input as Object[])[0]);
        const parts: Object = first['content'];
        if (Array.isArray(parts)) {
          const texts: string[] = [];
          for (const part of parts as Object[]) {
            texts.push(strOf(recOf(part)['text'], ''));
          }
          content = texts.join('\n');
        }
      }
      job.content = content;
    }
    return job;
  }

  private scheduleLabel(rec: Record<string, Object>): string {
    const schedule: Object = rec['schedule'];
    if (schedule === null || schedule === undefined || typeof schedule !== 'object') {
      return this.t($r('app.string.module_auto_no_schedule'));
    }
    const s: Record<string, Object> = schedule as Record<string, Object>;
    const cron: Object = s['cron'];
    if (typeof cron === 'string' && (cron as string).length > 0) {
      return cron as string;
    }
    const runAt: Object = s['run_at'];
    if (typeof runAt === 'string' && (runAt as string).length > 0) {
      return runAt as string;
    }
    return this.t($r('app.string.module_auto_server_schedule'));
  }

  private rawOf(id: string): Record<string, Object> {
    for (const rec of this.jobsRaw) {
      if (strOf(rec['id'], '') === id) {
        return rec;
      }
    }
    return {};
  }

  // —— Heartbeat ——

  private async runHeartbeat(): Promise<void> {
    try {
      await this.mutate(http.RequestMethod.POST, '/api/config/heartbeat/run', null);
      this.alert($r('app.string.module_auto_hb_started_title'), $r('app.string.module_auto_hb_started_msg'));
    } catch (e) {
      this.alert($r('app.string.module_auto_start_failed'), (e as Error).message);
    }
  }

  private hbDefs(): FieldDef[] {
    const target: FieldDef = fieldDef('target', this.t($r('app.string.module_auto_f_hb_target')), 'select',
      false, '', '', ['main', 'last', 'inbox']);
    target.defText = 'main';
    return [
      fieldDef('enabled', this.t($r('app.string.module_auto_f_hb_enabled')), 'switch'),
      fieldDef('every', this.t($r('app.string.module_auto_f_hb_every')), 'text', true, '6h 或 30m'),
      target,
      fieldDef('timeoutSeconds', this.t($r('app.string.module_auto_f_hb_timeout')), 'number', true),
      fieldDef('activeHoursStart', this.t($r('app.string.module_auto_f_hb_start')), 'text', false, '08:00'),
      fieldDef('activeHoursEnd', this.t($r('app.string.module_auto_f_hb_end')), 'text', false, '22:00')
    ];
  }

  private async saveHeartbeat(values: Record<string, Object>): Promise<void> {
    const start: string = strOf(values['activeHoursStart'], '').trim();
    const end: string = strOf(values['activeHoursEnd'], '').trim();
    const body: HeartbeatBody = new HeartbeatBody();
    body.enabled = values['enabled'] === true;
    body.every = strOf(values['every'], '');
    body.target = strOf(values['target'], 'main');
    body.timeoutSeconds = numOf(values['timeoutSeconds'], 0);
    // 起止都填才算限制时段，否则显式置空（对齐 7378 activeHours: null）
    if (start.length > 0 && end.length > 0) {
      const hours: ActiveHours = new ActiveHours();
      hours.start = start;
      hours.end = end;
      body.activeHours = hours;
    }
    await this.mutate(http.RequestMethod.PUT, '/api/config/heartbeat', JSON.stringify(body));
    await this.load();
  }

  // —— Cron Job 操作 ——

  private async jobCommand(job: CronJob, action: string): Promise<void> {
    try {
      await this.mutate(http.RequestMethod.POST,
        `/api/cron/jobs/${encodeURIComponent(job.id)}/${action}`, null);
      await this.load();
    } catch (e) {
      this.alert($r('app.string.module_auto_op_failed'), (e as Error).message);
    }
  }

  private async showHistory(job: CronJob): Promise<void> {
    try {
      const raw: Object = await this.get(`/api/cron/jobs/${encodeURIComponent(job.id)}/history`);
      const lines: string[] = [];
      if (Array.isArray(raw)) {
        const records: Object[] = raw as Object[];
        for (const item of records.slice(0, 8)) {
          const rec: Record<string, Object> = recOf(item);
          const status: string = strOf(rec['status'], 'unknown');
          const runAt: string = strOf(rec['run_at'], '');
          const err: string = strOf(rec['error'], '');
          lines.push(err.length > 0 ? `${status} · ${runAt}\n${err}` : `${status} · ${runAt}`);
        }
      }
      if (lines.length === 0) {
        this.alert(this.historyTitle(job.name), $r('app.string.module_auto_history_empty'));
      } else {
        this.alert(this.historyTitle(job.name), lines.join('\n\n'));
      }
    } catch (e) {
      this.alert($r('app.string.module_auto_read_failed'), (e as Error).message);
    }
  }

  private confirmDelete(job: CronJob): void {
    this.getUIContext().showAlertDialog({
      title: this.t($r('app.string.module_auto_delete_title')),
      message: job.name,
      primaryButton: {
        value: this.t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: this.t($r('app.string.module_delete')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.deleteJob(job);
        }
      }
    });
  }

  private async deleteJob(job: CronJob): Promise<void> {
    try {
      await this.mutate(http.RequestMethod.DELETE,
        `/api/cron/jobs/${encodeURIComponent(job.id)}`, null);
      await this.load();
    } catch (e) {
      this.alert($r('app.string.module_auto_delete_failed'), (e as Error).message);
    }
  }

  // 任务操作菜单（操作类，不是单选）→ 下拉菜单，项目既有菜单契约
  private jobMenu(job: CronJob): MenuElement[] {
    const items: MenuElement[] = [];
    items.push({
      value: $r('app.string.module_auto_run_now'),
      action: (): void => {
        this.jobCommand(job, 'run');
      }
    });
    items.push({
      value: job.enabled ? $r('app.string.module_auto_pause') : $r('app.string.module_auto_resume'),
      action: (): void => {
        this.jobCommand(job, job.enabled ? 'pause' : 'resume');
      }
    });
    items.push({
      value: $r('app.string.module_auto_history'),
      action: (): void => {
        this.showHistory(job);
      }
    });
    items.push({
      value: $r('app.string.module_edit'),
      action: (): void => {
        this.editingJob = job.id;
        this.editor = 'job';
        this.openSheet();
      }
    });
    items.push({
      value: $r('app.string.module_delete'),
      action: (): void => {
        this.confirmDelete(job);
      }
    });
    return items;
  }

  // —— 任务编辑表单 ——

  private jobDefs(): FieldDef[] {
    const schedule: FieldDef = fieldDef('schedule_type', this.t($r('app.string.module_auto_f_job_schedule')),
      'select', false, '', '', ['cron', 'once']);
    schedule.defText = 'cron';
    const taskType: FieldDef = fieldDef('task_type', this.t($r('app.string.module_auto_f_job_type')),
      'select', false, '', '', ['agent', 'text']);
    taskType.defText = 'agent';
    const defs: FieldDef[] = [
      fieldDef('name', this.t($r('app.string.module_auto_f_job_name')), 'text', true),
      fieldDef('enabled', this.t($r('app.string.module_auto_f_job_enabled')), 'switch'),
      schedule,
      fieldDef('cron', this.t($r('app.string.module_auto_f_job_cron')), 'text', false, '0 9 * * *'),
      fieldDef('run_at', this.t($r('app.string.module_auto_f_job_run_at')), 'text', false, '2026-08-26T09:00:00'),
      fieldDef('timezone', this.t($r('app.string.module_auto_f_job_timezone')), 'text', true, 'Asia/Shanghai'),
      fieldDef('repeat_every_days', this.t($r('app.string.module_auto_f_job_repeat')), 'number', false, '',
        this.t($r('app.string.module_auto_f_job_repeat_help'))),
      taskType,
      fieldDef('content', this.t($r('app.string.module_auto_f_job_content')), 'textarea', true, '',
        this.t($r('app.string.module_auto_f_job_content_help')))
    ];
    if (this.targets.length > 0) {
      const labels: string[] = [];
      for (const t of this.targets) {
        labels.push(this.targetValue(t));
      }
      const dispatch: FieldDef = fieldDef('dispatch_target',
        this.t($r('app.string.module_auto_f_job_dispatch')), 'select', false, '', '', labels);
      dispatch.defText = labels[0];
      defs.push(dispatch);
    }
    defs.push(fieldDef('save_result_to_inbox', this.t($r('app.string.module_auto_f_job_inbox')), 'switch'));
    defs.push(fieldDef('timeout_seconds', this.t($r('app.string.module_auto_f_job_timeout')), 'number'));
    return defs;
  }

  private targetValue(t: DispatchTarget): string {
    return `${t.channel} · ${t.userId} · ${t.sessionId}`;
  }

  private targetByValue(value: string): DispatchTarget | null {
    for (const t of this.targets) {
      if (this.targetValue(t) === value) {
        return t;
      }
    }
    return null;
  }

  private jobOf(id: string): CronJob | null {
    for (const j of this.jobs) {
      if (j.id === id) {
        return j;
      }
    }
    return null;
  }

  private jobInitial(): Record<string, Object> {
    const out: Record<string, Object> = {};
    const job: CronJob | null = this.jobOf(this.editingJob);
    if (job === null) {
      const tz: string = 'Asia/Shanghai';
      out['enabled'] = true;
      out['schedule_type'] = 'cron';
      out['cron'] = '0 9 * * *';
      out['run_at'] = '';
      out['timezone'] = tz;
      out['repeat_every_days'] = 0;
      out['task_type'] = 'agent';
      out['save_result_to_inbox'] = true;
      out['timeout_seconds'] = DEFAULT_TIMEOUT;
      if (this.targets.length > 0) {
        out['dispatch_target'] = this.targetValue(this.targets[0]);
      }
      return out;
    }
    out['name'] = job.name;
    out['enabled'] = job.enabled;
    out['schedule_type'] = job.scheduleType;
    out['cron'] = job.cron.length > 0 ? job.cron : '0 9 * * *';
    out['run_at'] = job.runAt;
    out['timezone'] = job.timezone;
    out['repeat_every_days'] = job.repeatEveryDays;
    out['task_type'] = job.taskType;
    out['content'] = job.content;
    out['save_result_to_inbox'] = job.saveResultToInbox;
    out['timeout_seconds'] = job.timeoutSeconds;
    // 投递目标：优先匹配当前任务的 channel/user_id/session_id，否则首个目标（对齐 7378 dispatchValue）
    let matched: DispatchTarget | null = null;
    for (const t of this.targets) {
      if (t.channel === job.dispatchChannel && t.userId === job.dispatchUserId
        && t.sessionId === job.dispatchSessionId) {
        matched = t;
        break;
      }
    }
    if (matched === null && this.targets.length > 0) {
      matched = this.targets[0];
    }
    if (matched !== null) {
      out['dispatch_target'] = this.targetValue(matched);
    }
    return out;
  }

  private async saveJob(values: Record<string, Object>): Promise<void> {
    const current: CronJob | null = this.jobOf(this.editingJob);
    const name: string = strOf(values['name'], '').trim();
    const id: string = current !== null ? current.id : this.createJobId(name);
    const taskType: string = values['task_type'] === 'text' ? 'text' : 'agent';
    const content: string = strOf(values['content'], '');
    const scheduleType: string = values['schedule_type'] === 'once' ? 'once' : 'cron';
    const cron: string = strOf(values['cron'], '').trim();
    const runAt: string = strOf(values['run_at'], '').trim();
    const timezone: string = strOf(values['timezone'], 'UTC').trim();
    if (scheduleType === 'cron' && cron.length === 0) {
      throw new Error(this.t($r('app.string.module_auto_need_cron')));
    }
    if (scheduleType === 'once' && runAt.length === 0) {
      throw new Error(this.t($r('app.string.module_auto_need_run_at')));
    }
    const picked: DispatchTarget | null = this.targetByValue(strOf(values['dispatch_target'], ''));
    const repeat: number = numOf(values['repeat_every_days'], 0);
    // 整表回写：保留服务端原文，仅覆盖表单字段（对齐 7378 payload 展开）
    const body: Record<string, Object> = current !== null ? this.copyOf(this.rawOf(current.id)) : {};
    body['id'] = id;
    body['name'] = name;
    body['enabled'] = values['enabled'] === true;
    body['save_result_to_inbox'] = values['save_result_to_inbox'] === true;
    body['task_type'] = taskType;
    const schedule: Record<string, Object> = {};
    if (scheduleType === 'cron') {
      schedule['type'] = 'cron';
      schedule['cron'] = cron;
      schedule['timezone'] = timezone;
    } else {
      schedule['type'] = 'once';
      schedule['run_at'] = runAt;
      schedule['timezone'] = timezone;
      if (repeat > 0) {
        schedule['repeat_every_days'] = repeat;
        schedule['repeat_end_type'] = 'never';
      }
    }
    body['schedule'] = schedule;
    if (taskType === 'text') {
      body['text'] = content;
    } else {
      const part: Record<string, string> = { 'type': 'text', 'text': content };
      const message: Record<string, Object> = { 'role': 'user', 'content': [part] };
      const request: Record<string, Object> = current !== null ? this.copyOf(recOf(this.rawOf(current.id)['request'])) : {};
      request['input'] = [message];
      request['user_id'] = 'mobile';
      request['session_id'] = `cron:${id}`;
      body['text'] = '';
      body['request'] = request;
    }
    const dispatch: Record<string, Object> = current !== null ? this.copyOf(recOf(this.rawOf(current.id)['dispatch'])) : {};
    dispatch['type'] = 'channel';
    dispatch['channel'] = picked !== null ? picked.channel
      : (current !== null ? current.dispatchChannel : 'console');
    const target: Record<string, string> = {};
    if (picked !== null) {
      target['user_id'] = picked.userId;
      target['session_id'] = picked.sessionId;
    } else if (current !== null) {
      target['user_id'] = current.dispatchUserId;
      target['session_id'] = current.dispatchSessionId;
    } else {
      target['user_id'] = 'mobile';
      target['session_id'] = `cron:${id}`;
    }
    dispatch['target'] = target;
    dispatch['mode'] = 'final';
    dispatch['silent'] = false;
    body['dispatch'] = dispatch;
    const runtime: Record<string, Object> = current !== null ? this.copyOf(recOf(this.rawOf(current.id)['runtime'])) : {};
    runtime['max_concurrency'] = 1;
    runtime['timeout_seconds'] = numOf(values['timeout_seconds'], DEFAULT_TIMEOUT);
    runtime['misfire_grace_seconds'] = 600;
    runtime['tool_safety'] = false;
    body['runtime'] = runtime;
    if (current !== null) {
      await this.mutate(http.RequestMethod.PUT,
        `/api/cron/jobs/${encodeURIComponent(current.id)}`, JSON.stringify(body));
    } else {
      await this.mutate(http.RequestMethod.POST, '/api/cron/jobs', JSON.stringify(body));
    }
    await this.load();
  }

  private createJobId(name: string): string {
    const lower: string = name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    let slug: string = lower;
    while (slug.startsWith('-')) {
      slug = slug.substring(1);
    }
    while (slug.endsWith('-')) {
      slug = slug.substring(0, slug.length - 1);
    }
    const base: string = slug.length > 0 ? slug : 'mobile-job';
    return `${base}-${Date.now().toString(36)}`;
  }

  private copyOf(src: Record<string, Object>): Record<string, Object> {
    const out: Record<string, Object> = {};
    for (const k of Object.keys(src)) {
      out[k] = src[k];
    }
    return out;
  }

  private historyTitle(name: string): string {
    return `${name} · ${this.t($r('app.string.module_auto_history'))}`;
  }

  private alert(title: Resource | string, message: Resource | string): void {
    this.getUIContext().showAlertDialog({
      title: title,
      message: message,
      confirm: {
        value: this.t($r('app.string.common_confirm')),
        action: (): void => {}
      }
    });
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.editor === 'heartbeat') {
        FieldSheet({
          title: this.t($r('app.string.module_auto_hb_config')),
          defs: this.hbDefs(),
          initial: {
            'enabled': this.hbEnabled,
            'every': this.hbEvery,
            'target': this.hbTarget.length > 0 ? this.hbTarget : 'main',
            'timeoutSeconds': this.hbTimeout,
            'activeHoursStart': this.hbStart,
            'activeHoursEnd': this.hbEnd
          },
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveHeartbeat(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else {
        FieldSheet({
          title: this.editingJob.length > 0 ? this.t($r('app.string.module_auto_job_edit'))
            : this.t($r('app.string.module_auto_create')),
          defs: this.jobDefs(),
          initial: this.jobInitial(),
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveJob(values);
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
        IosGroup({ title: this.t($r('app.string.module_auto_g_heartbeat')) }) {
          IosRow({
            icon: $r('sys.symbol.clock_arrow_2_circlepath'),
            label: this.t($r('app.string.module_auto_wake')),
            subtitle: this.hasHeartbeat
              ? `${this.hbEvery.length > 0 ? this.hbEvery : this.t($r('app.string.module_auto_default_every'))}`
                + ` · ${this.hbTarget.length > 0 ? this.hbTarget : this.t($r('app.string.module_auto_current_agent'))}`
              : this.t($r('app.string.module_auto_unsupported')),
            trailing: this.hbEnabled ? this.t($r('app.string.module_auto_enabled'))
              : this.t($r('app.string.module_auto_disabled')),
            tappable: this.hasHeartbeat,
            onPress: (): void => {
              this.runHeartbeat();
            }
          })
          if (this.hasHeartbeat) {
            IosRow({
              icon: $r('sys.symbol.square_and_pencil'),
              label: this.t($r('app.string.module_auto_config')),
              subtitle: this.t($r('app.string.module_auto_config_hint')),
              tappable: true,
              onPress: (): void => {
                this.editor = 'heartbeat';
                this.openSheet();
              }
            })
          }
        }
        IosGroup({
          title: this.hasJobs && this.jobs.length > 0
            ? `Cron Jobs · ${this.jobs.length}` : 'Cron Jobs'
        }) {
          IosRow({
            icon: $r('sys.symbol.plus'),
            label: this.t($r('app.string.module_auto_create')),
            subtitle: this.jobs.length > 0 ? this.t($r('app.string.module_auto_create_hint')) : '',
            tappable: true,
            onPress: (): void => {
              this.editingJob = '';
              this.editor = 'job';
              this.openSheet();
            }
          })
          ForEach(this.jobs, (job: CronJob) => {
            Column() {
              IosRow({
                icon: job.enabled ? $r('sys.symbol.clock') : $r('sys.symbol.clock_arrow_2_circlepath'),
                label: job.name,
                subtitle: this.scheduleLabel(this.rawOf(job.id)),
                trailing: job.enabled ? this.t($r('app.string.module_auto_running'))
                  : this.t($r('app.string.module_auto_paused')),
                tappable: true
              })
            }
            .width('100%')
            .bindMenu(this.jobMenu(job))
          }, (job: CronJob) => job.id)
        }
        if (this.hasJobs && this.jobs.length === 0) {
          ModuleEmpty($r('sys.symbol.clock'),
            this.t($r('app.string.module_auto_empty_title')),
            this.t($r('app.string.module_auto_empty_copy')))
        }
        ModuleFooter(this.t($r('app.string.module_auto_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(660, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }
}
