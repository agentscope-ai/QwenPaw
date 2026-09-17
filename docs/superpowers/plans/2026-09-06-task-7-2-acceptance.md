# Task 7.2 集成验收记录

**最终状态（2026-09-06）：实施、备份迁移、构建和真实浏览器验收已完成。18089运行，schema为0015。下方过程记录按当时状态保留；最终证据与限制见文末。等待用户验收Task7.2，不自动推进7.3。**

## 当前边界

- 用户确认按 Agent 授权和固定发布快照设计；允许测试后执行增量迁移，迁移前备份核对。
- 代码目录 E:/git_project/QwenPaw；数据目录 tmp/task-2-1-acceptance/working；原 18089 服务 PID 21524。本任务开始未改服务或真实数据。
- 实现者只使用隔离测试。不会使用真实供应商凭据补测试环境，不创建工作树，不提交，不删除已有数据。

## 前置测试

命令：`.venv/Scripts/python.exe -m pytest tests/integration/test_skills_pool.py tests/integration/test_skills_pool_autosync.py tests/integration/test_skills_agent_scoped.py tests/unit/app/routers/test_skills_router.py tests/unit/agents/test_skill_runtime.py -q --tb=short`

结果：20 failed、46 passed、1 既有 Starlette 弃用警告，35.18s，exit 1。多数失败发生在测试创建 Agent 的前置请求（400：No active model configured），并非技能授权行为断言。Hub install 用例另需针对性核实。此结果仅作基线，不计为本轮通过。

## 验收清单

前端基线：`npm run test:run -- src/api/modules/skill.test.ts src/pages/Agent/Skills/useSkills.test.ts src/pages/Agent/Skills/useSkillFilter.test.ts src/pages/Settings/SkillPool/builtinNotice.test.ts`：4 files、53 tests passed，exit 0，无告警输出。

真实数据库只读前置：qwenpaw_test_migrations / qwenpaw_task21_acceptance，revision=0014_artifact_lifecycle。skill_pool_items、skill_pool_versions、agent_skills、skill_publish_requests 各 0 条。此计数不代表文件技能为空，不能据此删除或推断授权。

部署前 Chrome 双角色登录基线（tmp/task-7-2-browser-baseline.py）：管理员和普通用户均可打开 /skills，GET /api/skills 返回 2 项，GET /api/skills/pool 返回 36 项，均 200；新 /api/skill-catalog 返回 404。此为旧服务未部署状态，仅输出数量，无技能内容或配置。

- [x] 根迁移链新增版本经隔离 PG 升级验证；真实 schema 备份可读，迁移后 head 正确。
- [x] 管理员治理入口及 Agent 授权；普通用户直接调用管理接口 403。
- [x] 授权 Agent owner/collaborator 可载入；use-only 和未授权 Agent 拒绝。
- [x] 发布申请固定提交快照，源变化不改变批准内容，重复审批不会产生重复版本。
- [x] 技能目录、脚本、引用内容变化标记 detached；配置/标签/频道/启停变化保持来源状态。
- [x] 更新与恢复要求明确确认、当前授权和内容一致性；detached 不被自动广播覆盖。
- [x] 原启停、频道、配置、标签及扫描冲突处理保真；无半成品或隐式删除旧副本。
- [x] 两账户切换不复用旧目录、申请和操作状态；私有配置不进入共享版本。
- [x] 定向测试、独立审查、前端构建、真实浏览器 TASK72 测试。
- [x] 原 18089 服务可登录，原模型治理状态、凭据和已有技能保持不变。

## 实施过程证据（未部署）

- Task 1 治理基础及第一轮修复：104 项相关测试通过，1 条既有 Starlette 弃用警告；独立规格/质量复审通过。详情及命令见 `.superpowers/sdd/2026-09-06-task-7-2-skill-governance/task-1-report.md`。
- 修复名为 hub 的技能可能绕过读取角色限制的问题；共享 capture/verify 对现有硬编码凭据签名执行不可被可选扫描配置跳过的检查。静态签名不是任意秘密的完备识别，不宣称100%检测。
- 只读健康复核：127.0.0.1:18089 / PID21524，GET /login=200；尚未构建、迁移或重启。

## 部署操作门控（待执行）

1. 以最终审查后冻结代码跑集成测试和完整前端构建。
2. 只读确认原端口进程、schema当前revision与目标0015；任何不一致先停止，不自动重建schema。
3. 用原容器内 pg_dump 为 qwenpaw_task21_acceptance 建独立TASK72英文命名备份（custom格式），复制到原项目tmp独立备份目录，pg_restore --list验证归档可读取。不打印dump内容或连接串。
4. 显式指定 schema 执行0014→0015增量迁移；确认旧表/模型治理数量状态不变、授权表存在且无自动grant。失败不自动downgrade或删除数据。
5. 原启动脚本、原工作/secret目录、原18089端口重启，仅本流程执行。
6. 浏览器仅创建TASK72标记技能和必要授权，保留所有已有技能；校验授权/载入/申请/固定快照审批/脱离/恢复及拒绝请求，不向外部模型发送推理或泄漏敏感内容。

## 新任务续接记录（尚未部署）

- 已重新读取原任务中的实施和增量迁移确认。续接时18089无监听；PostgreSQL容器正常，真实schema仍为0014，四张技能表仍为空。
- Task2独立审查发现改名丢失来源绑定、缺少SKILL.md后无法列出确认哈希及恢复；进入修复轮，不能将历史128 passed当作Task2验收完成。
- 主流程具名执行 `tests/integration/test_migrations.py::test_revision_chain_is_linear_and_named_by_domain`，结果1 failed：旧契约缺少0015。已要求修复者补齐新迁移及授权表契约并验证隔离PG。
- 续接时基线落盘 `tmp/task72-preservation-baseline.json`：584个技能内容文件、7份manifest的既有条目哈希；池manifest及锁文件从内容文件集合单独处理。首次verify显示文件和既有条目均无变化。旧任务仅存functions store的基线无法跨任务读取，本基线只证明续接之后的保真。
- `tmp/task72-model-db-baseline.json` 保存3张模型表的完整行数据哈希；`tmp/task72-config-baseline.json` 保存7个配置/secret文件哈希，仅保存哈希而非凭据内容。
- 已准备 `tmp/task72-migrate.py`、`tmp/task72-browser-acceptance.py`；脚本语法编译通过，但迁移、服务启动、浏览器验收均尚未执行。
- Task2修复后组合回归145 passed（包含完整迁移4 passed）、1既有warning；限定复审通过，Task3已进入前端实施。
- 主流程复跑原五文件技能基线：20 failed、46 passed、1 warning，35.54s。日志 `tmp/task72-legacy-regression.log` 中20次失败全部为创建Agent的201前置断言（实际400），包含之前待核实的Hub安装测试；与原基线一致，尚未覆盖这些用例后续技能操作。
- 已用仅作用于两个技能测试模块的本地MockLLMHandler fixture补齐模型前置，保留业务校验和全部原断言；原五文件66 passed，fixture独立审查通过。Hub用例仍只验证任务终态，不能据此声称真实下载成功。
- 主流程执行 `tmp/task72-run-backend.py` 合并14个后端测试文件，最终 **192 passed、1 warning，152.33s，exit 0**。包含治理/生命周期/完整迁移/旧技能/权限回归；日志 `tmp/task72-final-backend.log`。该命令使用随机隔离PG schema和本地假模型服务，未访问真实模型供应商。
- Task3首轮26文件199项通过、tsc exit0，但独立审查发现5项认证/缓存/批量交互缺口，已进入修复轮；不将测试通过视为前端审查通过。详见task-3-review.md。
- 首批前端before未及时落盘，已从本子任务完整FileChange记录恢复并正向重放；最终46文件独立差异重放通过，主流程核对文件及diff哈希一致。报告明确披露事后恢复来源，没有用HEAD或截断的app差异冒充原始版本。
- Task3限定修复后26文件215项通过、tsc exit0；5项认证/缓存/批量交互问题均经独立限定复审关闭。
- 最终整体审查发现5项跨层缺口：旧上传复制私有配置、改名覆盖无hash确认、Legacy池交互回归、已有副本广播预检失败、显式删除后同名重建残留来源。报告 `task72-final-review.md`，结论Needs fixes；已集中修复中，真实迁移和服务启动继续暂缓。
- 迁移脚本补强为本地/容器归档SHA256一致且完整只读解码成功后才迁移。此检查不等同于恢复演练；尚未实际执行。

## 最终交付与验证（2026-09-06）

Task7.2已完成：管理员按Agent授权、固定快照申请与审核，所有者/协作者授权载入，副本来源/脱离状态，带hash的恢复、更新、改名覆盖和人工广播，以及Legacy原池交互。撤销不删除旧副本；显式删除解除当前来源且保留历史申请。复用原页面、存储和事务补偿，不新增依赖或另一套技能实现。

### 审查与测试

- 分项审查及修复复审完成。最终整体审查的F1–F5经独立限定复审全部ADDRESSED；该复审另发现缓存过滤回归N1。主流程以暂存完整复制、最终保持原过滤的最小修改解决N1，2项RED转为通过，相关上传/快照37项通过。`task72-final-fix-review.md`保留当时未通过结论；`task72-n1-resolution.md`明确记录主流程残余处置，不冒称第二次独立复审。
- 后端完整回归198 passed，最后边界/生命周期42 passed，N1上传/快照37 passed；集合有重叠，**累计215个不同用例有通过证据**，不是将三次结果相加。原五文件技能回归66 passed，原20项模型前置失败已用隔离假模型fixture修复，没有削弱原业务断言。
- 前端最终27文件、223 passed；实际app/node TypeScript检查均exit0。`npm run build` exit0，Vite47.43s，Monaco CSS验证通过。日志：`tmp/task72-final-fix-final-vitest.log`、`tmp/task72-final-fix-final-boundaries-backend.log`、`tmp/task72-final-fix-n1-green.log`、`tmp/task72-build.log`。
- 构建仍报告原分包循环依赖、动态/静态混合导入及大chunk提示；测试保留Starlette/httpx弃用、jsdom伪元素getComputedStyle提示。未更新依赖或隐藏警告。

### 真实数据库、服务和数据保真

- 原容器 `qwenpaw-pg`，数据库 `qwenpaw_test_migrations`，schema `qwenpaw_task21_acceptance`：**0014_artifact_lifecycle → 0015_skill_governance**。
- 备份：`tmp/task72-backup-20260906T105607Z/acceptance.dump`，SHA256 `665bc4453a455f7e1180cb82fdeb2fc206efa2a772eb9905037604c275444e65`。本地/容器hash一致，归档目录验证及完整只读解码通过；**未做恢复演练**。详见该目录 `migration-result.json`。
- 原 `tmp/start-18089.ps1`、原working/secret目录启动；服务 `http://127.0.0.1:18089`，最终监听PID **49040**，登录页200，三个独立浏览器账户登录成功。未操作其他Legacy实例。
- 迁移后未自动grant。验收结束：3个TASK72池条目、6版本、3安装记录、3发布申请、3授权记录，**有效授权0**。两次脚本中断留下的样例及历史记录保留，临时授权已全部撤销；另有一次旧上传形成的TASK72池草稿。未删除既有技能或清理历史测试材料。
- 最终 `tmp/task72-verify-final.py` exit0：**584个原技能文件与7份manifest既有条目未变；7个配置/secret文件未变；model_providers/models/model_grants三表完整行hash未变**。原模型治理开关未调整。证据 `tmp/task72-final-preservation.json`、`tmp/task72-final-database-counts.json`。

### 真实浏览器验收范围

最终脚本 `tmp/task72-browser-acceptance.py` exit0，14项检查通过，记录 `tmp/TASK72-20260906105941-acceptance.json` 和 `tmp/task72-browser-acceptance-3.log`。

- 真实Chrome页面交互：三账户登录、管理员初始化预览不默认选中、普通所有者切换Agent并打开/取消/确认恢复弹窗；确认前零写请求，确认携带实际hash，成功后恢复按钮消失。额外查看use-only页面无发布入口。稳定截图 `tmp/task72-admin-final.png`、`tmp/task72-member-final.png`、`tmp/task72-use-only-final.png`；恢复过程截图另保留。
- 在同一真实登录上下文通过HTTP验证：管理/跨Agent拒绝，明确登记与授权后载入，提交后源变化不影响固定快照、幂等审批；广播预览不改内容、陈旧确认拒绝、正常更新/unchanged；恢复/更新保留停用状态、console频道、标签与私有配置；改名保留来源、撤销仍保留副本且拒绝恢复；陈旧改名hash拒绝、旧上传不复制私有config、删除后同名创建无来源且历史快照可读。
- 两次中间脚本失败均保留：首轮错误假设空频道列表原样保存，实际原逻辑规范化为all；改用明确console频道验证保真。第二轮CSS选择器假设antd前缀，实际为qwenpaw前缀，核对真实DOM后修正。额外截图脚本的带图标按钮精确名称定位曾超时，改为可见文字定位后完成。未通过修改业务断言掩盖产品缺陷。

### 限制及后续确认门

- Legacy创建/编辑/上传/下载和角色/身份切换覆盖来自隔离后端与页面网络桩；未声称所有浏览器操作或所有外网Hub下载均成功。真实Hub旧用例仅验证任务终态，新增Hub重建仅替换远程材料获取。
- 既有use-only提示标题显示 `common.readOnly` 的缺失翻译键，本轮before中已存在；不影响权限，作为非阻断既有展示问题记录。
- 强杀/断电时不保证跨数据库与文件系统原子恢复；历史申请FK引用的目标在改名覆盖时仍可能安全失败并补偿。共享静态凭据签名不保证识别任意秘密。
- 首批Task3 before为事后从完整FileChange严格恢复，已披露并重放；本轮最终修复与N1均事前备份。累计差异、阶段报告和哈希清单位于 `.superpowers/sdd/2026-09-06-task-7-2-skill-governance/`，没有以脏工作区HEAD冒充本任务基线。
- **未执行git提交、推送、分支、工作树或用户数据清理。Task7.2等待用户验收，Task7.3未开始。**
