# QwenPaw × NocoBase Console 登录设计

- **日期**: 2026-07-08
- **分支**: `feat/nocobase-auth`
- **状态**: 待评审 → 转实现计划
- **作者**: JackPan(与 Claude 协作 brainstorming)
- **关联**: 与 [`2026-07-01-nocobase-sso-design.md`](./2026-07-01-nocobase-sso-design.md) **互补**,见 §1.2

## 1. 背景与问题

### 1.1 现状

`feat/nocobase-auth` 分支已实现两块:

1. **ACL 同步 + 频道门禁**:`nocobase_auth` 插件把 NocoBase 用户/角色同步到本地 `PermissionStore`,经 `BaseChannel._external_acl_checkers` 对 console 频道做 fail-closed 准入。
2. **X-NocoBase-Token 身份解析器**(旧 spec 2026-07-01):核心 `app/auth.py` 开 `register_external_identity_resolver` 扩展点,插件读 `X-NocoBase-Token` 请求头 → `auth:check` 校验 → 写 `request.state.user`。服务于"**嵌入页**逐请求带 token"的场景。

本会话另外修复了门禁静默失效的部署问题(三开关:`QWENPAW_AUTH_ENABLED=true`、部署带 resolver 的新版插件、`allow_no_auth_hosts=[]`),使上述机制真正生效。

### 1.2 缺口:独立 console UI 无法用 NocoBase 账号登录

实测确认:QwenPaw 独立 console(`:8088`)的登录页(`console/src/pages/Login/index.tsx`)**只走原生本地单用户登录**(`/api/auth/login` → 校验本地 `auth.json`)。用 NocoBase 账号(如 `admin@nocobase.com`)在登录框登录必然 401。

**旧 spec 的适用边界**:旧 spec 明确把"浏览器重定向 SSO / 登录页 / 签发 QwenPaw token"列为**非目标**——因为它服务的是"嵌入页始终带 NocoBase token"的场景,不需要登录页。

**本 spec 的场景不同**:用户要在 **QwenPaw 自己的 console 登录页**用 NocoBase 账号密码登录。这里没有"一直带 token 的嵌入页";用户在登录框输入凭据。因此需要一条"账号密码 → 验证 → 建立 QwenPaw 会话"的登录路径。

**两者互补,不冲突**:

| 用例 | 身份来源 | 机制 | 归属 spec |
|---|---|---|---|
| 嵌入页调 chat API | 每请求 `X-NocoBase-Token` | identity resolver 逐请求 `auth:check` | 2026-07-01 |
| 独立 console UI 登录 | 登录页输入账号密码 | 后端代理 signin → 签发 QwenPaw 会话 token | **本 spec** |

## 2. 目标与非目标

**目标**
- console 登录页支持"用 NocoBase 账号登录":输入 NocoBase 账号密码 → 后端验证 → 建立 QwenPaw 会话 → 进入 console。
- 登录成功的会话身份 = NocoBase 用户身份(email),下游频道 ACL 零改动按角色准入。
- NocoBase 登录与现有原生本地登录**并存**(原生登录本次不改)。

**非目标**
- 不做浏览器重定向 OAuth2/OIDC。
- 不改 ACL 门禁判定逻辑(`permission_store`、`channel_gate`)。
- 不改动/移除原生本地登录(本次只新增 NocoBase 登录路径)。
- 不替换旧 spec 的 identity resolver(它服务嵌入页场景,继续保留)。

## 3. 选定方案(方案 A):后端代理 signin → 签发 QwenPaw 会话 token

前端登录页新增 NocoBase 登录入口 → 账号密码 POST 到**插件的公开登录接口** → 后端服务端调 NocoBase `auth:signIn` 验证凭据 → 取 `sender_id`(email)→ 校验 console ACL → 用 `create_token(sender_id)` 签发**标准 QwenPaw 会话 token** → 前端存入 localStorage,之后完全复用现有 `Authorization: Bearer` / `AuthGuard` / `/auth/verify` 机制。

**选它的理由**:前端改动最小、复用全部现有会话机制、无 CORS(NocoBase 只在后端被访问)、无每请求往返。

**与旧 spec"方案 B(token 交换)否决"的关系**:旧 spec 否决 token 交换,是因为**嵌入页**场景下页面本就一直持有 NocoBase token,再换一个 QwenPaw token 属多管一个凭据、且有吊销延迟。**但本场景是 console UI 登录**,没有嵌入页、没有常驻 NocoBase token——用户就是要建立一个到 console 的登录会话,签发 QwenPaw 会话 token 正是最自然的模型。因此在**本场景**它是正解,与旧 spec 的否决不矛盾(不同场景、不同结论)。

**接受的取舍(会话与 NocoBase 解耦)**:NocoBase token 只在登录这一刻被后端用一次(验证凭据),之后会话是独立的 QwenPaw token。若 NocoBase 之后禁用该用户,QwenPaw 会话 token 在到期前仍有效(吊销延迟)。缓解:
- 真正的准入控制(谁能用 console)由**频道门禁每条消息**按同步的 `PermissionStore` 强制校验,禁用会随下次同步在频道层生效。
- QwenPaw token 有效期可短(默认 7 天,可通过 `expires_in` 调短)。

**被否方案**:
- **B(返回 NocoBase token,前端每请求带 `X-NocoBase-Token`)**:复用 resolver 更"新鲜",但前端要注入自定义头、并把 Bearer 中心的 `AuthGuard`/`/auth/verify` 改造成认 NocoBase 会话,裸 fetch 绕过注入点也要单独处理——前端改动明显更大。
- **C(前端直连 NocoBase signin)**:需 NocoBase 开 CORS、前端硬依赖 NocoBase 地址(本是后端配置)、把端点暴露给浏览器。不采纳。

## 4. 架构与数据流

**已验证的外部命门**:
- `create_token`/`verify_token` 只验 HMAC 签名 + 有效期 + 吊销、**不校验是否注册用户**(`app/auth.py`),故可为任意 NocoBase 身份签发可通过现有守卫的 token(本会话实测)。
- NocoBase `POST /api/auth:signIn`,头 `X-Authenticator: basic`,body `{account, password}` → `200 {data:{user, token}}`;凭据错误非 200(本会话对 `localhost:13000` 实测 `admin@nocobase.com/admin123` 成功拿到 JWT)。

```
console 登录页(核心前端,新增 NocoBase 入口)
  用户选"用 NocoBase 登录" → 输入 account / password
      │  POST /api/nocobase-auth/login  {account, password, expires_in?}
      ▼
① 插件登录接口(公开路径,未鉴权可达)
   a. rate_limiter 限流(复用 app/rate_limiter,防爆破;is_user_locked / is_ip_locked / is_ip_rate_limited)
   b. 校验插件 enabled 且 is_auth_enabled();否则 409
   c. NocoBaseClient.sign_in(account, password) → auth:signIn → {user, nocobase_token}
        - 凭据错误 → 401
        - NocoBase 不可达 → 502/503
   d. sender_id = extract_sender_id(user, config.user_id_field)   # 默认 email
   e. ACL:复用 channel_gate 的 checker("console", sender_id, {}) → "deny" 则 403
   f. token = create_token(sender_id, expires_in) → 丢弃 nocobase_token
   g. rate_limiter.record_login_attempt(ip, account, success=True)
      │  200 {token, username: sender_id}
      ▼
② 前端 setAuthToken(token) → localStorage(qwenpaw_auth_token) → navigate(redirect)
      ▼
③ 之后所有请求照常带 Authorization: Bearer;AuthGuard/verify/console 门禁**零改动**
   - request.state.user = sender_id(email) → acl_sender_id → 频道门禁每消息按角色准入
```

**关键性质**
- 会话身份 = NocoBase email = ACL sender_id = console session key,天然多用户、会话隔离。
- 现有 Bearer 全链路零改动;仅新增一条建立会话的入口。
- 频道门禁仍是最终准入闸门(每消息校验)。

## 5. 组件与接口

改动 5 处:1 处核心开通用扩展点,2 处插件后端,2 处核心前端。互相通过清晰接口解耦。

### 5.1 核心 `app/auth.py` —— 新增通用"公开路径注册"扩展点

问题:公开白名单 `_PUBLIC_PATHS` 是核心硬编码的 frozenset;插件挂在 `/api/nocobase-auth/*` 的路由默认受保护(未鉴权 401),登录接口无法在登录前被访问。

改法(仿 `register_external_identity_resolver` 的注册表模式,核心不硬编插件路径):

```python
_dynamic_public_paths: set[str] = set()

def register_public_path(path: str) -> None:
    """Allow a plugin to declare an unauthenticated-reachable path."""
    _dynamic_public_paths.add(path)

def unregister_public_path(path: str) -> None:
    _dynamic_public_paths.discard(path)
```

`_should_skip_auth` 的公开判定处补一项:

```python
if path in _PUBLIC_PATHS or path in _dynamic_public_paths or any(
    path.startswith(p) for p in _PUBLIC_PREFIXES
):
    return True
```

安全说明:该能力仅供**受信插件**(admin 安装)在启动时声明自身少量公开端点;登录接口自身仍做限流 + 凭据校验,不因公开而免检。

### 5.2 插件 `NocoBaseClient.sign_in(account, password)`(新增)

```python
async def sign_in(self, account, password) -> dict:
    # POST /api/auth:signIn, header X-Authenticator: <config.authenticator or "basic">
    # body {"account": account, "password": password}
    # 200 → 返回 data(含 user, token);401/非 200 → 抛 NocoBaseAuthError；网络错误 → NocoBaseRequestError
```

- 用**匿名请求**(不带 admin api_token)——signin 是无凭据换凭据。可复用 `_get_client()` 之外的一次性 client(仿 `verify_user_token`),`trust_env=False`、同 base_url。
- `authenticator` 名默认 `"basic"`(本实例已验证),作为可选配置项 `NocoBaseAuthConfig.authenticator`,应对不同 NocoBase 认证器配置。

### 5.3 插件登录路由(`routers.py` 新增 `POST /login`)

编排 §4 的 ①a–g。依赖(插件已耦合 `qwenpaw.app.*`):
- `qwenpaw.app.rate_limiter.rate_limiter` —— 与原生登录同一套限流。
- `qwenpaw.app.auth.create_token` / `is_auth_enabled` —— 签发 token / 总开关判定。
- `channel_gate.build_checker` 产出的 checker —— 登录时 ACL 复用,保证与频道门禁**同一判定逻辑**(避免"能登进却不能聊"或规则漂移)。
- `sync_engine`(store + config)。

请求/响应契约:

```
POST /api/nocobase-auth/login
  body: { "account": str, "password": str, "expires_in"?: int }
  200:  { "token": str, "username": str }      # username = sender_id(email)
  401:  { "detail": "NocoBase 账号或密码错误" }
  403:  { "detail": "该 NocoBase 账号无权访问 console" }
  409:  { "detail": "NocoBase 登录未启用" }     # 插件未 enabled 或 QWENPAW_AUTH_ENABLED 未开
  423/429: 限流锁定 / 过快
  502/503: { "detail": "无法连接 NocoBase,请稍后再试" }
```

### 5.4 插件装配(`plugin.py`)

`_on_startup` 内(在注册 checker / resolver 之后)`register_public_path("/api/nocobase-auth/login")`;`_on_uninstall` 内 `unregister_public_path(...)`。与现有生命周期对称。

### 5.5 前端 `console/src/api/modules/auth.ts`(新增)

```ts
async function nocobaseLogin(account, password): Promise<LoginResponse> {
  // 裸 fetch POST getApiUrl("/nocobase-auth/login"), body {account, password}
  // 返回 { token, username };非 2xx → 抛错(带 detail)
}
```

### 5.6 前端 `console/src/pages/Login/index.tsx`(改)

- **默认呈现**:登录页保持原生登录为默认表单;下方加一个次要入口"用 NocoBase 账号登录",点击切换到 NocoBase 模式(复用同一 account/password 两输入,提交按钮文案与目标接口切换),并提供返回原生登录的链接。用一个本地 state(如 `mode: "native" | "nocobase"`)控制,不引入路由变化。
- NocoBase 模式提交走 `authApi.nocobaseLogin`;成功后调用**现有** `setAuthToken(token)` + `navigate(redirect)`,并做与原生一致的开放重定向防护。错误按 §5.3 契约展示 `detail`。
- 原生登录路径保持不变;`authHeaders`/`AuthGuard`/`request` **不动**。

## 6. 错误处理与安全

1. **绝不盲信 claims**:凭据一律经 NocoBase `auth:signIn` 服务端验证;不接受前端直传 email/identity。
2. **限流**:与原生登录共用 `rate_limiter`,按 account + client IP 记录成败,防对 NocoBase 的爆破。
3. **登录时 ACL(fail-closed)**:signin 成功但用户不被 console 允许 → 403(复用频道门禁 checker,规则一致)。频道门禁每消息校验作为最终兜底。
4. **敏感数据**:日志不记完整 token/密码(至多 email/前缀);NocoBase token 仅登录瞬时使用、不落盘;admin `api_token` 维持加密静态存储。
5. **总开关**:`QWENPAW_AUTH_ENABLED` 未开时登录接口返回 409(签发 token 无意义,门禁本就不生效)。
6. **无 CORS 面**:NocoBase 只在后端被访问,浏览器不直连 NocoBase。

## 7. 测试策略

遵循 pytest、`unit/contract/integration` 分层、`p0/p1/p2` 标记、TDD 先红后绿。

**后端单元(pytest + pytest-httpx,mock NocoBase)**
- `NocoBaseClient.sign_in`:200→data;凭据错误→`NocoBaseAuthError`;网络错误→`NocoBaseRequestError`;断言 `X-Authenticator` 头与 body 形态。
- 登录路由:凭据成功→签发 token 且 `verify_token(token)==sender_id`;凭据错误→401;ACL 拒绝→403;插件/鉴权未启用→409;NocoBase 宕→502/503;限流路径(锁定→423)。
- 核心 `register_public_path`:注册后 `_should_skip_auth` 对该路径放行;注销后恢复保护;不影响其它 `/api/` 保护。

**契约(组件拼接,不连真 NocoBase)**
- `/api/nocobase-auth/login` 公开可达(未带任何 token 不被中间件提前 401)。
- 登录成功签发的 token 能通过 `AuthGuard` 的 `/api/auth/verify`。

**集成 / 手动端到端(桩或真 NocoBase)**
- 真实 `admin@nocobase.com/admin123` 走通:登录 → 进 console → 能对话(sender_id=email 命中 ACL 放行)。
- 非 console 白名单的 NocoBase 用户 → 登录 403。

**安全回归守卫(标 `p0`)**
1. 未开 `QWENPAW_AUTH_ENABLED` 时不签发有效会话(409)。
2. ACL 拒绝的用户登不进(403),且频道门禁仍兜底。
3. 公开路径仅限声明的登录端点,其它 `/api/nocobase-auth/*` 仍受保护。

## 8. 影响的文件(预估)

- `src/qwenpaw/app/auth.py` — 新增 `register_public_path`/`unregister_public_path` + `_should_skip_auth` 一处判定(核心,最小改动)。
- `plugins/bundle/nocobase_auth/nocobase_client.py` — 新增 `sign_in`。
- `plugins/bundle/nocobase_auth/routers.py` — 新增 `POST /login`。
- `plugins/bundle/nocobase_auth/plugin.py` — 装配 `register_public_path` 生命周期。
- `plugins/bundle/nocobase_auth/config.py` — 新增可选 `authenticator`(默认 `basic`)。
- `console/src/api/modules/auth.ts` — 新增 `nocobaseLogin`。
- `console/src/pages/Login/index.tsx` — 登录页加 NocoBase 入口。
- 对应 `tests/` 单元/契约用例;`console/` vitest。
- 部署:改完需 `cd console && npm run build`;插件新版需部署到 `~/.qwenpaw/plugins/nocobase_auth/`(注意备份别放进 plugins 目录)。
- 用户文档:`website/public/docs/*`(NocoBase 登录使用说明)。

## 9. 假设与待确认

- **已确认**:`auth:signIn`(basic)契约与 `admin@nocobase.com/admin123` 有效(实测 `localhost:13000`);`verify_token` 身份无关;`create_token` 可为任意身份签发。
- **待实现期确认**:不同 NocoBase 实例的认证器名是否恒为 `basic`(已做成可配置);signin 是否需附加 `X-App` 等头(默认应用下裸请求即可)。
- **可调参数**:token 默认有效期(沿用原生默认 7 天,支持 `expires_in`);前端 NocoBase 入口的具体呈现(切换 vs 分段)在实现时定。
