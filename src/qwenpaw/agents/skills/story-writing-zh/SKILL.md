---
name: story-writing
description: "在主聊天中创作故事、人物小传、大纲和剧本，并将完整定稿交给 QwenPaw Creator 制作单部影片。适用于故事创作、剧本修改或将已确认故事移交 Creator。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "✍️"
    requires: {}
---

# 在主聊天创作，在 Creator 制作

先在主聊天中帮助用户完成创作；写作本身不依赖 Creator。使用用户的语言。
只询问会实质影响作品的缺失信息，其余明确合理假设后直接推进。

## 完成整份故事

1. 明确受众、形式、时长、语言、基调和核心创意。
2. 展开主角动机、冲突、代价与转折。结构服务于作品：产品片、安静的
   视觉小品不必强加传统戏剧冲突。
3. 维护人物设定：稳定 ID、名字、描述及连续性限制。记录每份参考的
   标签、用户提供的 URI 与用途。
4. 写出逐场景完整剧本：场景、动作、逐字对白、说话者、旁白、声音和结尾。
   不以梗概替代正文。
5. 与用户迭代，区分已确认决定与待议建议，记录限制条件。保留确认后的
   原文、多语言对白和有意留白；不要给明确无对白的结尾擅自添加旁白。

向用户呈现可读的作品，不要求用户理解数据格式。单纯写作或修改剧本
不意味着允许开始生成图片或视频。

## 将完整定稿移交 Creator

用户要求移交时：

1. 调用 `list_apps`，再 `describe_action` 获取已授权的
   `qwenpaw-creator` / `prepare-production`。以返回的 schema 为准，
   不猜测不存在的 action 或权限。
2. 构造完整 `story`：
   - `schema_version: 1`、稳定 `story_id`、`revision: 1`、`title`。
   - `logline`、`synopsis`、**完整且逐字保留的 `script_markdown`**。
   - `audience`、`tone`、`language`、已知时的 `duration_seconds`、
     `aspect_ratio`、`resolution`、`scenario`。
   - `characters`：`{id, name, description, continuity}`。
   - `references`：`{id, label, uri, notes}`。
   - 完整的 `decisions` 与 `constraints`。
3. 用稳定 request ID 委派 `prepare-production`，输入 `{"story": ...}`。
   不确定是否成功时，用完全相同的 ID 和输入重试。收到 accepted 后结束
   本轮，交给 Host 任务卡监控，完成后会回到主聊天；不要在本轮轮询或睡眠等待。
4. 完成后保留 task ID 及结构化回执：`project_id`、`story_revision`、
   `story_digest`、`project_etag`、`project_generation`。任务还会发布完整
   JSON 故事包及 Markdown 剧本。使用完成任务的 ID 调用 `open_app`，
   打开已经导入内容的项目。如实说明“已准备”，不要声称“已生成成片”。

参考说明与 URI 会完整保存，但此操作不会复制或下载参考文件。URI 出现在
故事包中，不代表图片或附件已经可用于制作；制作依赖该素材时，应在 Creator
完成必要的素材导入。

## 在同一项目修改或制作

- 用户确认修改后，describe `revise-story`：提交**完整**新故事包，沿用
  story ID，revision 加一，并附上上次回执中的 `project_id`、
  `expected_story_digest`、`expected_project_etag`。未修改对白逐字保留。
  历史版本会保留，原有剧本批准会失效；只改变已确认决定也需要重新批准。
  修改前须完成或明确取消正在进行的制作；繁忙项目会拒绝修改，不会在运行目标
  下替换故事。
- 用户明确要求制作时，describe `produce-video`：提交 `project_id`、
  `story_revision`、`story_digest` 和 `expected_project_etag`
  （对应回执的 `project_etag`）。这会确认该确切版本进入制作，但模型配置、
  媒体执行与费用授权仍需按任务提示处理。
- 用户同时要求移交和制作时，先 prepare；完成后的 continuation 使用返回
  回执及用户已有授权继续 produce。不要虚构项目 ID 或跳过准备。
- 冲突说明 Creator 已有修改或另一个版本已更新。打开项目供用户核对，
  不要静默刷新 ETag、覆盖 Creator 修改、另建替代项目或换 request ID 反复重试。
- 在另一聊天中继续时，从已记录任务/回执取回身份信息，或通过
  `list_app_artifacts` 查找已发布产物；不要猜测版本与 ID。同一用户、同一
  工作空间支持复用；知道项目 ID 不意味着可以访问其他用户或工作空间的项目。

制作 action 当前支持**单部影片、单个有效叙事 Timeline**。多集、多部作品
需明确拆分并分别移交，不能悄悄压成一份剧本。Creator 或 action 不可用时，
继续完成写作并说明缺失的移交能力，不声称已创建项目。
