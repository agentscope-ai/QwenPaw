/*
 * 工作台模块 · Debug —— 对齐 PR #7378 features/workbench/DebugSettings.tsx。
 *   GET /api/console/debug/backend-logs?lines=200
 *      → { path, exists, lines, updated_at, size, content }
 * 日志面板用同一套半模态（SheetGate + moduleSheetOptions）；内容只在当前设备展示，不上传。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { UiTokens } from '../theme/UiTokens';
import { t } from '../services/I18n';

const LOG_LINES: number = 200;

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

function numOf(value: Object, fallback: number): number {
  const n: number = Number(value !== undefined && value !== null ? value : fallback);
  return Number.isFinite(n) ? n : fallback;
}

@Component
export struct ModuleDebug {
  @State logPath: string = '';
  @State logContent: string = '';
  @State logExists: boolean = false;
  @State logLines: number = 0;
  @State logSize: number = 0;
  @State loaded: boolean = false;
  @State error: string = '';
  @State sheetShown: boolean = false;
  private gate: SheetGate = new SheetGate();

  aboutToAppear(): void {
    this.load();
  }

  private openSheet(): void {
    if (!this.gate.request()) {
      return;
    }
    this.sheetShown = true;
  }


  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      this.error = t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    try {
      const resp: http.HttpResponse = await doRequest(
        `${c.baseUrl}/api/console/debug/backend-logs?lines=${LOG_LINES}`,
        http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const data: Record<string, Object> = jsonOf(resp);
      this.logPath = strOf(data['path'], '');
      this.logContent = strOf(data['content'], '');
      this.logExists = data['exists'] === true;
      this.logLines = numOf(data['lines'], 0);
      this.logSize = numOf(data['size'], 0);
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  // 字节数可读化（对齐 7378 formatBytes）
  private formatBytes(value: number): string {
    if (value < 1024) {
      return `${Math.round(value)} B`;
    }
    if (value < 1024 * 1024) {
      return `${Math.round(value / 1024)} KB`;
    }
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }

  @Builder
  logSheet() {
    Column() {
      Text($r('app.string.module_dbg_sheet_title'))
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .width('100%')
        .margin({ bottom: 10 })
      Scroll() {
        Text(this.logContent.length > 0 ? this.logContent : $r('app.string.module_dbg_empty_content'))
          .fontSize(11)
          .lineHeight(17)
          .fontColor($r('app.color.text_primary_strong'))
          .width('100%')
          .padding(12)
          .borderRadius(12)
          .backgroundColor($r('app.color.card_bg'))
          .textAlign(TextAlign.Start)
          // 长日志行自动换行，避免横向溢出
          .wordBreak(WordBreak.BREAK_ALL)
          .copyOption(CopyOptions.LocalDevice)
      }
      .width('100%')
      .layoutWeight(1)
      .align(Alignment.Top)
      .scrollBar(BarState.Auto)
    }
    .width('100%')
    .height('100%')
    .padding({ left: 20, right: 20, top: 64, bottom: 16 })
  }

  build() {
    Column() {
      if (this.error.length > 0) {
        ModuleError(this.error, (): void => {
          this.load();
        })
      } else if (!this.loaded) {
        ModuleLoading(t($r('app.string.module_loading')))
      } else {
        IosGroup({ title: t($r('app.string.module_dbg_group')) }) {
          IosRow({
            icon: $r('app.media.file_text'),
            label: t($r('app.string.module_dbg_recent')),
            subtitle: `${this.logLines} ${t($r('app.string.module_dbg_lines'))} · `
              + `${this.formatBytes(this.logSize)}`,
            trailing: this.logExists ? t($r('app.string.module_dbg_view'))
              : t($r('app.string.module_dbg_not_created')),
            tappable: true,
            onPress: (): void => {
              this.openSheet();
            }
          })
          IosRow({
            icon: $r('app.media.refresh_cw'),
            label: t($r('app.string.module_dbg_refresh')),
            subtitle: t($r('app.string.module_dbg_refresh_hint')),
            tappable: true,
            onPress: (): void => {
              this.load();
            }
          })
          IosRow({
            icon: $r('app.media.file_text'),
            label: t($r('app.string.module_dbg_path')),
            subtitle: this.logPath.length > 0 ? this.logPath
              : t($r('app.string.module_dbg_no_path'))
          })
        }
        ModuleFooter(t($r('app.string.module_dbg_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.logSheet(),
      moduleSheetOptions(620, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }
}
