# QwenPaw OpenUI

[English](README.md) | 中文

让 QwenPaw 的回答可以直接操作。通过 OpenUI，助手能在文字说明中加入表格、图表、表单和滑块，让你调整参数、比较结果，再带着选好的方案继续对话。

- **边读边操作**：界面随回答逐步出现，与文字、图片排在一起。
- **即时查看结果**：调整控件后，有关联的数值和图表在本地更新。
- **继续对话**：点击提交按钮，把当前选择交给助手进一步分析。

组件跟随 QwenPaw 的深浅主题、强调色和字号设置，下拉菜单和弹窗也保持一致。

## 安装

准备好 `qwenpaw-openui-0.1.0.zip`，启动 QwenPaw，然后执行：

```sh
qwenpaw plugin install /path/to/qwenpaw-openui-0.1.0.zip
```

刷新 Chat 即可使用。插件沿用 QwenPaw 已配置的模型，安装包包含前端运行所需资源，无需额外安装 Node.js、npm、Python 包或配置 OpenUI API key。

QwenPaw 需支持 `chat.codeBlock`、`chat.submit` 和 `host.openExternalLink` 插件接口。

如果 QwenPaw 尚未启动，也可以用系统解压工具展开 ZIP，安装其中的目录后再启动：

```sh
qwenpaw plugin install /path/to/extracted/qwenpaw-openui
```

## 开始使用

打开 Chat，像平常一样描述需求：

> 周末准备请朋友来家里吃烧烤，先按 6 人列采购清单。人数可能变，想调整人数时直接看到采购量。

助手会根据问题选择合适的呈现方式。生成的界面可以包含人数滑块、采购表和继续讨论的按钮。具体布局与联动取决于模型生成的内容。

调整滑块、勾选选项和填写表单在浏览器内完成。点击继续或提交按钮后，选定的信息会作为一条可见消息进入对话。刷新页面会恢复界面的初始值。

## 支持的界面

插件接入 OpenUI 官方组件目录，包含 82 个组件及子组件：

| 类别 | 组件示例 |
| --- | --- |
| 表格 | 数据表格、可编辑表格 |
| 图表 | 柱状图、折线图、面积图、饼图、雷达图、散点图 |
| 表单 | 输入框、下拉选择、日期选择、滑块、复选框、单选框、开关 |
| 布局 | 卡片、标签页、折叠面板、步骤、轮播、弹窗 |
| 内容 | Markdown、图片、图库、代码、提示信息、列表和指标 |

组件由模型使用 `openui-lang` 描述，OpenUI 官方运行时负责解析与交互。每个 UI 块维护自己的状态，可以和普通文字交替出现在同一条回答中。

## 常见问题

**回答只有文字？** 助手会自行判断是否需要界面。可以说明希望直接调整哪些参数，或选择哪些选项。

**界面没有显示？** 确认插件已启用并刷新 Chat。若提示缺少宿主接口，请使用支持上述接口的 QwenPaw。若提示界面生成失败，可以让助手重新生成。

**怎么卸载？** 执行以下命令，随后刷新 Chat。历史中的 UI 代码块会按普通代码显示。

```sh
qwenpaw plugin uninstall qwenpaw-openui
```

## 开发

使用 QwenPaw 的 Python 3.11+ 开发环境，以及 Node `^20.19.0`、`^22.13.0` 或 `>=24.0.0`。在仓库根目录执行：

```sh
npm --prefix plugins/bundle/qwenpaw-openui/frontend ci
npm --prefix plugins/bundle/qwenpaw-openui/frontend test
python -m pytest tests/unit/plugins/test_openui.py -q
python scripts/pack/generate_plugin_metadata.py --only qwenpaw-openui
```

安装包输出到 `dist/plugins/bundle/qwenpaw-openui/qwenpaw-openui-0.1.0.zip`。本地测试也使用这个 ZIP 或它的解压目录，包中已排除前端源码与开发依赖。

[examples/seeds.openui](examples/seeds.openui) 提供一个可复现的交互示例：滑块从 5 调到 8，总实验次数从 35 更新为 56，点击继续按钮提交当前值。

### 接入方式

前端注册 `openui-lang` 渲染器，并为聊天请求附上能力标记。后端 Middleware 为适用的 Console 请求添加由官方组件库生成的语言与组件说明。

流式更新使用官方解析器，完整语法片段逐步显示。渲染器持续挂载，具名子组件按语句身份保持状态，使后续内容到达时已有输入和选择得以保留。

`@Set` 和 `@Reset` 更新本地状态；`@ToAssistant` 通过 QwenPaw 消息队列提交动作文字、显式 context 和表单值；`@OpenUrl` 通过宿主打开 HTTP(S) 链接。Query、Mutation、工具 provider 和历史 UI patch 尚未接入。

构建产物包括 `dist/index.js` 和 `dist/system-prompt.txt`。前端复用宿主 React/ReactDOM，样式限定在插件界面内。`frontend/src/qwenpaw-host.d.ts` 保存公开 SDK 类型快照，升级宿主接口时同步更新。

官方 `ThemeProvider` 将 OpenUI 的视觉样式映射到 QwenPaw 的 `--app-*` 变量。字号变化会更新图表文字的测量结果，同时保留组件状态。组件布局和图表系列配色沿用 OpenUI。

运行时通过已注册的组件、内置函数和宿主动作解释 `openui-lang`。测试直接加载发布产物，覆盖脚本执行尝试、危险链接、未接入的工具调用，以及正常的本地交互。
