/*
 * Copyright (c) 2026 Huawei Device Co., Ltd.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { AbilityConstant, Configuration, ConfigurationConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window, ColorMetrics, display } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { initI18n } from '../services/I18n';
import { bindPlatformContext } from '../services/PlatformGateway';

const DOMAIN = 0x0000;

export default class EntryAbility extends UIAbility {
  // 折叠态监听器（仅折叠屏注册）：窗口销毁时按引用注销
  private foldListener: ((s: display.FoldStatus) => void) | null = null;

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    initI18n(this.context);
    // 请求层（无 ctx 的纯函数）做 Platform 网关复签时要用到应用上下文：启动时绑定一次
    bindPlatformContext(this.context);
    try {
      this.context.getApplicationContext().setColorMode(ConfigurationConstant.ColorMode.COLOR_MODE_NOT_SET);
    } catch (err) {
      hilog.error(DOMAIN, 'testTag', 'Failed to set colorMode. Cause: %{public}s', JSON.stringify(err));
    }
    // 深浅色实时跟随：AppStorage 共享键，各页 isDark 用 @StorageLink 订阅——切换深浅色时
    // 长驻页面（会话详情等）立即生效，不必重开页面。刷新走两条官方订阅路：
    // 前台实时 = onConfigurationUpdate（系统环境变量订阅，控制中心切深浅色即此路径，
    // 官方文档 subscribe-system-environment-variable-changes）；
    // 后台延迟 = onForeground 兜底（后台期间变更延迟到回前台再下发）。
    // 此处初值可能还是未解析的占位，根页 aboutToAppear 会回写解析值。
    AppStorage.setOrCreate('appIsDark',
      this.context.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK);
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onCreate');
  }

  onDestroy(): void {
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onDestroy');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    // Main window is created, set main page for this ability
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onWindowStageCreate');

    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(DOMAIN, 'testTag', 'Failed to load the content. Cause: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(DOMAIN, 'testTag', 'Succeeded in loading the content.');
      // 窗口底色 = 页面底色：底部悬浮页签栏周围、手势条一带、屏幕左右两侧这些"没有组件覆盖"的区域
      // 露的是窗口底色（默认黑）—— 组件级 backgroundColor 只覆盖自身区域，故在窗口层面统一设一次。
      // 必须在 loadContent 生效后调用（loadContent 前窗口状态未就绪，抛 1300002 STATE_ABNORMAL）
      try {
        const mainWindow: window.Window = windowStage.getMainWindowSync();
        // 用 ColorMetrics.resourceColor 直接吃资源（随深浅色/限定词目录解析，不用手工取色值）
        mainWindow.setWindowBackgroundColor(ColorMetrics.resourceColor($r('app.color.page_bg')));
      } catch (err) {
        hilog.error(DOMAIN, 'testTag', 'Failed to set window background. Cause: %{public}s', JSON.stringify(err));
      }
    });

    // 折叠屏按折叠态控制旋转（module.json5 声明 unspecified，系统不静态锁方向）：
    // 仅对折叠屏生效——普通手机 getFoldStatus 恒为 UNKNOWN，保持原有自由方向行为
    if (this.isFoldableDevice()) {
      windowStage.getMainWindow().then((win: window.Window): void => {
        this.applyFoldOrientation(win);
        const cb = (s: display.FoldStatus): void => this.applyFoldOrientation(win);
        this.foldListener = cb;
        display.on('foldStatusChange', cb);
      }).catch((err: BusinessError): void => {
        hilog.error(DOMAIN, 'testTag', 'getMainWindow failed. Cause: %{public}s', JSON.stringify(err));
      });
    }
  }

  // 折叠屏判定（官方 faqs-arkui-340）：isFoldable() 对仅外屏辅助显示的竖向折叠机
  // （HUAWEI Pocket 2）返回 false → 以折叠态非 UNKNOWN 兜底
  private isFoldableDevice(): boolean {
    try {
      return display.isFoldable() || display.getFoldStatus() !== display.FoldStatus.FOLD_STATUS_UNKNOWN;
    } catch (e) {
      return false;
    }
  }

  // 折叠态 → 期望旋转（官方 faqs-arkui-362）：
  // 窄态（折叠 / 二轴折叠）= 手机形态 → 锁竖屏；展开 / 半折叠 / 双轴展开 = 平板形态 →
  // AUTO_ROTATION_UNSPECIFIED（官方「选择合适的窗口旋转策略」表：四向受控自动旋转，
  // 受控制中心旋转锁控制；不受控的 AUTO_ROTATION 不在推荐表内）。
  // 任务连续性（折叠/展开互切保持当前页面与路由）由应用侧响应窗口尺寸变化天然满足：
  // 布局全部按实时窗口宽高推导，路由栈不随折叠态重建
  private applyFoldOrientation(win: window.Window): void {
    try {
      const status: display.FoldStatus = display.getFoldStatus();
      if (status === display.FoldStatus.FOLD_STATUS_UNKNOWN) {
        return;
      }
      const narrow: boolean = status === display.FoldStatus.FOLD_STATUS_FOLDED
        || status === display.FoldStatus.FOLD_STATUS_FOLDED_WITH_SECOND_HALF_FOLDED;
      win.setPreferredOrientation(
        narrow ? window.Orientation.PORTRAIT : window.Orientation.AUTO_ROTATION_UNSPECIFIED,
        (err: BusinessError): void => {
          hilog.error(DOMAIN, 'testTag', 'setPreferredOrientation failed. Cause: %{public}s',
            JSON.stringify(err));
        });
    } catch (err) {
      hilog.error(DOMAIN, 'testTag', 'applyFoldOrientation failed. Cause: %{public}s', JSON.stringify(err));
    }
  }

  onWindowStageDestroy(): void {
    // Main window is destroyed, release UI related resources
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onWindowStageDestroy');
    if (this.foldListener !== null) {
      display.off('foldStatusChange', this.foldListener);
      this.foldListener = null;
    }
  }

  onForeground(): void {
    // Ability has brought to foreground
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onForeground');
    this.refreshIsDark();
  }

  // 系统环境变量变化订阅（官方 doccenter-capabilities/subscribe-system-environment-variable-changes）：
  // 深浅色变化时前台实时回调、后台延迟到回前台——用户在控制中心切深浅色时 app 保持前台，
  // 只有这条路能同帧刷新标志。若不刷新，标志驱动的颜色（气泡墨色等）与系统资源驱动的颜色
  // （卡片底色 $r 即时翻转）失步，出现"浅底白字"不可见的窗口。
  onConfigurationUpdate(newConfig: Configuration): void {
    const dark: boolean = newConfig.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    if (AppStorage.get<boolean>('appIsDark') !== dark) {
      hilog.info(DOMAIN, 'testTag', 'colorMode changed -> dark=%{public}d', dark ? 1 : 0);
      AppStorage.set('appIsDark', dark);
    }
  }

  // 回到前台时重读系统配色：用户在通知面板/系统设置里切换深浅色都发生在离前台的间隙，
  // 前台化时 context.config 已是新值——与 AppStorage 现值不一致才写（避免无谓触发全页重渲）
  private refreshIsDark(): void {
    try {
      const dark: boolean = this.context.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
      if (AppStorage.get<boolean>('appIsDark') !== dark) {
        AppStorage.set('appIsDark', dark);
      }
    } catch (err) {
      hilog.error(DOMAIN, 'testTag', 'refreshIsDark failed. Cause: %{public}s', JSON.stringify(err));
    }
  }

  onBackground(): void {
    // Ability has back to background
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onBackground');
  }
}