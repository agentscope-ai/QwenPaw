# HMarkdown

[![Downloads](https://img.shields.io/github/downloads/lidary-byte/HMarkdown/total?style=for-the-badge&logo=github)](https://github.com/lidary-byte/HMarkdown)
[![Last Version](https://img.shields.io/github/v/release/lidary-byte/HMarkdown?style=for-the-badge)](https://github.com/lidary-byte/HMarkdown/releases)
[![License](https://img.shields.io/github/license/lidary-byte/HMarkdown?style=for-the-badge)](LICENSE)
[![OpenHarmony](https://img.shields.io/github/v/release/lidary-byte/HMarkdown?style=for-the-badge&logo=harmonyos&color=76CE65
)](https://ohpm.openharmony.cn/#/cn/detail/@lidary%2Fmarkdown)
[![CHANGELOG](https://img.shields.io/badge/CHANGELOG-E87436?style=for-the-badge&logo=googledocs&logoColor=ffffff)](https://github.com/lidary-byte/HMarkdown/blob/main/Markdown/CHANGELOG.md)

基于[**marked**](https://github.com/markedjs/marked)的鸿蒙端markdown渲染库

## v3.0.0特性

1. 支持公式本地渲染
2. 支持子线程渲染
3. 完全重构

Tips:
1. 本次更新支持Api变动较大,如需旧版本请查看[→](https://github.com/lidary-byte/HMarkdown/blob/feat-v2.0.8)
2. v2.0.8因为没有考虑到子线程内存隔离问题会导致设置的插件不生效


<p align="center">
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/image_1.png" width="20%" alt="图1" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/image_2.png" width="20%" alt="图2" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/image_3.png" width="20%" alt="图3" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/image_4.png" width="20%" alt="图4" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/image_5.png" width="20%" alt="图5" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/dark_image_1.png" width="20%" alt="图6" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/dark_image_2.png" width="20%" alt="图7" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/dark_image_3.png" width="20%" alt="图8" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/dark_image_4.png" width="20%" alt="图9" />
  <img src="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/screen/dark_image_5.png" width="20%" alt="图10" />
</p>


---

## 参数

|               名称               | 是否必传 | 默认值       |          说明           |
|:------------------------------:|:----:|-----------|:---------------------:|
|            content             |  否   | ""        |     markdown文本内容      |
|             token              |  否   | []        | markdown文本内容解析后Tokens |
|            options             |  否   | undefined |      属性，主题等相关配置       |
| onLoading,  onSuccess ,onError |  否   | undefined | 加载状态回调(方面设置Loading等)  |

### MarkdownOptions参数

|         名称          | 是否必传 | 默认值                              |                                                                                         说明                                                                                          |
|:-------------------:|:----:|----------------------------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|
|        theme        |  否   | defaultTheme(参考Jetbrains的ui)     |                                                                                      亮色主题相关配置                                                                                       | 
|      darkTheme      |  否   | defaultDarkTheme(参考Jetbrains的ui) |                                                                                      暗色主题相关配置                                                                                       |
|      darkMode       |  否   | false                            |                                                                                       是否亮色/暗色                                                                                       |
|      lineSpace      |  否   | 12                               |                                                                                      item之间的间距                                                                                      | 
|    textLineSpace    |  否   | LengthMetrics.vp(12)             |                                                                                    item中text的行间距                                                                                    |
|       options       |  否   | undefined                        |                                                                 <a href="https://marked.js.org/using_advanced">marked相关配置</a>                                                               |
|     extensions      |  否   | undefined                        |   <a href="https://marked.js.org/using_advanced#extensions">marked插件</a>,可参考<a href="https://github.com/lidary-byte/HMarkdown/blob/feat-v3.0.0/Markdown/src/main/ets/core/plugins/latex.ets">数学公式</a>  |
|     imageClick      |  否   | undefined                        |                                                                                       图片点击事件                                                                                        |
|      linkClick      |  否   | undefined                        |                                                                                       超链接点击事件                                                                                       |
| customBlockBuilder  |  否   | undefined                        |                                                                                      自定义块元素渲染                                                                                       |
| customInlineBuilder |  否   | undefined                        |                                                                                      自定义行内元素渲染                                                                                      |
|      maxLines       |  否   | undefined                        |                                                                     如果是行内元素则显示最大行数(多为List列表内item都是Markdown时使用)                                                                      |

---

## 下载安装

```
ohpm install @lidary/markdown
```

---

## 导包

```typescript
// V2状态管理 不支持V1
import { Markdown } from '@lidary/markdown';
``` 

---

## 使用方式

```typescript
Markdown({
  content: this.text,
  options: {
    darkMode: this.isDark,
    options: {
      gfm: true
    },
    darkTheme: {
      themeColor: Color.Orange
    },
    imageClick: (url?: string) => {
      promptAction.showToast({
        message: `图片被点击:${url}`,
        duration: 1500,
        bottom: "center",
      })
    },
    linkClick: (url?: string) => {
      promptAction.showToast({
        message: `超链接被点击----url:${url}`,
        duration: 1500,
        bottom: "center",
      })
    }
  },
  onLoading: () => {
    this.isLoading = true
  },
  onError: () => {
    this.isLoading = false
  },
  onSuccess: () => {
    this.isLoading = false
  }
})
```

 
---

## 特性

-  [x] 支持标题语法
-  [x] 支持段落语法
-  [x] 支持分割线语法
-  [x] 支持代码语法
-  [x] 支持加粗语法
-  [x] 支持斜体语法
-  [x] 支持删除线语法
-  [x] 支持链接语法
-  [x] 支持表格语法
-  [x] 支持有序列表语法
-  [x] 支持无序列表语法
-  [x] 支持块引用语法
-  [x] 支持数学公式语法
-  [x] 支持图片语法
-  [x] 支持单独代码块功能
-  [x] 支持列表嵌套功能
-  [x] 支持文本样式设置
-  [x] 支持深浅主题色设置
-  [ ] 支持部分html语法
-  [ ] 支持任务列表语法

## [更新日志](https://github.com/lidary-byte/HMarkdown/blob/main/Markdown/CHANGELOG.md)

## 开源协议

本项目基于 [MIT License](https://gitee.com/daryl_code/HMarkdown/blob/main/Markdown/LICENSE) ，请自由地享受和参与开源