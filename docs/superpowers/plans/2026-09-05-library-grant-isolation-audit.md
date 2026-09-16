# 个人资料库授权与历史副本核验

## 授权规则

个人资料库读取同时要求可信当前用户拥有文档、当前 Agent 存在该用户的 active 授权。授权对象是用户与 Agent 的组合，不是把文档公开给使用该 Agent 的所有人。

核对路径：match_prompt_documents、reference_documents、read_text_for_agent、search_text、ChatFileReferences，以及 runtime builder 注册工具的身份闭包。数据库查询当前仅存在管理员账号的一条 active 资料库授权，普通账号没有授权。

新增真实文件服务集成测试覆盖同 Agent 不同用户、同用户未授权 Agent、撤销授权后的目录与读取拒绝、引用过程中不创建用户运行目录。相关 34 项测试通过；本轮未修改生产授权代码。

## 已隔离文件

经用户同意继续处理，将普通账号运行目录内的 AI写作需求文档.md 移到：

`E:/git_project/QwenPaw/tmp/private-document-quarantine-20260905/task42-user-default-ai-writing-requirements.md`

原路径：`working/user_workspaces/d5ef746c-4311-45fb-af5e-03742bd5af78/default/AI写作需求文档.md`。

移动前后 SHA256 均为 56E36AE9F41952CE2D4509DAADDBCBEF75606AED91F59ABFE81F84443A63260A。管理员个人资料库原件未动。可通过备份恢复。没有删除旧会话或衍生文件。

## 浏览器实测

普通账号新建空白会话，提出检查 AI 写作需求文档的请求。搜索不再列出原文档，模型实际读取的是 MiaoBi_AI_Introduction.md 等该账号已有文件，最终明确称找到的是英文简介并针对简介作答。不能把这项验证说成“相关私人信息已全部清除”。

## 未关闭边界

副本创建早于管理员此次资料库上传；日志只证明普通账号登录及后来读取，尚无创建动作的确切来源。旧会话已含正文，另有该账号历史生成的英文简介。若用户要求清除既往泄漏影响，需要另行确认这些数据的处置范围；不能静默批量删历史。

通用文件工具按用户排除项未修改。资料库服务授权测试通过不等于通用执行环境已实现完全文件隔离；隔离备份也不是工具沙箱。
