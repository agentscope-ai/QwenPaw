---
name: guidance
description: "回答用户关于 CoPaw 安装与配置的问题：优先定位并阅读本地文档，再提炼答案；若本地信息不足，兜底访问官网文档。"
categories:
  - copaw
  - documentation
tags:
  - help
  - setup
  - configuration
  - onboarding
metadata:
  builtin_skill_version: "1.0"
  copaw:
    emoji: "🧭"
    requires: {}
---

# CoPaw 安装与配置问答指南

当用户询问 **CoPaw 的安装、初始化、环境配置、依赖要求、常见配置项** 时，使用本 skill。

核心原则：

- 先查本地文档，再回答
- 回答要基于已读到的内容，不臆测
- 回答语言与用户提问语言保持一致

## 标准流程


### 第一步：定位文档位置

**查找记忆中的文档目录**

首先你可以查看memory中是否有文档目录，如果有则直接使用，如果没有则继续执行下一步。

```bash
# 获取memory中的文档目录
DOC_DIR=$(find ~/.copaw/memory/ -type d -name "docs")
```

如果 memory 中没有文档目录，则继续执行下面的逻辑。

**检查项目源码中的文档目录**

执行以下脚本逻辑来获取变量 $COPAW_ROOT：

```bash
# 获取二进制绝对路径
COP_PATH=$(which copaw 2>/dev/null || whereis copaw | awk '{print $2}')

# 逻辑推导：如果路径包含 .copaw/bin/copaw，则根目录在其上三层
# 例如：/path/to/CoPaw/.copaw/bin/copaw -> /path/to/CoPaw
if [[ "$COP_PATH" == *".copaw/bin/copaw" ]]; then
    COPAW_ROOT=$(echo "$COP_PATH" | sed 's/\/\.copaw\/bin\/copaw//')
else
    # 兜底：尝试获取所在目录的父目录
    COPAW_ROOT=$(dirname $(dirname "$COP_PATH") 2>/dev/null || echo ".")
fi

echo "Detected CoPaw Root: $COPAW_ROOT"
```

验证并列出文档目录：
使用推导出的 $COPAW_ROOT 定位文档：

```bash
# 组合标准文档路径
="$COPAW_ROOT/website/public/docs/"

# 检查路径是否存在并列出文件
if [ -d "$DOC_DIR" ]; then
    find "$DOC_DIR" -type f -name "*.md" | head -n 100
else
    # 如果推导路径不对，执行全局模糊搜索
    find "$COPAW_ROOT" -type d -name "docs" | grep "website/public/docs"
fi
```
**如果项目文档不存在，搜索工作目录**

如果还是找不到文档，搜索 copaw 安装路径下的可用文档内容：

```bash
# 寻找 faq.en.md 或 config.zh.md 等特征文件
FILE_PATH=$(find . -type f -name "faq.en.md" -o -name "config.zh.md" | head -n 1)
if [ -n "$FILE_PATH" ]; then
    # 使用 dirname 获取该文件所在的目录
    DOC_DIR=$(dirname "$FILE_PATH")
fi
```
如果找到了文档目录，请你记录在 memory 中，格式为：

```markdown
# 文档目录
$DOC_DIR = <doc_path>
```

### 第二步：文档检索与匹配

文档文件命名格式为 `<topic>.<lang>.md`（如 `config.zh.md`、`config.en.md`、`quickstart.zh.md`）。

使用 find 命令在目标目录中列出所有符合后缀的文档，并根据文件名关键字（如 install, env, setup）锁定目标作为 <doc_path>。

```bash
# 列出所有符合后缀的文档
find $DOC_DIR -type f -name "*.md"
```

如果没有合适的文档，则在下一步阅读所有文档内容。


### 第三步：阅读文档内容

找到候选文档后，读取并确认与问题相关的段落。可使用：

- `cat <doc_path>`
- `file_reader` skill（推荐用于更长文档或分段读取）

如果文档很长，优先读取和问题最相关的章节（安装步骤、配置项、示例命令、注意事项、版本要求）。

### 第四步：提取信息并作答

从文档中提取关键信息，组织成可执行答案：

- 先给直接结论
- 再给步骤/命令/配置示例
- 补充必要前置条件与常见坑

语言要求：回答语言必须与用户提问语言一致（中文问就中文答，英文问就英文答）。

### 第五步（可选）：官网检索

若前面步骤无法完成（本地无文档、文档缺失、信息不足），使用官网作为兜底：

- http://copaw.agentscope.io/

基于官网可获得内容继续回答，并在答案中明确说明该结论来自官网文档。

## 输出质量要求

- 不编造不存在的配置项或命令
- 遇到版本差异时，明确标注“需以当前文档版本为准”
- 涉及路径、命令、配置键时，尽量给可复制的原文片段
- 若信息仍不足，明确缺口并告诉用户还需要哪类信息（例如操作系统、安装方式、报错日志）
