/*
 * 工作台模块 · Channels —— 对齐 PR #7378 features/workbench/ChannelSettings.tsx
 *                          + ChannelAccessSettings.tsx（7378 中访问控制渲染在渠道列表之前）。
 *   GET  /api/access-control                    渠道白/黑名单与待处理
 *   POST /api/access-control/{whitelist|blacklist}/{add|remove}
 *   POST /api/access-control/pending/{approve|deny|dismiss}
 *   GET  /api/mail-access-control               邮件待处理
 *   POST /api/mail-access-control/pending/{approve|deny|dismiss}
 *   GET  /api/config/channels                   渠道配置；PUT /api/config/channels/{key} 保存
 *   GET  /api/config/channels/schemas           插件渠道的动态字段定义
 * 渠道表单字段 = 插件 schema 字段（有则用）优先，否则内置字段表，末尾统一追加公共字段；
 * 保存走整表合并（{...当前, ...表单值}），避免覆盖未展示字段。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';

function recOf(value: Object): Record<string, Object> {
  if (value === null || value === undefined || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, Object>;
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

// 渠道显示名（对齐 7378 channelLabel）
const CHANNEL_NAMES: Record<string, string> = {
  'console': 'Console',
  'dingtalk': '钉钉',
  'feishu': '飞书',
  'wechat': '微信',
  'wecom': '企业微信',
  'telegram': 'Telegram',
  'discord': 'Discord',
  'slack': 'Slack',
  'imessage': 'iMessage',
  'mattermost': 'Mattermost',
  'mqtt': 'MQTT',
  'matrix': 'Matrix',
  'qq': 'QQ'
};

// 内置凭据字段（对齐 7378 builtinFields；标签为专有名词，保留英文）
const BUILTIN_FIELDS: Record<string, string[][]> = {
  'dingtalk': [['client_id', 'Client ID', 'password'], ['client_secret', 'Client Secret', 'password']],
  'feishu': [['app_id', 'App ID', 'password'], ['app_secret', 'App Secret', 'password'],
    ['encrypt_key', 'Encrypt Key', 'password'], ['verification_token', 'Verification Token', 'password']],
  'telegram': [['bot_token', 'Bot Token', 'password'], ['base_url', 'API Base URL', 'text'],
    ['http_proxy', 'HTTP Proxy', 'text']],
  'discord': [['bot_token', 'Bot Token', 'password'], ['http_proxy', 'HTTP Proxy', 'text']],
  'slack': [['bot_token', 'Bot Token', 'password'], ['app_token', 'App Token', 'password']],
  'wecom': [['bot_id', 'Bot ID', 'text'], ['secret', 'Secret', 'password']],
  'wechat': [['bot_token', 'Bot Token', 'password'], ['bot_token_file', 'Token File', 'text']],
  'qq': [['app_id', 'App ID', 'text'], ['client_secret', 'Client Secret', 'password']],
  'mattermost': [['url', 'Server URL', 'text'], ['bot_token', 'Bot Token', 'password']],
  'matrix': [['homeserver', 'Homeserver URL', 'text'], ['user_id', 'User ID', 'text'],
    ['access_token', 'Access Token', 'password'], ['password', 'Password', 'password']],
  'mqtt': [['host', 'Host', 'text'], ['port', 'Port', 'number'], ['username', 'Username', 'text'],
    ['password', 'Password', 'password'], ['subscribe_topic', 'Subscribe Topic', 'text'],
    ['publish_topic', 'Publish Topic', 'text']],
  'imessage': [['db_path', 'Messages DB Path', 'text']]
};

class ChannelInfo {
  key: string = '';
  enabled: boolean = false;
}

class AclUser {
  channel: string = '';
  userId: string = '';
  remark: string = '';
  username: string = '';
  allowed: boolean = true;
}

class PendingEntry {
  channel: string = '';
  userId: string = '';
  firstMessage: string = '';
  remark: string = '';
  username: string = '';
}

class MailPending {
  agentId: string = '';
  address: string = '';
  displayName: string = '';
  subject: string = '';
}

@Component
export struct ModuleChannels {
  @State channels: ChannelInfo[] = [];
  @State channelKeys: string[] = [];
  @State aclUsers: AclUser[] = [];
  @State pending: PendingEntry[] = [];
  @State mailPending: MailPending[] = [];
  @State aclSupported: boolean = false;
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

  private rawChannels: Record<string, Object> = {};
  private schemas: Record<string, Object> = {};
  private conn: QpConnection | null = null;
  private editing: string = '';

  aboutToAppear(): void {
    this.load();
  }

  private async connect(): Promise<QpConnection | null> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    return await loadConnection(ctx);
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

  private async post(path: string, body: string | null): Promise<void> {
    const c: QpConnection = this.conn as QpConnection;
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      http.RequestMethod.POST, body, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
  }

  private async load(): Promise<void> {
    const c: QpConnection | null = await this.connect();
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      const value: Record<string, Object> = await this.getJson('/api/config/channels');
      const schemaValue: Record<string, Object> = await this.getJson('/api/config/channels/schemas');
      this.schemas = schemaValue;
      this.applyChannels(value);
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
      this.loaded = true;
      return;
    }
    // 访问控制与邮件各自独立取值：任一失败不影响渠道列表
    try {
      const acl: Record<string, Object> = await this.getJson('/api/access-control');
      this.applyAcl(acl);
      this.aclSupported = true;
    } catch (e) {
      this.aclUsers = [];
      this.pending = [];
    }
    try {
      const mail: Record<string, Object> = await this.getJson('/api/mail-access-control');
      this.applyMailAcl(mail);
      this.aclSupported = true;
    } catch (e) {
      this.mailPending = [];
    }
    this.loaded = true;
  }

  private applyChannels(value: Record<string, Object>): void {
    const list: ChannelInfo[] = [];
    const keys: string[] = [];
    const raw: Record<string, Object> = {};
    for (const key of Object.keys(value)) {
      const v: Object = value[key];
      if (v === null || v === undefined || typeof v !== 'object' || Array.isArray(v)) {
        continue;
      }
      const rec: Record<string, Object> = v as Record<string, Object>;
      const info: ChannelInfo = new ChannelInfo();
      info.key = key;
      info.enabled = rec['enabled'] === true;
      list.push(info);
      keys.push(key);
      raw[key] = rec;
    }
    list.sort((a: ChannelInfo, b: ChannelInfo): number => a.key < b.key ? -1 : (a.key > b.key ? 1 : 0));
    keys.sort();
    this.channels = list;
    this.channelKeys = keys;
    this.rawChannels = raw;
  }

  private applyAcl(acl: Record<string, Object>): void {
    const users: AclUser[] = [];
    const pendings: PendingEntry[] = [];
    for (const channel of Object.keys(acl)) {
      const entry: Record<string, Object> = recOf(acl[channel]);
      this.collectList(users, channel, recOf(entry['whitelist']), true);
      this.collectList(users, channel, recOf(entry['blacklist']), false);
      const pending: Object = entry['pending'];
      if (Array.isArray(pending)) {
        for (const item of pending as Object[]) {
          const rec: Record<string, Object> = recOf(item);
          const p: PendingEntry = new PendingEntry();
          p.channel = strOf(rec['channel'], channel);
          p.userId = strOf(rec['user_id'], '');
          p.firstMessage = strOf(rec['first_message'], '');
          p.remark = strOf(rec['remark'], '');
          p.username = strOf(rec['username'], '');
          pendings.push(p);
        }
      }
    }
    this.aclUsers = users;
    this.pending = pendings;
  }

  private collectList(out: AclUser[], channel: string, list: Record<string, Object>,
    allowed: boolean): void {
    for (const userId of Object.keys(list)) {
      const info: Record<string, Object> = recOf(list[userId]);
      const u: AclUser = new AclUser();
      u.channel = channel;
      u.userId = userId;
      u.remark = strOf(info['remark'], '');
      u.username = strOf(info['username'], '');
      u.allowed = allowed;
      out.push(u);
    }
  }

  private applyMailAcl(mail: Record<string, Object>): void {
    const out: MailPending[] = [];
    for (const key of Object.keys(mail)) {
      const entry: Record<string, Object> = recOf(mail[key]);
      const pending: Object = entry['pending'];
      if (Array.isArray(pending)) {
        for (const item of pending as Object[]) {
          const rec: Record<string, Object> = recOf(item);
          const m: MailPending = new MailPending();
          m.agentId = strOf(rec['agent_id'], key);
          m.address = strOf(rec['sender_address'], '');
          m.displayName = strOf(rec['display_name'], '');
          m.subject = strOf(rec['subject'], '');
          out.push(m);
        }
      }
    }
    this.mailPending = out;
  }

  private channelLabel(key: string): string {
    const name: Object = CHANNEL_NAMES[key];
    return typeof name === 'string' ? name as string : key;
  }

  // —— 渠道开关 / 编辑 ——

  private async toggleChannel(key: string): Promise<void> {
    const current: Record<string, Object> = recOf(this.rawChannels[key]);
    const next: Record<string, Object> = this.copyOf(current);
    next['enabled'] = current['enabled'] !== true;
    await this.saveChannel(key, next);
  }

  private async saveChannel(key: string, body: Record<string, Object>): Promise<void> {
    const c: QpConnection = this.conn as QpConnection;
    try {
      const resp: http.HttpResponse = await doRequest(
        `${c.baseUrl}/api/config/channels/${encodeURIComponent(key)}`,
        http.RequestMethod.PUT, JSON.stringify(body),
        c.token.length > 0 ? c.token : null, c.agentId);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      this.rawChannels[key] = jsonOf(resp);
      const updated: ChannelInfo[] = [];
      for (const info of this.channels) {
        const copy: ChannelInfo = new ChannelInfo();
        copy.key = info.key;
        copy.enabled = info.key === key
          ? recOf(this.rawChannels[key])['enabled'] === true : info.enabled;
        updated.push(copy);
      }
      this.channels = updated;
    } catch (e) {
      this.toast($r('app.string.module_ch_save_failed'));
    }
  }

  // —— 访问控制 ——

  private aclBody(channel: string, userId: string, remark: string): string {
    const entry: Record<string, string> = { 'channel': channel, 'user_id': userId };
    if (remark.length > 0) {
      entry['remark'] = remark;
    }
    const body: Record<string, Object> = {};
    body['entries'] = [entry];
    return JSON.stringify(body);
  }

  private async aclAction(path: string, body: string): Promise<void> {
    try {
      await this.post(path, body);
      await this.load();
    } catch (e) {
      this.toast($r('app.string.module_ch_acl_failed'));
    }
  }

  private pendingMenu(entry: PendingEntry): MenuElement[] {
    const body: string = this.aclBody(entry.channel, entry.userId, '');
    return [
      {
        value: $r('app.string.module_ch_allow'),
        action: (): void => {
          this.aclAction('/api/access-control/pending/approve', body);
        }
      },
      {
        value: $r('app.string.module_ch_deny'),
        action: (): void => {
          this.aclAction('/api/access-control/pending/deny', body);
        }
      },
      {
        value: $r('app.string.module_ch_dismiss'),
        action: (): void => {
          this.aclAction('/api/access-control/pending/dismiss', body);
        }
      }
    ];
  }

  private mailMenu(entry: MailPending): MenuElement[] {
    const item: Record<string, string> = { 'agent_id': entry.agentId, 'address': entry.address };
    const body: Record<string, Object> = {};
    body['entries'] = [item];
    const text: string = JSON.stringify(body);
    return [
      {
        value: $r('app.string.module_ch_allow'),
        action: (): void => {
          this.aclAction('/api/mail-access-control/pending/approve', text);
        }
      },
      {
        value: $r('app.string.module_ch_deny'),
        action: (): void => {
          this.aclAction('/api/mail-access-control/pending/deny', text);
        }
      },
      {
        value: $r('app.string.module_ch_dismiss'),
        action: (): void => {
          this.aclAction('/api/mail-access-control/pending/dismiss', text);
        }
      }
    ];
  }

  private ruleMenu(user: AclUser): MenuElement[] {
    const list: string = user.allowed ? 'whitelist' : 'blacklist';
    const body: string = this.aclBody(user.channel, user.userId, '');
    return [
      {
        value: $r('app.string.module_ch_remove_rule'),
        action: (): void => {
          this.aclAction(`/api/access-control/${list}/remove`, body);
        }
      }
    ];
  }

  private addRuleDefs(): FieldDef[] {
    const channel: FieldDef = fieldDef('channel', this.t($r('app.string.module_ch_f_channel')), 'select',
      true, '', '', this.channelKeys.length > 0 ? this.channelKeys : ['console']);
    channel.defText = this.channelKeys.length > 0 ? this.channelKeys[0] : 'console';
    const effect: FieldDef = fieldDef('effect', this.t($r('app.string.module_ch_f_effect')), 'select',
      true, '', '', [this.t($r('app.string.module_ch_allow')), this.t($r('app.string.module_ch_deny'))]);
    effect.defText = this.t($r('app.string.module_ch_allow'));
    return [
      channel,
      fieldDef('user_id', this.t($r('app.string.module_ch_f_user_id')), 'text', true),
      fieldDef('remark', this.t($r('app.string.module_ch_f_remark')), 'text'),
      effect
    ];
  }

  private async saveRule(values: Record<string, Object>): Promise<void> {
    const deny: string = this.t($r('app.string.module_ch_deny'));
    const list: string = strOf(values['effect'], '') === deny ? 'blacklist' : 'whitelist';
    const body: string = this.aclBody(strOf(values['channel'], 'console'),
      strOf(values['user_id'], '').trim(), strOf(values['remark'], '').trim());
    await this.post(`/api/access-control/${list}/add`, body);
    await this.load();
  }

  // —— 渠道表单字段 ——

  private schemaFields(key: string): FieldDef[] {
    const schema: Record<string, Object> = recOf(this.schemas[key]);
    const fields: Object = schema['config_fields'];
    const out: FieldDef[] = [];
    if (!Array.isArray(fields)) {
      return out;
    }
    for (const item of fields as Object[]) {
      const rec: Record<string, Object> = recOf(item);
      const name: string = strOf(rec['name'], '');
      let type: string = strOf(rec['type'], '');
      if (type === 'switch') {
        type = 'boolean';
      }
      const valid: string[] = ['text', 'password', 'number', 'boolean', 'select'];
      if (name.length === 0 || valid.indexOf(type) < 0) {
        continue;
      }
      const options: string[] = [];
      const rawOptions: Object = rec['options'];
      if (Array.isArray(rawOptions)) {
        for (const opt of rawOptions as Object[]) {
          if (typeof opt === 'string') {
            options.push(opt as string);
          }
        }
      }
      const label: string = this.localized(rec['label']);
      const d: FieldDef = fieldDef(name, label.length > 0 ? label : name, type,
        rec['required'] === true, this.localized(rec['placeholder']), this.localized(rec['help']), options);
      const def: Object = rec['default'];
      if (typeof def === 'string') {
        d.defText = def as string;
      }
      out.push(d);
    }
    return out;
  }

  // 本地化字段（schema 里 label/placeholder/help 可以是字符串或 {zh-CN, en-US, ...}）
  private localized(value: Object): string {
    if (typeof value === 'string') {
      return value as string;
    }
    const rec: Record<string, Object> = recOf(value);
    const order: string[] = ['zh-CN', 'zh', 'en-US', 'en'];
    for (const key of order) {
      const v: Object = rec[key];
      if (typeof v === 'string') {
        return v as string;
      }
    }
    for (const key of Object.keys(rec)) {
      const v: Object = rec[key];
      if (typeof v === 'string') {
        return v as string;
      }
    }
    return '';
  }

  private builtinFields(key: string): FieldDef[] {
    const out: FieldDef[] = [];
    const defs: Object = BUILTIN_FIELDS[key];
    if (!Array.isArray(defs)) {
      return out;
    }
    for (const item of defs as Object[]) {
      const parts: Object[] = item as Object[];
      const d: FieldDef = fieldDef(`${parts[0]}`, `${parts[1]}`, `${parts[2]}`);
      if (`${parts[2]}` === 'number') {
        d.defText = '1883';
      }
      out.push(d);
    }
    return out;
  }

  private commonFields(): FieldDef[] {
    const out: FieldDef[] = [
      fieldDef('bot_prefix', this.t($r('app.string.module_ch_f_prefix')), 'text')
    ];
    const switches: FieldDef[] = [
      fieldDef('show_tool_calls', this.t($r('app.string.module_ch_f_show_tool_calls')), 'boolean'),
      fieldDef('show_tool_results', this.t($r('app.string.module_ch_f_show_tool_results')), 'boolean'),
      fieldDef('show_thinking', this.t($r('app.string.module_ch_f_show_thinking')), 'boolean'),
      fieldDef('access_control_dm', this.t($r('app.string.module_ch_f_allow_dm')), 'boolean'),
      fieldDef('access_control_group', this.t($r('app.string.module_ch_f_allow_group')), 'boolean'),
      fieldDef('require_mention', this.t($r('app.string.module_ch_f_require_mention')), 'boolean')
    ];
    for (const s of switches) {
      s.defBool = true;
      out.push(s);
    }
    return out;
  }

  private channelDefs(key: string): FieldDef[] {
    const plugin: FieldDef[] = this.schemaFields(key);
    const head: FieldDef[] = plugin.length > 0 ? plugin : this.builtinFields(key);
    const out: FieldDef[] = [];
    for (const d of head) {
      out.push(d);
    }
    for (const d of this.commonFields()) {
      out.push(d);
    }
    return out;
  }

  private async saveChannelForm(values: Record<string, Object>): Promise<void> {
    const current: Record<string, Object> = recOf(this.rawChannels[this.editing]);
    const body: Record<string, Object> = this.copyOf(current);
    for (const key of Object.keys(values)) {
      body[key] = values[key];
    }
    await this.saveChannel(this.editing, body);
  }

  private copyOf(src: Record<string, Object>): Record<string, Object> {
    const out: Record<string, Object> = {};
    for (const k of Object.keys(src)) {
      out[k] = src[k];
    }
    return out;
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

  private aclGroupTitle(channel: string): string {
    return `${channel} ${this.t($r('app.string.module_ch_list_suffix'))}`;
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.editor === 'rule') {
        FieldSheet({
          title: this.t($r('app.string.module_ch_add_rule')),
          defs: this.addRuleDefs(),
          initial: {},
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveRule(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else {
        FieldSheet({
          title: this.channelLabel(this.editing),
          defs: this.channelDefs(this.editing),
          initial: recOf(this.rawChannels[this.editing]),
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveChannelForm(values);
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
        if (this.aclSupported) {
          IosGroup({ title: this.t($r('app.string.module_ch_access_group')) }) {
            IosRow({
              icon: $r('sys.symbol.plus'),
              label: this.t($r('app.string.module_ch_add_rule')),
              subtitle: this.t($r('app.string.module_ch_add_rule_hint')),
              tappable: true,
              onPress: (): void => {
                this.editor = 'rule';
                this.openSheet();
              }
            })
            IosRow({
              icon: $r('sys.symbol.checkmark_shield'),
              label: this.t($r('app.string.module_ch_pending')),
              subtitle: this.t($r('app.string.module_ch_pending_hint')),
              trailing: `${this.pending.length + this.mailPending.length}`,
              tappable: true
            })
          }
          if (this.pending.length > 0) {
            IosGroup({
              title: `${this.t($r('app.string.module_ch_pending_channel'))} · ${this.pending.length}`
            }) {
              ForEach(this.pending, (p: PendingEntry) => {
                Column() {
                  IosRow({
                    icon: $r('sys.symbol.person'),
                    label: p.remark.length > 0 ? p.remark
                      : (p.username.length > 0 ? p.username : p.userId),
                    subtitle: p.firstMessage.length > 0 ? `${p.channel} · ${p.firstMessage}` : p.channel,
                    trailing: this.t($r('app.string.module_ch_handle')),
                    tappable: true
                  })
                }
                .width('100%')
                .bindMenu(this.pendingMenu(p))
              }, (p: PendingEntry) => `${p.channel}:${p.userId}`)
            }
          }
          if (this.mailPending.length > 0) {
            IosGroup({
              title: `${this.t($r('app.string.module_ch_pending_mail'))} · ${this.mailPending.length}`
            }) {
              ForEach(this.mailPending, (m: MailPending) => {
                Column() {
                  IosRow({
                    icon: $r('sys.symbol.envelope'),
                    label: m.displayName.length > 0 ? m.displayName : m.address,
                    subtitle: m.subject.length > 0 ? `${m.agentId} · ${m.subject}` : m.agentId,
                    trailing: this.t($r('app.string.module_ch_handle')),
                    tappable: true
                  })
                }
                .width('100%')
                .bindMenu(this.mailMenu(m))
              }, (m: MailPending) => `${m.agentId}:${m.address}`)
            }
          }
          ForEach(this.channelKeys, (channel: string) => {
            if (this.usersOf(channel).length > 0) {
              IosGroup({ title: this.aclGroupTitle(channel) }) {
                ForEach(this.usersOf(channel), (u: AclUser) => {
                  Column() {
                    IosRow({
                      icon: u.allowed
                        ? $r('sys.symbol.person_badge_checkmark')
                        : $r('sys.symbol.person_xmark'),
                      label: u.remark.length > 0 ? u.remark
                        : (u.username.length > 0 ? u.username : u.userId),
                      subtitle: u.userId,
                      trailing: u.allowed ? this.t($r('app.string.module_ch_allow'))
                        : this.t($r('app.string.module_ch_deny')),
                      tappable: true
                    })
                  }
                  .width('100%')
                  .bindMenu(this.ruleMenu(u))
                }, (u: AclUser) => `${u.channel}:${u.allowed ? 'a' : 'd'}:${u.userId}`)
              }
            }
          }, (channel: string) => channel)
        }

        if (this.channels.length > 0) {
          IosGroup({ title: this.t($r('app.string.module_ch_channels_group')) }) {
            ForEach(this.channels, (info: ChannelInfo) => {
              IosRow({
                icon: $r('sys.symbol.radio'),
                label: this.channelLabel(info.key),
                subtitle: info.enabled ? this.t($r('app.string.module_ch_connected'))
                  : this.t($r('app.string.module_ch_disabled')),
                hasSwitch: true,
                switchOn: info.enabled,
                onSwitch: (): void => {
                  this.toggleChannel(info.key);
                },
                tappable: true,
                onPress: (): void => {
                  this.editing = info.key;
                  this.editor = 'channel';
                  this.openSheet();
                }
              })
            }, (info: ChannelInfo) => info.key)
          }
          ModuleFooter(this.t($r('app.string.module_ch_footer')))
        } else {
          ModuleEmpty($r('sys.symbol.radio'),
            this.t($r('app.string.module_ch_empty_title')),
            this.t($r('app.string.module_ch_empty_copy')))
        }
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(660, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  private usersOf(channel: string): AclUser[] {
    const out: AclUser[] = [];
    for (const u of this.aclUsers) {
      if (u.channel === channel) {
        out.push(u);
      }
    }
    return out;
  }
}
