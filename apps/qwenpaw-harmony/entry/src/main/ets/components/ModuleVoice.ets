/*
 * 工作台模块 · 语音与转写 —— 对齐 PR #7378 features/workbench/VoiceSettings.tsx。
 *   GET /api/workspace/audio-mode                    → {audio_mode}
 *   GET /api/workspace/transcription-provider-type    → {transcription_provider_type}
 *   GET /api/workspace/transcription-providers        → {providers[], configured_provider_id}
 *   GET /api/workspace/local-whisper-status           → {available, ffmpeg_installed, whisper_installed}
 *   PUT 以上前三者：{audio_mode} / {transcription_provider_type} / {provider_id}
 * 三项选择各走单选半模态（OptionsSheet），本地 Whisper 只读展示探测结果。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { OptionsSheet, SheetOption, optionOf } from './OptionsSheet';
import { ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';

class VoiceProvider {
  id: string = '';
  name: string = '';
  available: boolean = false;
}

const MODE_NONE: string = '';
const MODE_AUDIO: string = 'audio';
const MODE_TYPE: string = 'type';
const MODE_PROVIDER: string = 'provider';

@Component
export struct ModuleVoice {
  @State audioMode: string = 'auto';
  @State providerType: string = 'disabled';
  @State providerId: string = '';
  @State providers: VoiceProvider[] = [];
  @State ffmpegInstalled: boolean = false;
  @State whisperInstalled: boolean = false;
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
  private gate: SheetGate = new SheetGate();
  private conn: QpConnection | null = null;

  aboutToAppear(): void {
    this.load();
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private async send(path: string, method: http.RequestMethod,
    body: string | null): Promise<Record<string, Object> | null> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      throw new Error('未连接');
    }
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}/api${path}`, method, body,
      c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    if (method !== http.RequestMethod.GET) {
      return null;
    }
    return jsonOf(resp);
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      const mode: Record<string, Object> | null = await this.send(
        '/workspace/audio-mode', http.RequestMethod.GET, null);
      if (mode !== null && typeof mode['audio_mode'] === 'string') {
        this.audioMode = mode['audio_mode'] as string;
      }
      const type: Record<string, Object> | null = await this.send(
        '/workspace/transcription-provider-type', http.RequestMethod.GET, null);
      if (type !== null && typeof type['transcription_provider_type'] === 'string') {
        this.providerType = type['transcription_provider_type'] as string;
      }
      const list: Record<string, Object> | null = await this.send(
        '/workspace/transcription-providers', http.RequestMethod.GET, null);
      const out: VoiceProvider[] = [];
      if (list !== null) {
        const raw: Object = list['providers'];
        if (Array.isArray(raw)) {
          for (const item of raw as Object[]) {
            const r: Record<string, Object> = item as Record<string, Object>;
            const p: VoiceProvider = new VoiceProvider();
            p.id = typeof r['id'] === 'string' ? r['id'] as string : '';
            p.name = typeof r['name'] === 'string' ? r['name'] as string : p.id;
            p.available = r['available'] === true;
            out.push(p);
          }
        }
        const configured: Object = list['configured_provider_id'];
        this.providerId = typeof configured === 'string' ? configured as string : '';
      }
      this.providers = out;
      const local: Record<string, Object> | null = await this.send(
        '/workspace/local-whisper-status', http.RequestMethod.GET, null);
      if (local !== null) {
        this.ffmpegInstalled = local['ffmpeg_installed'] === true;
        this.whisperInstalled = local['whisper_installed'] === true;
      }
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private async update(path: string, body: Record<string, string>): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await this.send(path, http.RequestMethod.PUT, JSON.stringify(body));
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_voice_save_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private openSheet(mode: string): void {
    this.sheetMode = mode;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private audioLabel(): string {
    return this.audioMode === 'native' ? this.t($r('app.string.module_voice_audio_native'))
      : this.t($r('app.string.module_voice_audio_auto'));
  }

  private typeLabel(): string {
    if (this.providerType === 'whisper_api') {
      return this.t($r('app.string.module_voice_type_api'));
    }
    if (this.providerType === 'local_whisper') {
      return this.t($r('app.string.module_voice_type_local'));
    }
    return this.t($r('app.string.module_voice_type_off'));
  }

  private providerLabel(): string {
    for (const p of this.providers) {
      if (p.id === this.providerId) {
        return p.name;
      }
    }
    return '';
  }

  private availableCount(): number {
    let n: number = 0;
    for (const p of this.providers) {
      if (p.available) {
        n++;
      }
    }
    return n;
  }

  private options(): SheetOption[] {
    const out: SheetOption[] = [];
    if (this.sheetMode === MODE_AUDIO) {
      out.push(optionOf('auto', this.t($r('app.string.module_voice_audio_auto'))));
      out.push(optionOf('native', this.t($r('app.string.module_voice_audio_native'))));
    } else if (this.sheetMode === MODE_TYPE) {
      out.push(optionOf('disabled', this.t($r('app.string.module_voice_type_off'))));
      out.push(optionOf('whisper_api', this.t($r('app.string.module_voice_type_api'))));
      out.push(optionOf('local_whisper', this.t($r('app.string.module_voice_type_local'))));
    } else {
      for (const p of this.providers) {
        if (p.available) {
          out.push(optionOf(p.id, p.name));
        }
      }
      out.push(optionOf('', this.t($r('app.string.module_voice_clear'))));
    }
    return out;
  }

  private currentKey(): string {
    if (this.sheetMode === MODE_AUDIO) {
      return this.audioMode;
    }
    if (this.sheetMode === MODE_TYPE) {
      return this.providerType;
    }
    return this.providerId;
  }

  private sheetTitle(): string {
    if (this.sheetMode === MODE_AUDIO) {
      return this.t($r('app.string.module_voice_audio_label'));
    }
    if (this.sheetMode === MODE_TYPE) {
      return this.t($r('app.string.module_voice_type_label'));
    }
    return this.t($r('app.string.module_voice_provider_label'));
  }

  private async onPick(value: string): Promise<void> {
    if (this.sheetMode === MODE_AUDIO) {
      await this.update('/workspace/audio-mode', { 'audio_mode': value });
    } else if (this.sheetMode === MODE_TYPE) {
      await this.update('/workspace/transcription-provider-type',
        { 'transcription_provider_type': value });
    } else {
      await this.update('/workspace/transcription-provider', { 'provider_id': value });
    }
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
        IosGroup({ title: this.t($r('app.string.module_voice_group_audio')) }) {
          IosRow({
            icon: $r('sys.symbol.message'),
            label: this.t($r('app.string.module_voice_audio_label')),
            subtitle: this.t($r('app.string.module_voice_audio_hint')),
            trailing: this.audioLabel(),
            tappable: !this.busy,
            onPress: (): void => {
              this.openSheet(MODE_AUDIO);
            }
          })
        }
        IosGroup({ title: this.t($r('app.string.module_voice_group_text')) }) {
          IosRow({
            icon: $r('sys.symbol.translate'),
            label: this.t($r('app.string.module_voice_type_label')),
            trailing: this.typeLabel(),
            tappable: !this.busy,
            onPress: (): void => {
              this.openSheet(MODE_TYPE);
            }
          })
          IosRow({
            icon: $r('sys.symbol.doc_text'),
            label: this.t($r('app.string.module_voice_provider_label')),
            subtitle: `${this.availableCount()} ${this.t($r('app.string.module_voice_provider_available'))}`,
            trailing: this.providerLabel(),
            tappable: !this.busy,
            onPress: (): void => {
              this.openSheet(MODE_PROVIDER);
            }
          })
          IosRow({
            icon: $r('sys.symbol.checkmark_circle'),
            label: this.t($r('app.string.module_voice_local_label')),
            subtitle: `FFmpeg ${this.ffmpegInstalled
              ? this.t($r('app.string.module_voice_installed'))
              : this.t($r('app.string.module_voice_not_installed'))} · Whisper ${this.whisperInstalled
              ? this.t($r('app.string.module_voice_installed'))
              : this.t($r('app.string.module_voice_not_installed'))}`
          })
        }
        ModuleFooter(this.t($r('app.string.module_voice_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(420, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  @Builder
  sheetContent() {
    Column() {
      OptionsSheet({
        title: this.sheetTitle(),
        options: this.options(),
        current: this.currentKey(),
        onPick: (v: string): void => {
          this.onPick(v);
        },
        onClose: (): void => {
          this.closeSheet();
        }
      })
    }
    .width('100%')
    .height('100%')
  }
}
