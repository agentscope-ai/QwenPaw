/*
 * 动态表单半模态 —— 对齐 PR #7378 features/workbench/DynamicConfigSheet.tsx。
 * 工作台模块页里「新增 / 编辑一条配置」的表单（字段由 defs 声明）：
 *   text / password / number / textarea → 输入框；boolean / switch → 开关；select → 下拉菜单。
 * 字段类型与取值规则逐条对齐 7378：number 空串保持空串，否则转数字；boolean 取布尔；其余取字符串；
 * 必填项为空即拒绝保存并提示。
 * select 用 bindMenu（Menu 在沉浸光感白名单内，全页面生效；项目内已有先例）。
 * 半模态由调用方用 .bindSheet 承载（本组件只渲染内容）。
 */

import { common } from '@kit.AbilityKit';
import { UiTokens } from '../theme/UiTokens';
import { isDarkMode, accentColor } from '../theme/Accent';

export class FieldDef {
  name: string = '';
  label: string = '';
  // text | password | number | boolean | select | textarea
  type: string = 'text';
  required: boolean = false;
  placeholder: string = '';
  help: string = '';
  options: string[] = [];
  defText: string = '';
  defBool: boolean = false;
}

// 字段工厂（ArkTS 对象字面量要求字段齐全，用工厂避免每个字段写满 9 项）
export function fieldDef(name: string, label: string, type: string, required: boolean = false,
  placeholder: string = '', help: string = '', options: string[] = []): FieldDef {
  const d: FieldDef = new FieldDef();
  d.name = name;
  d.label = label;
  d.type = type;
  d.required = required;
  d.placeholder = placeholder;
  d.help = help;
  d.options = options;
  return d;
}

class FieldItem {
  name: string = '';
  text: string = '';
  flag: boolean = false;
}

@Component
export struct FieldSheet {
  title: string = '';
  defs: FieldDef[] = [];
  // 编辑既有配置时传入的当前值（Record<string, Object>：string / number / boolean）
  initial: Record<string, Object> = {};
  onSave: (values: Record<string, Object>) => Promise<void> =
    async (values: Record<string, Object>): Promise<void> => {};
  onClose: () => void = (): void => {};
  @State items: FieldItem[] = [];
  @State saving: boolean = false;
  private dark: boolean = false;

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.dark = isDarkMode(ctx);
    const out: FieldItem[] = [];
    for (const d of this.defs) {
      const it: FieldItem = new FieldItem();
      it.name = d.name;
      const v: Object = this.initial[d.name];
      if (d.type === 'boolean' || d.type === 'switch') {
        it.flag = typeof v === 'boolean' ? v as boolean : d.defBool;
      } else if (typeof v === 'string') {
        it.text = v as string;
      } else if (typeof v === 'number') {
        it.text = `${v as number}`;
      } else {
        it.text = d.defText;
      }
      out.push(it);
    }
    this.items = out;
  }

  private itemOf(name: string): FieldItem {
    for (const it of this.items) {
      if (it.name === name) {
        return it;
      }
    }
    return new FieldItem();
  }

  // 整表重建后整体赋值：@State 数组换引用才触发刷新（逐项改字段不刷新）
  private setText(name: string, text: string): void {
    const next: FieldItem[] = [];
    for (const it of this.items) {
      const copy: FieldItem = new FieldItem();
      copy.name = it.name;
      copy.text = it.name === name ? text : it.text;
      copy.flag = it.flag;
      next.push(copy);
    }
    this.items = next;
  }

  private setFlag(name: string, flag: boolean): void {
    const next: FieldItem[] = [];
    for (const it of this.items) {
      const copy: FieldItem = new FieldItem();
      copy.name = it.name;
      copy.text = it.text;
      copy.flag = it.name === name ? flag : it.flag;
      next.push(copy);
    }
    this.items = next;
  }

  private optionsOf(d: FieldDef): MenuElement[] {
    const out: MenuElement[] = [];
    for (const opt of d.options) {
      out.push({
        value: opt,
        action: (): void => {
          this.setText(d.name, opt);
        }
      });
    }
    return out;
  }

  private payload(): Record<string, Object> {
    const out: Record<string, Object> = {};
    for (const d of this.defs) {
      const it: FieldItem = this.itemOf(d.name);
      if (d.type === 'number') {
        const t: string = it.text.trim();
        out[d.name] = t.length > 0 ? Number(t) : '';
      } else if (d.type === 'boolean' || d.type === 'switch') {
        out[d.name] = it.flag;
      } else {
        out[d.name] = it.text;
      }
    }
    return out;
  }

  private async save(): Promise<void> {
    if (this.saving) {
      return;
    }
    for (const d of this.defs) {
      if (d.required && this.itemOf(d.name).text.trim().length === 0) {
        this.toast(`${this.t($r('app.string.module_field_required'))}：${d.label}`);
        return;
      }
    }
    this.saving = true;
    try {
      await this.onSave(this.payload());
      this.onClose();
    } catch (e) {
      this.toast((e as Error).message);
    } finally {
      this.saving = false;
    }
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
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
  fieldEditor(d: FieldDef, it: FieldItem) {
    Column() {
      Row() {
        Text(d.label)
          .fontSize(UiTokens.fsSecondary)
          .fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.text_secondary'))
        if (d.required) {
          Text($r('app.string.module_field_required'))
            .fontSize(UiTokens.fsChip)
            .fontColor(accentColor(this.dark))
            .margin({ left: 6 })
        }
      }
      .width('100%')
      .margin({ bottom: 6 })

      if (d.type === 'boolean' || d.type === 'switch') {
        Row() {
          Text(it.flag ? $r('app.string.module_field_on') : $r('app.string.module_field_off'))
            .fontSize(UiTokens.fsBody)
            .fontColor($r('app.color.text_secondary'))
            .layoutWeight(1)
          Toggle({ type: ToggleType.Switch, isOn: it.flag })
            .selectedColor(accentColor(this.dark))
            .onChange((on: boolean): void => {
              this.setFlag(d.name, on);
            })
        }
        .width('100%')
        .constraintSize({ minHeight: 50 })
        .padding({ left: 14, right: 14 })
        .borderRadius(UiTokens.cardRadius)
        // 卡片底色统一走 sheet_card_bg（灰色 token），与半模态玻璃背板拉开层次
        .backgroundColor($r('app.color.sheet_card_bg'))
      } else if (d.type === 'select') {
        Row() {
          Text(it.text.length > 0 ? it.text : $r('app.string.module_field_select'))
            .fontSize(UiTokens.fsBody)
            .fontColor(it.text.length > 0
              ? $r('app.color.text_primary_strong') : $r('app.color.text_tertiary'))
            .layoutWeight(1)
          Text('›')
            .fontSize(20)
            .fontColor($r('app.color.text_tertiary'))
        }
        .width('100%')
        .constraintSize({ minHeight: 50 })
        .padding({ left: 14, right: 14 })
        .borderRadius(UiTokens.cardRadius)
        // 卡片底色统一走 sheet_card_bg（灰色 token），与半模态玻璃背板拉开层次
        .backgroundColor($r('app.color.sheet_card_bg'))
        .bindMenu(this.optionsOf(d))
      } else if (d.type === 'textarea') {
        TextArea({ text: it.text, placeholder: d.placeholder })
          .width('100%')
          .height(110)
          .fontSize(UiTokens.fsBody)
          // 卡片底色统一走 sheet_card_bg（灰色 token），与半模态玻璃背板拉开层次
          .backgroundColor($r('app.color.sheet_card_bg'))
          .borderRadius(UiTokens.cardRadius)
          .onChange((v: string): void => {
            this.setText(d.name, v);
          })
      } else {
        TextInput({ text: it.text, placeholder: d.placeholder })
          .type(d.type === 'password' ? InputType.Password
            : (d.type === 'number' ? InputType.Number : InputType.Normal))
          .width('100%')
          .height(50)
          .fontSize(UiTokens.fsBody)
          // 卡片底色统一走 sheet_card_bg（灰色 token），与半模态玻璃背板拉开层次
          .backgroundColor($r('app.color.sheet_card_bg'))
          .borderRadius(UiTokens.cardRadius)
          .onChange((v: string): void => {
            this.setText(d.name, v);
          })
      }

      if (d.help.length > 0) {
        Text(d.help)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .width('100%')
          .margin({ top: 6 })
          .wordBreak(WordBreak.BREAK_ALL)
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .margin({ bottom: 18 })
  }

  build() {
    Column() {
      Text(this.title)
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Bold)
        .width('100%')
        .margin({ bottom: 14 })
      Scroll() {
        Column() {
          ForEach(this.defs, (d: FieldDef) => {
            this.fieldEditor(d, this.itemOf(d.name))
          }, (d: FieldDef) => d.name)
        }
        .width('100%')
      }
      .layoutWeight(1)
      .align(Alignment.Top)
      .scrollBar(BarState.Auto)
      Row() {
        Button($r('app.string.common_cancel'))
          .layoutWeight(1)
          .height(46)
          .backgroundColor($r('app.color.card_bg'))
          .fontColor($r('app.color.btn_gray_text'))
          .stateEffect(false)
          .onClick((): void => {
            this.onClose();
          })
        Button($r('app.string.common_save'))
          .layoutWeight(1)
          .height(46)
          .margin({ left: 10 })
          .backgroundColor(accentColor(this.dark))
          .fontColor(Color.White)
          .stateEffect(false)
          .enabled(!this.saving)
          .onClick((): void => {
            this.save();
          })
      }
      .width('100%')
      .margin({ top: 10 })
    }
    .width('100%')
    .height('100%')
    // 顶部留出系统关闭叉（✕）与拖拽条的高度，避免与标题/首字段重叠
    .padding({ left: 20, right: 20, top: 64, bottom: 16 })
  }
}
