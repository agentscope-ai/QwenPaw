# 架构设计

本页从宏观层面介绍 QwenPaw 的构成：它实现的**智能体操作系统（Agent OS）**，以及它依托的 **AgentScope** 基座。本页只讲设计中相对稳定的部分，不点名那些会随代码频繁变动的模块和类。还没做的部分会标注出来，并链接到[路线图](./roadmap)。

如果你只是想*使用* QwenPaw，请从[项目介绍](./intro)和[快速开始](./quickstart)入手。本页写给贡献者，以及想搞清楚底层原理的人。

---

## 一图看懂智能体操作系统

QwenPaw 完全跑在你自己的环境里，是一个常驻服务。一次安装就能托管**多个互相独立的智能体**。每个智能体有一个隔离的**工作区**；每个请求都交给**运行时**来执行，运行时在治理和沙箱这一层之下，把智能体的模型、工具、记忆、Skills 和连接器串到一起。

可以把 QwenPaw 看成一个面向智能体的小型操作系统。它的“内核”是 [AgentScope 2.0](https://github.com/agentscope-ai/agentscope)，在进程内提供智能体循环、会话存储、事件流和工具层。QwenPaw 是其上的操作系统层，管着智能体要用到的**资源维度**——工作区文件、记忆、Skills、驱动（连接器）和模型——以及管控这些资源访问的信任主干。

<svg viewBox="0 0 900 684" width="100%" role="img" aria-label="一图看懂 QwenPaw 智能体操作系统：上层是运行时调度层；下层是每个智能体专属的工作区，内含按颜色区分的资源泳道（记忆、Skills、工具、其他）、治理面板和沙箱执行底座，旁边是独立的驱动（连接器）栏；整体构建在 AgentScope 基座之上。" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpMapArrow" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="currentColor" fill-opacity="0.45"/>
    </marker>
  </defs>
  <!-- Title -->
  <text x="450" y="30" text-anchor="middle" font-size="16" font-weight="700" fill="currentColor">QwenPaw Agent OS · 一图看懂</text>
  <text x="450" y="49" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">上层 Runtime ／ 下层 Workspace ‖ Drivers · 构建于 AgentScope 基座之上</text>
  <!-- Surfaces strip -->
  <rect x="20" y="60" width="860" height="40" rx="9" fill="currentColor" fill-opacity="0.03" stroke="currentColor" stroke-opacity="0.18"/>
  <text x="34" y="84" font-size="10" letter-spacing="1.2" font-weight="700" fill="currentColor" fill-opacity="0.7">入口</text>
  <g font-size="11" fill="currentColor">
    <rect x="170" y="68" width="168" height="24" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="254" y="84" text-anchor="middle">频道（IM）</text>
    <rect x="348" y="68" width="168" height="24" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="432" y="84" text-anchor="middle">控制台（Web）</text>
    <rect x="526" y="68" width="168" height="24" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="610" y="84" text-anchor="middle">终端 UI</text>
    <rect x="704" y="68" width="168" height="24" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="788" y="84" text-anchor="middle">CLI</text>
  </g>
  <line x1="450" y1="100" x2="450" y2="112" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4" marker-end="url(#qpMapArrow)"/>
  <!-- Runtime tier -->
  <rect x="20" y="114" width="860" height="118" rx="10" fill="#a855f7" fill-opacity="0.05" stroke="#a855f7" stroke-opacity="0.45"/>
  <rect x="30" y="124" width="12" height="12" rx="3" fill="#a855f7"/>
  <text x="50" y="134" font-size="11.5" font-weight="700" fill="#a855f7">运行时 · 请求调度 · 上层</text>
  <text x="30" y="153" font-size="10" fill="currentColor" fill-opacity="0.62">一次安装托管多个智能体 —— 编排 · 路由 · 组装 · 运行 · 流式返回</text>
  <g>
    <rect x="40" y="164" width="193" height="54" rx="7" fill="#a855f7" fill-opacity="0.1" stroke="#a855f7" stroke-opacity="0.55"/><text x="136" y="188" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">请求路由器</text><text x="136" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">路由到目标智能体</text>
    <rect x="249" y="164" width="193" height="54" rx="7" fill="#a855f7" fill-opacity="0.1" stroke="#a855f7" stroke-opacity="0.55"/><text x="345" y="188" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">运行时生命周期</text><text x="345" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">钩子阶段 · 模式</text>
    <rect x="458" y="164" width="193" height="54" rx="7" fill="#a855f7" fill-opacity="0.1" stroke="#a855f7" stroke-opacity="0.55"/><text x="554" y="188" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">智能体 — ReAct 循环</text><text x="554" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">上下文策略 · 按请求组装</text>
    <rect x="667" y="164" width="193" height="54" rx="7" fill="#a855f7" fill-opacity="0.1" stroke="#a855f7" stroke-opacity="0.55"/><text x="763" y="188" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">Harness 适配器</text><text x="763" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">外部 agent · ACP</text>
  </g>
  <line x1="450" y1="232" x2="450" y2="246" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4" marker-end="url(#qpMapArrow)"/>
  <text x="462" y="244" font-size="9" fill="currentColor" fill-opacity="0.55">路由到工作区</text>
  <!-- Workspace container -->
  <rect x="20" y="248" width="690" height="336" rx="10" fill="currentColor" fill-opacity="0.02" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="34" y="272" font-size="12" font-weight="700" fill="currentColor">工作区 · 每个智能体一个隔离空间</text>
  <text x="34" y="288" font-size="10" fill="currentColor" fill-opacity="0.6">= 资源 · 治理 · 沙箱（治理 + 沙箱 = 信任主干）</text>
  <!-- Resources sub-box -->
  <rect x="32" y="300" width="456" height="192" rx="8" fill="currentColor" fill-opacity="0.02" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="44" y="320" font-size="10.5" font-weight="700" fill="currentColor" fill-opacity="0.82">被治理资源 · 智能体所用之物</text>
  <!-- memory lane -->
  <rect x="44" y="330" width="102" height="140" rx="7" fill="#2fb26b" fill-opacity="0.07" stroke="#2fb26b" stroke-opacity="0.4"/>
  <text x="95" y="348" text-anchor="middle" font-size="11" font-weight="700" fill="#2fb26b">记忆</text>
  <rect x="52" y="358" width="86" height="42" rx="6" fill="#2fb26b" fill-opacity="0.1" stroke="#2fb26b" stroke-opacity="0.5"/><text x="95" y="384" text-anchor="middle" font-size="10" fill="currentColor">召回 / 写入</text>
  <rect x="52" y="408" width="86" height="42" rx="6" fill="#2fb26b" fill-opacity="0.1" stroke="#2fb26b" stroke-opacity="0.5"/><text x="95" y="434" text-anchor="middle" font-size="10" fill="currentColor">Markdown 文件</text>
  <!-- skills lane -->
  <rect x="154" y="330" width="102" height="140" rx="7" fill="#e0a021" fill-opacity="0.07" stroke="#e0a021" stroke-opacity="0.4"/>
  <text x="205" y="348" text-anchor="middle" font-size="11" font-weight="700" fill="#e0a021">Skills</text>
  <rect x="162" y="358" width="86" height="42" rx="6" fill="#e0a021" fill-opacity="0.1" stroke="#e0a021" stroke-opacity="0.5"/><text x="205" y="384" text-anchor="middle" font-size="10" fill="currentColor">Skill 目录</text>
  <rect x="162" y="408" width="86" height="42" rx="6" fill="#e0a021" fill-opacity="0.1" stroke="#e0a021" stroke-opacity="0.5"/><text x="205" y="434" text-anchor="middle" font-size="10" fill="currentColor">共享池</text>
  <!-- tools lane -->
  <rect x="264" y="330" width="102" height="140" rx="7" fill="#12b0c6" fill-opacity="0.07" stroke="#12b0c6" stroke-opacity="0.4"/>
  <text x="315" y="348" text-anchor="middle" font-size="11" font-weight="700" fill="#12b0c6">工具</text>
  <rect x="272" y="358" width="86" height="42" rx="6" fill="#12b0c6" fill-opacity="0.1" stroke="#12b0c6" stroke-opacity="0.5"/><text x="315" y="384" text-anchor="middle" font-size="10" fill="currentColor">文件 · Shell</text>
  <rect x="272" y="408" width="86" height="42" rx="6" fill="#12b0c6" fill-opacity="0.1" stroke="#12b0c6" stroke-opacity="0.5"/><text x="315" y="434" text-anchor="middle" font-size="10" fill="currentColor">搜索 · 网页</text>
  <!-- others lane -->
  <rect x="374" y="330" width="102" height="140" rx="7" fill="#9d8579" fill-opacity="0.07" stroke="#9d8579" stroke-opacity="0.4"/>
  <text x="425" y="348" text-anchor="middle" font-size="11" font-weight="700" fill="#9d8579">其他</text>
  <rect x="382" y="358" width="86" height="42" rx="6" fill="#9d8579" fill-opacity="0.1" stroke="#9d8579" stroke-opacity="0.5"/><text x="425" y="384" text-anchor="middle" font-size="10" fill="currentColor">模型</text>
  <rect x="382" y="408" width="86" height="42" rx="6" fill="#9d8579" fill-opacity="0.1" stroke="#9d8579" stroke-opacity="0.5"/><text x="425" y="434" text-anchor="middle" font-size="10" fill="currentColor">会话</text>
  <text x="260" y="484" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">全部落地为磁盘文件 —— Markdown、JSON、目录。</text>
  <!-- Governance sub-box -->
  <rect x="500" y="300" width="198" height="192" rx="8" fill="#4f8cf7" fill-opacity="0.06" stroke="#4f8cf7" stroke-opacity="0.5"/>
  <text x="512" y="320" font-size="11" font-weight="700" fill="#4f8cf7">治理面</text>
  <text x="512" y="335" font-size="9.5" fill="currentColor" fill-opacity="0.6">每个动作都要经过</text>
  <rect x="512" y="344" width="174" height="40" rx="6" fill="#4f8cf7" fill-opacity="0.1" stroke="#4f8cf7" stroke-opacity="0.5"/><text x="599" y="361" text-anchor="middle" font-size="10.5" font-weight="600" fill="currentColor">治理策略</text><text x="599" y="376" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.62">允许 · 拒绝 · 询问 · 沙箱</text>
  <rect x="512" y="390" width="174" height="26" rx="6" fill="#4f8cf7" fill-opacity="0.1" stroke="#4f8cf7" stroke-opacity="0.5"/><text x="599" y="407" text-anchor="middle" font-size="10" fill="currentColor">工具守卫 · 内容审查</text>
  <rect x="512" y="422" width="174" height="26" rx="6" fill="#4f8cf7" fill-opacity="0.1" stroke="#4f8cf7" stroke-opacity="0.5"/><text x="599" y="439" text-anchor="middle" font-size="10" fill="currentColor">审批 · 技能扫描器</text>
  <rect x="512" y="454" width="174" height="26" rx="6" fill="#4f8cf7" fill-opacity="0.1" stroke="#4f8cf7" stroke-opacity="0.5"/><text x="599" y="471" text-anchor="middle" font-size="10" fill="currentColor">加密密钥库</text>
  <!-- Sandbox band -->
  <rect x="32" y="504" width="666" height="62" rx="8" fill="#f0921f" fill-opacity="0.08" stroke="#f0921f" stroke-opacity="0.5"/>
  <rect x="44" y="514" width="12" height="12" rx="3" fill="#f0921f"/>
  <text x="62" y="524" font-size="11" font-weight="700" fill="#f0921f">沙箱 · 执行底座</text>
  <text x="250" y="524" font-size="9.5" fill="currentColor" fill-opacity="0.6">每次工具调用新建，用完销毁</text>
  <text x="365" y="548" text-anchor="middle" font-size="10.5" fill="currentColor">原生 OS 隔离 —— macOS seatbelt · Linux bubblewrap/landlock · Windows AppContainer · 或不用</text>
  <!-- Drivers column -->
  <rect x="722" y="248" width="158" height="336" rx="10" fill="#eb5545" fill-opacity="0.05" stroke="#eb5545" stroke-opacity="0.45"/>
  <rect x="734" y="266" width="12" height="12" rx="3" fill="#eb5545"/>
  <text x="752" y="276" font-size="11.5" font-weight="700" fill="#eb5545">驱动</text>
  <text x="734" y="294" font-size="9.5" fill="currentColor" fill-opacity="0.6">对接外部系统</text>
  <rect x="734" y="304" width="134" height="50" rx="7" fill="#eb5545" fill-opacity="0.1" stroke="#eb5545" stroke-opacity="0.55"/><text x="801" y="326" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor">连接器</text><text x="801" y="342" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.62">协议中立层</text>
  <rect x="734" y="362" width="134" height="50" rx="7" fill="#eb5545" fill-opacity="0.1" stroke="#eb5545" stroke-opacity="0.55"/><text x="801" y="384" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor">MCP 服务</text><text x="801" y="400" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.62">外部工具 → agent</text>
  <rect x="734" y="420" width="134" height="50" rx="7" fill="#eb5545" fill-opacity="0.1" stroke="#eb5545" stroke-opacity="0.55"/><text x="801" y="442" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor">凭据 + 策略</text><text x="801" y="458" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.62">按次调用管控</text>
  <text x="801" y="500" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.6">与频道不同 ——</text>
  <text x="801" y="513" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.6">频道是人找 agent 的入口。</text>
  <line x1="450" y1="584" x2="450" y2="596" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4" marker-end="url(#qpMapArrow)"/>
  <!-- Foundation -->
  <rect x="20" y="596" width="860" height="48" rx="10" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/>
  <text x="450" y="618" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">基座 · AgentScope 2.0</text>
  <text x="450" y="634" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">智能体循环 · 会话 · 事件流 · 工具层 —— 作为库在进程内使用</text>
  <!-- Legend -->
  <text x="20" y="669" font-size="10" font-weight="700" fill="currentColor" fill-opacity="0.7">图例</text>
  <g font-size="10" fill="currentColor">
    <rect x="64" y="659" width="12" height="12" rx="3" fill="#4f8cf7"/><text x="80" y="669">治理</text>
    <rect x="140" y="659" width="12" height="12" rx="3" fill="#2fb26b"/><text x="156" y="669">记忆</text>
    <rect x="216" y="659" width="12" height="12" rx="3" fill="#e0a021"/><text x="232" y="669">Skills</text>
    <rect x="302" y="659" width="12" height="12" rx="3" fill="#12b0c6"/><text x="318" y="669">工具</text>
    <rect x="378" y="659" width="12" height="12" rx="3" fill="#9d8579"/><text x="394" y="669">其他</text>
    <rect x="454" y="659" width="12" height="12" rx="3" fill="#f0921f"/><text x="470" y="669">沙箱</text>
    <rect x="530" y="659" width="12" height="12" rx="3" fill="#eb5545"/><text x="546" y="669">驱动</text>
    <rect x="606" y="659" width="12" height="12" rx="3" fill="#a855f7"/><text x="622" y="669">运行时</text>
  </g>
  <text x="690" y="669" font-size="9" fill="currentColor" fill-opacity="0.5">颜色按关注点划分 OS</text>
</svg>

---

## 基座：AgentScope

QwenPaw 构建在 **AgentScope 2.0** 之上，把它当作一个库来用。AgentScope 的运行时跑在进程内，因此不用再单独起一个运行时服务。QwenPaw 复用了以下几样：

- QwenPaw 在其之上构建的**推理-行动（ReAct）智能体循环**；
- 用于流式输出、以及保存和恢复会话的**消息与可序列化状态约定**；
- 每个 QwenPaw 工具都接入的**工具调用层**；
- QwenPaw 用自有工具扩展的**工作目录抽象**；
- 智能体一边思考、一边调用工具时发出的**流式事件模型**。

本页其余部分（工作区边界、请求生命周期、资源维度、信任主干）都是 QwenPaw 在这些基础原语之上的自有设计。

---

## 工作区——智能体专属的边界

**工作区**是隔离的基本单位。一次安装可以跑多个智能体，每个智能体正好对应一个工作区：一个磁盘目录，加上一组在它之上运行的实时服务。某个智能体第一次被用到时，工作区才懒加载；服务停止时则干净退出。除非一个智能体主动给另一个发消息，否则谁也看不到对方的文件、记忆和对话。

每个工作区打包两样东西：智能体运行时要用的**服务**（会话与历史、记忆、连接器、频道、聊天、定时任务），以及一组**扩展注册表**，用来登记工具、钩子、命令和提示词片段。第三方**插件**往这些注册表里添东西——模型提供商、工具、钩子、魔法命令、提示词区块、HTTP 路由，还有智能体中间件——这样不用改动核心就能扩展平台。参见[插件](./plugins)。

<svg viewBox="0 0 860 420" width="100%" role="img" aria-label="工作区剖析：注册表持有多个相互隔离、各智能体专属的工作区；每个工作区都打包了服务以及一个磁盘目录。" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpWsArrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- Registry -->
  <rect x="20" y="40" width="220" height="320" rx="10" fill="currentColor" fill-opacity="0.03" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="130" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#ff9d4d">智能体注册表</text>
  <text x="130" y="86" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">为每个智能体懒加载一个工作区</text>
  <g font-size="12.5" fill="currentColor">
    <rect x="44" y="104" width="172" height="40" rx="7" fill="#ff9d4d" fill-opacity="0.14" stroke="#ff9d4d" stroke-opacity="0.55"/><text x="130" y="129" text-anchor="middle" font-weight="600">智能体 A（活跃）</text>
    <rect x="44" y="156" width="172" height="40" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="130" y="181" text-anchor="middle">智能体 B</text>
    <rect x="44" y="208" width="172" height="40" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="130" y="233" text-anchor="middle">智能体 C</text>
  </g>
  <text x="130" y="300" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6" font-style="italic">工作区之间不共享状态，</text>
  <text x="130" y="316" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6" font-style="italic">除非某个智能体</text>
  <text x="130" y="332" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6" font-style="italic">显式地向另一个发送消息。</text>
  <line x1="240" y1="124" x2="300" y2="124" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpWsArrow)"/>
  <!-- Expanded workspace -->
  <rect x="304" y="40" width="536" height="320" rx="10" fill="currentColor" fill-opacity="0.03" stroke="#ff9d4d" stroke-opacity="0.5"/>
  <text x="324" y="66" font-size="12.5" font-weight="700" fill="#ff9d4d">工作区（智能体 A）</text>
  <!-- Services column -->
  <text x="324" y="92" font-size="11" letter-spacing="1" font-weight="700" fill="currentColor" fill-opacity="0.75">服务</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="324" y="102" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="119" text-anchor="middle">会话与历史</text>
    <rect x="324" y="134" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="151" text-anchor="middle">记忆</text>
    <rect x="324" y="166" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="183" text-anchor="middle">连接器（MCP）</text>
    <rect x="324" y="198" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="215" text-anchor="middle">频道</text>
    <rect x="324" y="230" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="247" text-anchor="middle">对话 · 调度器</text>
    <rect x="324" y="262" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="279" text-anchor="middle">工具 · 钩子 · 命令 · 提示词</text>
  </g>
  <!-- Disk column -->
  <text x="588" y="92" font-size="11" letter-spacing="1" font-weight="700" fill="currentColor" fill-opacity="0.75">磁盘上 · 工作区文件夹</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="588" y="102" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="119" text-anchor="middle">配置（纯 JSON）</text>
    <rect x="588" y="134" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="151" text-anchor="middle">MEMORY.md · memory/*.md</text>
    <rect x="588" y="166" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="183" text-anchor="middle">digest · Skills</text>
    <rect x="588" y="198" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="215" text-anchor="middle">连接器 + 凭据</text>
    <rect x="588" y="230" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="247" text-anchor="middle">持久化对话历史</text>
    <rect x="588" y="262" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="279" text-anchor="middle">共享技能池</text>
  </g>
  <text x="572" y="324" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">文件保持人类可读且可移植——整个工作区都可以备份与恢复。</text>
</svg>

磁盘上的布局是透明的：配置是纯 JSON，记忆是 Markdown，Skills 就是文件夹。哪怕 QwenPaw 没在运行，你也能读、能改其中任何一部分，还能纳入版本控制。[备份与恢复](./backup)可以把一个工作区打包成带签名的归档，方便在不同机器之间搬。

---

## 运行时——请求的生命周期

运行时把每个进来的请求变成一串 UI 事件。它是一条带阶段、阶段之间留有钩子点的固定流程，各项功能因此能挂上自己的行为，而不用动核心循环。请求被分到目标智能体的工作区，在那里为这次请求组装好智能体、运行，再把输出流式发回。

<svg viewBox="0 0 820 600" width="100%" role="img" aria-label="请求生命周期：钩子阶段与固定步骤交错，用于命令分发、智能体组装和执行，而出错与清理处理器始终运行。" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpFlowArrow" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- legend -->
  <rect x="556" y="20" width="20" height="14" rx="3" fill="#ff9d4d" fill-opacity="0.14" stroke="#ff9d4d" stroke-opacity="0.55"/>
  <text x="582" y="31" font-size="10.5" fill="currentColor" fill-opacity="0.7">钩子阶段</text>
  <rect x="664" y="20" width="20" height="14" rx="3" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/>
  <text x="690" y="31" font-size="10.5" fill="currentColor" fill-opacity="0.7">固定步骤</text>
  <!-- short flow arrows, one in each gap between consecutive boxes -->
  <g stroke="#ff9d4d" stroke-width="1.4">
    <line x1="250" y1="75" x2="250" y2="91" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="121" x2="250" y2="137" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="167" x2="250" y2="183" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="213" x2="250" y2="229" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="259" x2="250" y2="275" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="305" x2="250" y2="321" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="351" x2="250" y2="367" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="397" x2="250" y2="413" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="459" x2="250" y2="475" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="505" x2="250" y2="521" marker-end="url(#qpFlowArrow)"/>
  </g>
  <!-- rows -->
  <g font-size="12">
    <!-- input -->
    <rect x="90" y="44" width="320" height="30" rx="15" fill="#ff9d4d" fill-opacity="0.18" stroke="#ff9d4d" stroke-opacity="0.6"/><text x="250" y="63" text-anchor="middle" font-weight="600" fill="currentColor">传入请求（来自频道或定时任务）</text>
    <rect x="90" y="92" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="110" text-anchor="middle" fill="currentColor">分发前</text>
    <rect x="90" y="138" width="320" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="250" y="156" text-anchor="middle" fill="currentColor">命令分发</text>
    <text x="424" y="156" font-size="10.5" fill="currentColor" fill-opacity="0.6">/命令 → 直接回复并跳过智能体</text>
    <rect x="90" y="184" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="202" text-anchor="middle" fill="currentColor">分发后</text>
    <rect x="90" y="230" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="248" text-anchor="middle" fill="currentColor">构建前</text>
    <text x="424" y="248" font-size="10.5" fill="currentColor" fill-opacity="0.6">加载会话 · 媒体 · 请求上下文</text>
    <rect x="90" y="276" width="320" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="250" y="294" text-anchor="middle" fill="currentColor" font-weight="600">组装智能体</text>
    <text x="424" y="290" font-size="10.5" fill="currentColor" fill-opacity="0.6">模型 · 工具 · 提示词</text>
    <text x="424" y="303" font-size="10.5" fill="currentColor" fill-opacity="0.6">记忆 · 上下文策略 · 策略</text>
    <rect x="90" y="322" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="340" text-anchor="middle" fill="currentColor">构建后</text>
    <text x="424" y="340" font-size="10.5" fill="currentColor" fill-opacity="0.6">注入当前模式上下文</text>
    <rect x="90" y="368" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="386" text-anchor="middle" fill="currentColor">执行前</text>
    <text x="424" y="386" font-size="10.5" fill="currentColor" fill-opacity="0.6">首次运行初始化 · 提示词刷新</text>
    <rect x="90" y="414" width="320" height="44" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="250" y="432" text-anchor="middle" fill="currentColor" font-weight="600">运行智能体</text><text x="250" y="448" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.65">ReAct 循环，受最大迭代次数限制约束</text>
    <rect x="90" y="476" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="494" text-anchor="middle" fill="currentColor">响应后</text>
    <text x="424" y="494" font-size="10.5" fill="currentColor" fill-opacity="0.6">保存会话 · 定时任务回写</text>
    <rect x="90" y="522" width="320" height="30" rx="15" fill="#ff9d4d" fill-opacity="0.18" stroke="#ff9d4d" stroke-opacity="0.6"/><text x="250" y="541" text-anchor="middle" font-weight="600" fill="currentColor">将响应流式输出</text>
  </g>
  <!-- error / cleanup bracket -->
  <path d="M70,92 q-14,0 -14,14 v384 q0,14 14,14" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.5"/>
  <text x="30" y="298" font-size="11" fill="currentColor" fill-opacity="0.7" transform="rotate(-90 30 298)" text-anchor="middle">出错时 · 清理（始终执行）</text>
  <text x="250" y="576" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">清理始终执行：取消回复、关闭连接器、重置请求状态。</text>
</svg>

### 钩子、模式与组装智能体

**钩子**是挂在生命周期某个阶段上的小单元。它可以放请求继续，也可以直接回一条消息把请求截下来，或者干脆跳过智能体。内置钩子负责会话的加载和保存、首次运行的初始化、技能环境准备、媒体处理，以及可选的链路追踪。

**模式**把相关的命令、工具、钩子和提示词片段收拢到一个开关后面。目前有两种：

- **Coding 模式**加上了懂项目的工具（代码搜索、内联 diff 编辑）和一段 Coding 系统提示，作用范围限定在某个项目目录里。参见 [Coding 模式](./coding-mode)。
- **Mission 模式**用两阶段循环来跑长任务：智能体先写一份计划，再用实现类工具反复迭代，直到每个检查点都通过。

**组装智能体**每个请求只做一次：把智能体配置、模型、工具、系统提示、记忆和上下文策略凑齐，并给每个工具都包上一层，让治理层始终看得到。每次都重新组装，资源调配和策略就都留在智能体之外。

---

## 智能体及其工具

QwenPaw 的智能体跑的是一个 **ReAct（先推理后行动）循环**，迭代次数设了上限；它要用的依赖都由组装这一步现成给到。

工具自带**激活条件**——要哪些模式、Skills、功能或沙箱资源——所以每个请求只看得到自己能用的那些工具。内置工具包括文件读写、代码和文本搜索、Shell 执行、浏览器控制和截图、看图看视频，以及多智能体协作。

多个智能体有两种协作方式（参见[多智能体](./multi-agent)）：

- **对内**——同一套安装里，一个 QwenPaw 智能体可以给另一个发消息，或者新拉起一个智能体。
- **对外**——通过 **ACP**（Agent Client Protocol），QwenPaw 可以拉起一个外部智能体进程，把它干的活当作工具结果流式发回，遇到权限请求还能交回宿主来审批。参见 [ACP 集成](./acp-integration)。

---

## 记忆与上下文

QwenPaw 把两个容易混为一谈的概念分开：**记忆**（智能体跨对话记住的东西）和**上下文**（当下能塞进模型窗口的内容）。

<svg viewBox="0 0 860 372" width="100%" role="img" aria-label="记忆是构建在透明 Markdown 文件之上的可插拔后端；上下文管理要么采用总结式压缩，要么采用配备持久化存储和 recall 工具的 Scroll 策略。" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpMemArrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- MEMORY side -->
  <rect x="20" y="24" width="400" height="324" rx="10" fill="currentColor" fill-opacity="0.03" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="40" y="50" font-size="12.5" font-weight="700" fill="#ff9d4d">记忆 · 跨对话</text>
  <rect x="40" y="64" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="83" text-anchor="middle" font-size="12" fill="currentColor">记忆集成（检索 · 写入）</text>
  <line x1="220" y1="94" x2="220" y2="108" stroke="#ff9d4d" stroke-width="1.4" marker-end="url(#qpMemArrow)"/>
  <rect x="40" y="110" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="129" text-anchor="middle" font-size="12" fill="currentColor">可插拔记忆后端</text>
  <rect x="40" y="152" width="174" height="30" rx="7" fill="#ff9d4d" fill-opacity="0.12" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="127" y="171" text-anchor="middle" font-size="11.5" fill="currentColor">ReMe（默认）</text>
  <rect x="226" y="152" width="174" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="313" y="171" text-anchor="middle" font-size="11.5" fill="currentColor">纯 Markdown</text>
  <text x="40" y="208" font-size="11" letter-spacing="1" font-weight="700" fill="currentColor" fill-opacity="0.75">工作区中的透明文件</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="40" y="218" width="360" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="235" text-anchor="middle">MEMORY.md — 长期笔记</text>
    <rect x="40" y="250" width="360" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="267" text-anchor="middle">memory/YYYY-MM-DD.md — 每日笔记</text>
    <rect x="40" y="282" width="360" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="299" text-anchor="middle">整合后的 digest</text>
  </g>
  <text x="220" y="330" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">检索、写入和整合都作为后台工作运行。</text>
  <!-- CONTEXT side -->
  <rect x="440" y="24" width="400" height="324" rx="10" fill="currentColor" fill-opacity="0.03" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="460" y="50" font-size="12.5" font-weight="700" fill="#ff9d4d">上下文 · 实时窗口</text>
  <rect x="460" y="64" width="360" height="44" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="640" y="82" text-anchor="middle" font-size="12" fill="currentColor" font-weight="600">总结式压缩（默认）</text><text x="640" y="98" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.65">窗口一满就总结较早的轮次</text>
  <text x="460" y="132" font-size="11" letter-spacing="1" font-weight="700" fill="currentColor" fill-opacity="0.75">或 — SCROLL 策略（可选启用）</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="460" y="142" width="360" height="30" rx="7" fill="#ff9d4d" fill-opacity="0.12" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="640" y="161" text-anchor="middle">Scroll 策略</text>
    <rect x="460" y="180" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="640" y="199" text-anchor="middle">持久化存储 — 保留每一轮次</text>
    <rect x="460" y="218" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="640" y="237" text-anchor="middle">已滚出窗口的轮次索引</text>
    <rect x="460" y="256" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="640" y="275" text-anchor="middle">recall 工具 — 重放任意较早的片段</text>
  </g>
  <text x="640" y="318" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">不丢任何内容：滚出窗口的轮次</text>
  <text x="640" y="332" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">随时都能回放，而不是只剩摘要。</text>
</svg>

**记忆**是一个可插拔的后端。默认那套基于 [ReMe](https://github.com/agentscope-ai/ReMe) 记忆库，在工作区上用后台任务来做取回、写入和整合（“做梦”）；另一套更简单的则直接读写同一批文件。不管哪套，底层都是**人能读的 Markdown**——`MEMORY.md` 放长期笔记，再配上按日期分的每日文件——所以记忆你随时都能打开、查看、修改。参见[记忆](./memory)和[记忆演化与主动交互](./memory-evolving-and-proactive)。

**上下文**管理同样可插拔。默认情况下，窗口一满，QwenPaw 就把较早的对话轮次总结掉。可选的 **Scroll 策略**换了个思路：它把每一轮都存进持久化存储，给已经滚出窗口的内容留一份精简索引，再给智能体一个工具，按需就能回放早先的任意一段对话——长对话因此能完整找回。参见[上下文](./context)。

---

## 技能——能力层

QwenPaw 靠 Skills 来长本事。一项**技能（Skill）就是一个文件夹**：放着说明和元数据，再带上一组可选的可执行脚本。内置 Skills 提供多语言变体。

QwenPaw 会按当前的工作区和频道，算出哪些 Skills 处于启用状态，来源是工作区自己的一份集合，加上一个共享池。每个启用的技能都会变成一个工具，供智能体调用（也可以用 `/skill-name` 命令调用）。Skills 可以从 GitHub、ModelScope 等外部来源安装，统一在[技能市场](./skills)里呈现。

Skills 可能带可执行代码，所以安装时会先过一遍**技能扫描器**（见下文的信任主干），之后才能用。更多内容参见 [Skills](./skills)。

---

## 驱动与频道——和外部世界打交道

QwenPaw 把**频道**（人怎么联系到智能体）和**驱动**（智能体怎么访问外部系统）分开。

**频道**是各消息平台的入口。每个频道负责在所在平台的原生消息格式和一套统一的请求/响应格式之间来回转换，还自带访问控制、防抖和流式处理。内置频道有钉钉、飞书、企业微信、微信、Discord、Slack、Telegram、QQ 等，再加上 Web 控制台。参见[频道](./channels)。

**驱动**是一个与协议无关的**连接器层**。一个连接器声明自己的端点、凭据引用和策略；系统从加密存储里取出凭据，再用策略加一道审批，替每次调用把关。目前落地的协议是 **MCP**（模型上下文协议，Model Context Protocol），外部工具服务器靠它变成智能体能调的工具。这层抽象比 MCP 更宽，所以其他连接器协议也能接到同一套凭据和策略模型下面。参见 [MCP 与内置工具](./mcp)。

---

## 模型——认知引擎

模型是智能体用来思考的引擎。它被放在一个稳定的接口后面，所以换模型不会牵动系统的其他部分。

- **云端提供商**——OpenAI、Anthropic、Google Gemini、DashScope（Qwen）和 OpenRouter，需要登录的提供商也配了登录流程。
- **本地运行时**——Ollama 和 LM Studio，还有通过 **llama.cpp** 完全在本机跑的模型，不用 API 密钥、不用联网。
- 每个智能体各自指定用哪个模型；能力探测会记下模型支不支持图像或视频，遇到不支持的输入就尽早挡掉。
- **个性化**功能可以为单个用户微调一个模型，再像别的提供商一样把它提供出来。

配置方法参见[模型](./models)。

---

## 信任主干——安全与治理

每一次工具调用、每一个对外动作，在碰到你的机器或数据之前，都要先过一条分层的信任主干。

<svg viewBox="0 0 860 384" width="100%" role="img" aria-label="每次工具调用都先过一道策略检查，由治理策略判定为放行、拒绝、询问或沙箱；放行的调用再经过工具守卫，并在宿主原生沙箱里运行。" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpSecArrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- agent wants to call a tool -->
  <rect x="40" y="30" width="200" height="40" rx="8" fill="#ff9d4d" fill-opacity="0.16" stroke="#ff9d4d" stroke-opacity="0.6"/><text x="140" y="55" text-anchor="middle" font-size="12.5" font-weight="600" fill="currentColor">智能体调用工具</text>
  <line x1="240" y1="50" x2="296" y2="50" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSecArrow)"/>
  <rect x="300" y="30" width="220" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="410" y="55" text-anchor="middle" font-size="12" fill="currentColor">策略检查（包裹每一次调用）</text>
  <line x1="410" y1="70" x2="410" y2="92" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSecArrow)"/>
  <!-- governance engine -->
  <rect x="270" y="96" width="280" height="58" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="410" y="120" text-anchor="middle" font-size="12.5" font-weight="600" fill="currentColor">治理策略</text><text x="410" y="138" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.65">内置规则 + 你的规则 → 一个决策</text>
  <!-- four outcomes -->
  <g font-size="11.5" fill="currentColor">
    <rect x="40" y="186" width="170" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="125" y="205" text-anchor="middle" font-weight="600">拒绝</text><text x="125" y="219" text-anchor="middle" font-size="10" fill-opacity="0.65">拦下，返回原因</text>
    <rect x="226" y="186" width="170" height="40" rx="8" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="311" y="205" text-anchor="middle" font-weight="600">询问</text><text x="311" y="219" text-anchor="middle" font-size="10" fill-opacity="0.65">审批 → 由你决定</text>
    <rect x="412" y="186" width="170" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="497" y="205" text-anchor="middle" font-weight="600">沙箱</text><text x="497" y="219" text-anchor="middle" font-size="10" fill-opacity="0.65">强制进入隔离</text>
    <rect x="598" y="186" width="170" height="40" rx="8" fill="#ff9d4d" fill-opacity="0.16" stroke="#ff9d4d" stroke-opacity="0.6"/><text x="683" y="205" text-anchor="middle" font-weight="600">放行</text><text x="683" y="219" text-anchor="middle" font-size="10" fill-opacity="0.65">继续执行</text>
  </g>
  <g stroke="#ff9d4d" stroke-width="1.3">
    <line x1="330" y1="154" x2="160" y2="184" marker-end="url(#qpSecArrow)"/>
    <line x1="380" y1="154" x2="320" y2="184" marker-end="url(#qpSecArrow)"/>
    <line x1="440" y1="154" x2="500" y2="184" marker-end="url(#qpSecArrow)"/>
    <line x1="490" y1="154" x2="670" y2="184" marker-end="url(#qpSecArrow)"/>
  </g>
  <!-- approval note -->
  <text x="311" y="240" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.55">批准 → 按放行继续执行</text>
  <!-- tool guard + sandbox -->
  <line x1="683" y1="226" x2="683" y2="252" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSecArrow)"/>
  <rect x="560" y="256" width="246" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="683" y="275" text-anchor="middle" font-size="12" fill="currentColor">工具守卫 — 内容筛查</text><text x="683" y="289" text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.65">路径 · 模式 · Shell 规避检查</text>
  <line x1="683" y1="296" x2="683" y2="320" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSecArrow)"/>
  <rect x="560" y="324" width="246" height="44" rx="8" fill="#ff9d4d" fill-opacity="0.12" stroke="#ff9d4d" stroke-opacity="0.55"/><text x="683" y="343" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">在原生 OS 沙箱中执行</text><text x="683" y="358" text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.7">seatbelt · bubblewrap · landlock · appcontainer · 无</text>
  <!-- side: skill scanner + secrets -->
  <rect x="40" y="256" width="280" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="180" y="275" text-anchor="middle" font-size="11.5" fill="currentColor">技能扫描器 — 把关技能安装</text><text x="180" y="289" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">代码运行前先静态分析</text>
  <rect x="40" y="324" width="280" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="180" y="343" text-anchor="middle" font-size="11.5" fill="currentColor">加密凭据存储</text><text x="180" y="357" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">静态存储的提供商密钥和连接器密钥</text>
</svg>

各层如下：

- **治理策略**——每次工具调用都拿内置规则和你自己的规则比对，给出放行、拒绝、询问或沙箱之一。工具在智能体调用之前就已经包好，所以这道检查绕不过去。给出*询问*时会弹出一个审批，你可以在控制台或自己的 IM 频道里回应。
- **工具守卫**——对已放行的调用再查一遍内容，盯着路径穿越、敏感文件、危险写法和 Shell 绕过手法。
- **沙箱**——把有风险的执行放进宿主自带的隔离里跑：macOS 用 seatbelt，Linux 用 bubblewrap（首选）或 landlock，Windows 用 AppContainer，也可以不隔离。每次工具调用都新建一个沙箱，带上声明好的挂载点和禁止访问的路径。
- **技能扫描器**——技能安装前先对它的文件做一遍静态分析。
- **加密密钥**——提供商密钥和连接器凭据都加密存放。

完整的策略模型和配置方法参见[安全](./security)。

---

## 入口与运维

QwenPaw 是一个常驻服务，装在你自己的机器上、或你说了算的服务器上都行，并提供好几个入口通向同一个运行时。不管走哪个入口，底层的智能体、工作区、记忆和策略都是同一套。

<svg viewBox="0 0 860 290" width="100%" role="img" aria-label="同一个 QwenPaw 运行时由多个入口（控制台、桌面应用、终端 UI、CLI、聊天频道）接入，周围是各项运维能力（定时任务、收件箱、备份）。" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpSurfArrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- SURFACES column -->
  <text x="24" y="34" font-size="11" letter-spacing="1.5" font-weight="700" fill="#ff9d4d">入口 · 你从哪里进来</text>
  <g font-size="12" fill="currentColor">
    <rect x="24" y="46" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="66" text-anchor="middle">控制台 — Web 枢纽</text>
    <rect x="24" y="86" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="106" text-anchor="middle">桌面应用（Beta）</text>
    <rect x="24" y="126" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="146" text-anchor="middle">终端 UI</text>
    <rect x="24" y="166" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="186" text-anchor="middle">CLI + doctor</text>
    <rect x="24" y="206" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="226" text-anchor="middle">聊天频道</text>
  </g>
  <line x1="282" y1="150" x2="322" y2="150" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSurfArrow)"/>
  <text x="302" y="142" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">访问</text>
  <!-- center -->
  <rect x="326" y="100" width="208" height="100" rx="10" fill="#ff9d4d" fill-opacity="0.12" stroke="#ff9d4d" stroke-opacity="0.55"/>
  <text x="430" y="140" text-anchor="middle" font-size="13" font-weight="700" fill="currentColor">QwenPaw 服务</text>
  <text x="430" y="159" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.7">单一运行时 ·</text>
  <text x="430" y="173" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.7">智能体专属工作区</text>
  <line x1="538" y1="150" x2="578" y2="150" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSurfArrow)"/>
  <text x="558" y="142" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">运行</text>
  <!-- OPERATIONS column -->
  <text x="584" y="34" font-size="11" letter-spacing="1.5" font-weight="700" fill="#ff9d4d">运维 · 维持其运行的部分</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="584" y="100" width="252" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="710" y="118" text-anchor="middle">定时任务与心跳</text>
    <rect x="584" y="136" width="252" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="710" y="154" text-anchor="middle">主动收件箱</text>
    <rect x="584" y="172" width="252" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="710" y="190" text-anchor="middle">备份与恢复</text>
  </g>
</svg>

### 入口

- **控制台**——主要的 Web 界面，也是管理中枢：能实时流式聊天，还能配置智能体、频道、模型、Skills 和技能市场、连接器、安全与审批、备份、Token 用量、定时任务，以及主动消息收件箱。参见[控制台](./console)。
- **桌面应用**——把控制台打包成的跨平台桌面应用（Beta），内置运行时、支持自动更新，不用开终端、不用手动配置就能跑起来。参见[桌面应用](./desktop)。
- **终端 UI**——一个全屏的终端界面，在 shell 里就能聊天和管理智能体，也支持按项目划分的编码会话；直接敲 `qwenpaw` 就能打开。参见[终端 UI](./tui)。
- **CLI**——能写进脚本的 `qwenpaw` 命令，用来管理智能体、提供商、频道、Skills、连接器和定时任务，还有 `qwenpaw doctor` 做一次性诊断和带引导的修复。参见 [CLI](./cli)。
- **聊天频道**——每个消息平台本身就是一个入口：钉钉、飞书、Slack、Discord 等等，都能直接找到智能体。参见[频道](./channels)。

### 运维

下面这些能力，让 QwenPaw 可以无人值守地长期跑下去：

- **定时任务与心跳**——按时间表跑智能体，把结果发到任意频道（比如一份晨间摘要、一次定期签到）。定时跑用的是隔离的记忆上下文，所以自动化不会弄乱你平时对话的历史。参见[定时任务](./cron)和[心跳](./heartbeat)。
- **主动收件箱**——智能体可以主动找你（提醒、摘要、复盘），这些消息会汇到控制台的一个收件箱里，供你查看和转发。参见[记忆演化与主动交互](./memory-evolving-and-proactive)。
- **备份与恢复**——一个完整的工作区（配置、记忆、Skills，以及可选的密钥）可以导出成一份带签名的归档，整体恢复或挑着恢复都行。参见[备份与恢复](./backup)。

---

本页讲的是 QwenPaw 现在的样子。接下来要做什么，参见[路线图](./roadmap)。
