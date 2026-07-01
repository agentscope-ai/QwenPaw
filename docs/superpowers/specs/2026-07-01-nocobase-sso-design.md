# QwenPaw × NocoBase SSO 身份接入设计

- **日期**: 2026-07-01
- **分支**: `feat/nocobase-auth`
- **状态**: 已评审通过,待转实现计划
- **作者**: JackPan(与 Claude 协作 brainstorming)

## 1. 背景与问题

`feat/nocobase-auth` 分支已实现:NocoBase 作为权限真源,`nocobase_auth` 插件把用户/角色同步到本地 `PermissionStore`,并通过 `BaseChannel._external_acl_checkers` 对频道做"角色 → 频道"的准入判定(console 为 fail-closed)。

本会话实测确认了当前的**关键缺口**:

- console 门禁只在 `payload.acl_sender_id` 非空时才触发(`app/channels/console/channel.py:374`)。
- `acl_sender_id = request.state.user`(`app/routers/console.py:171`),而 `request.state.user` 只由 QwenPaw **内置单用户**鉴权中间件在校验 token 后设置(`app/auth.py:632`)。
- 因此现状是"**QwenPaw 单用户登录 + 拿登录名去 NocoBase 数据比对角色**"的拼接模式,**没有**"用各自 NocoBase 账号登录、按用户做准入"的机制。

**目标**:让用户以各自的 NocoBase 身份访问 QwenPaw 的对话能力,QwenPaw 信任该身份并写入 `request.state.user`,**复用现有 ACL 门禁零改动**做按角色的频道准入。

### 使用场景(已澄清)

- 用户使用一个**封装页面**(处于 NocoBase 登录态),该页面**直接调用 QwenPaw 的对话接口** `/api/console/chat`。
- 部署为**两个独立站点/端口**(NocoBase 与 QwenPaw 分离)。
- 封装页面调用时**携带当前 NocoBase 用户的 token**。
- 因此**不需要** SSO 浏览器重定向 / 登录页 / 签发 QwenPaw token;只需"**随请求带身份 + QwenPaw 校验**"。

## 2. 目标与非目标

**目标**
- QwenPaw 对话接口接受"NocoBase 用户 token"作为身份来源,校验后按用户应用现有 ACL。
- 天然多用户:每请求各自身份、各自会话历史。
- 与现有内置单用户登录**并行兼容**,不破坏。

**非目标**
- 不实现完整 OAuth2/OIDC provider。
- 不做浏览器重定向 SSO。
- 不改 ACL 门禁判定逻辑(`permission_store.is_channel_allowed`、`channel_gate`)。
- 封装页面本身不在本仓库范围内(仅约定它该带的 header 契约)。

## 3. 选定方案(方案 A):插件注册"身份解析器",逐请求校验

在**核心 auth 中间件**开一个"外部身份解析器"扩展点(仿现有 `_external_acl_checkers`),由 `nocobase_auth` 插件填充"从 NocoBase token 解析出用户"的逻辑。身份写入 `request.state.user` 后,下游全部复用。

**选它的理由**:贴合"页面始终带 NocoBase token"的模型;NocoBase 逻辑全留插件、与现有插件式架构一致;ACL 门禁零改动;逐请求校验能**及时跟随 NocoBase 登出**;无需签发/管理 QwenPaw token。

被否方案:
- **B(token 交换)**:换成 QwenPaw token 再对话——页面要多管一个 token,QwenPaw token 比 NocoBase 会话活得久有吊销延迟。
- **C(核心内建)**:核心与 NocoBase 强耦合、不可插拔,违背边界。

## 4. 架构与数据流

**外部命门已验证**:`create_token`/`verify_token` 只验 HMAC 签名+有效期+吊销、**不校验是否注册用户**(`app/auth.py:170-202`);NocoBase `GET /api/auth:check` 端点存在,无/坏 token 返回 401 `INVALID_TOKEN`,有效 token 返回当前用户(本会话实测 `localhost:13000` 确认)。

```
封装页面(NocoBase 登录态,持有用户 token)
  │  POST http://qwenpaw:8088/api/console/chat
  │  Header: X-NocoBase-Token: <nocobase 用户 token>   ← 专用头,不占用 Authorization
  ▼
① 核心 auth 中间件 (app/auth.py)
   - 先试 Authorization: Bearer 里的 QwenPaw token(老逻辑,兼容内置登录)
   - 没有/无效 → 遍历 _external_identity_resolvers
       └─ NocoBase 插件解析器:读 X-NocoBase-Token
          → 调 NocoBase GET /api/auth:check(带 token)【短 TTL 缓存】
          → 200 取 email;401 视为未认证
   - 解析出 email → request.state.user = email
   - 两者都没有 → 401
  ▼
② console 路由 (app/routers/console.py:171)  acl_sender_id = request.state.user   ← 零改动
  ▼
③ console 门禁 (_external_acl_gate → NocoBase checker)  ← 零改动
   is_channel_allowed(email, "console") 按角色判定 allow/deny
  ▼
放行 → 进 agent;拒绝 → SSE error「您已被禁止访问此智能体。」
```

**关键性质**
- 逐请求解析,天然多用户,能及时跟随 NocoBase 登出。
- 会话隔离天然成立:console 用 `sender_id`(=email)派生 session。
- 内置单用户登录保持兼容(走 `Authorization: Bearer` 老路),SSO 是并行叠加的一条身份来源。

## 5. 组件与接口

改动 4 处:1 处核心开扩展点,3 处在插件内新增,互相通过清晰接口解耦。

### 5.1 核心 `app/auth.py` —— 新增"外部身份解析器"扩展点

```python
IdentityResolver = Callable[[Request], Awaitable[Optional[str]]]
_external_identity_resolvers: List[IdentityResolver] = []

def register_external_identity_resolver(resolver): ...
def unregister_external_identity_resolver(resolver): ...

def has_external_identity_resolvers() -> bool:
    return bool(_external_identity_resolvers)

async def _resolve_external_identity(request) -> Optional[str]:
    for r in _external_identity_resolvers:
        try:
            ident = await r(request)          # email 或 None
        except Exception:
            logger.exception("identity resolver failed"); continue
        if ident:
            return ident
    return None
```

中间件 dispatch **唯一改动**(`app/auth.py:622` 附近):

```python
user = verify_token(token) if token else None
if user is None:
    user = await _resolve_external_identity(request)   # ← 新增回退
if user is None:
    return 401
request.state.user = user
```

**解析器契约**:输入 `Request`(自行决定读哪个头),输出身份串(= NocoBase email,即 ACL 用的 sender_id)或 `None`;必须 async、不得抛出(helper 已兜底)。核心对 NocoBase 一无所知。

### 5.2 插件新增 `identity_resolver.py`(与 `channel_gate.py` 平行)

```python
def build_identity_resolver(engine, cache) -> IdentityResolver:
    async def resolve(request):
        if not (engine.config and engine.config.enabled): return None
        token = request.headers.get("X-NocoBase-Token")
        if not token: return None
        hit = cache.get(token)
        if hit is not None: return hit
        user = await engine.verify_user_token(token)        # 调 auth:check
        if user is None: return None
        sender_id = extract_sender_id(user, engine.config.user_id_field)
        cache.put(token, sender_id)
        return sender_id
    return resolve
```

**关键**:取 `sender_id` 复用与同步**同一套** `user_id_field`(email)逻辑,保证解析出的身份与 `PermissionStore` 用户 key 一致 → ACL 命中已知用户,而非被 fail-closed 当"未知"拒掉。

### 5.3 `NocoBaseClient.verify_user_token(user_token)`

```python
async def verify_user_token(user_token) -> Optional[dict]:
    # 用"用户的 token"而非插件持有的 admin api_token
    # → 单独发 GET /api/auth:check,Authorization: Bearer <user_token>
    # 200 → 返回 data(用户);401 INVALID_TOKEN → None;网络错误 → None 且标记"不可缓存"
```

现有 `_get_client()` 把 admin token 焊死在 header 里,故此处**另起带用户 token 的请求**(同样 `trust_env=False`、同 base_url)。

> 接口归属:解析器只依赖 `SyncEngine`,由 `SyncEngine.verify_user_token(token)` 作**薄封装委托**给 `NocoBaseClient.verify_user_token`(与 `engine.store`/`engine.config` 的依赖方式一致),解析器不直接触碰 client 内部。

### 5.4 短 TTL 缓存 `TokenIdentityCache`

- `token → (sender_id, expires_at)`,TTL ≈ **60s**,把每用户对 NocoBase 校验压到"每 60s 一次"。
- 代价:NocoBase 登出后 ≤TTL 才跟随失效;TTL 取小即可。简单 dict + 惰性过期。

### 5.5 插件装配(`plugin.py`)

`_on_startup` 里在注册 ACL checker 之后 `build_identity_resolver(...)` 并 `register_external_identity_resolver(...)`;`_on_uninstall` 里注销。与现有 checker 生命周期对称,共用 `SyncEngine` 的 client/config。

## 6. 鉴权开关细节(堵住 SSO-only 静默放行)

### 问题
现有 `_should_skip_auth`(`app/auth.py:636`):
```python
if not is_auth_enabled() or not has_registered_users():
    return True   # 整个跳过鉴权
```
- `is_auth_enabled()` 靠 `QWENPAW_AUTH_ENABLED` —— **总开关保留**,SSO 部署也必须设 `true`。
- `not has_registered_users()` 是坑:纯 SSO(无本地密码用户)时为真 → 鉴权被整个跳过 → 解析器不跑 → 人人畅通。

### 改法(最小,不破坏首次引导)
```python
def _should_skip_auth(request):
    if not is_auth_enabled():
        return True
    # 有本地用户 或 有外部身份源(NocoBase SSO)→ 强制鉴权;
    # 两者都无才跳过(保留 local 模式下"首个用户还没建时能进注册页")
    if not has_registered_users() and not has_external_identity_resolvers():
        return True
    # …其余不变:OPTIONS、_PUBLIC_PATHS/_PREFIXES、allow_no_auth_hosts
```

**为什么安全**:`/api/auth/register`、`/api/auth/login`、`/api/auth/status` 本就在 `_PUBLIC_PATHS`(`app/auth.py:53-55`),首次引导不受影响;纯 SSO 时解析器已注册 → 强制鉴权 → 无有效 NocoBase token 的请求 401。

**三种部署自洽**

| 部署 | QWENPAW_AUTH_ENABLED | 本地用户 | 插件启用 | 结果 |
|---|---|---|---|---|
| 关闭鉴权(开发) | 未设 | — | — | 全放行(不变) |
| 仅本地单用户 | true | 有 | 否 | 走 Authorization Bearer(不变) |
| 纯 SSO | true | 无 | 是 | 走 X-NocoBase-Token,门禁生效(本节修复) |
| 混合 | true | 有 | 是 | 两条身份源并行,QwenPaw token 优先 |

**配套**:`allow_no_auth_hosts` 保持 `[]`(否则封装页面/浏览器所在 host 命中白名单会被提前放行)。

## 7. 错误处理与安全

1. **跨域 CORS**:复用现有 `CORS_ORIGINS` 环境变量(`app/_app.py:612`),把封装页面 origin 加入即可;`allow_headers=["*"]` 已涵盖 `X-NocoBase-Token`;预检 OPTIONS 被 `_should_skip_auth` 放行。token 走请求头而非 cookie,不依赖第三方 cookie/SameSite。
2. **专用头 `X-NocoBase-Token`**:与 `Authorization: Bearer` 分离,优先级 = 先 QwenPaw token 后 NocoBase token,混合部署不打架。
3. **绝不盲信 claims**:身份一律经 `auth:check` 服务端校验,不接受页面直传 email,不本地解码 token 的 `sub` 就采信;`auth:check` 同时反映 NocoBase 侧登出/吊销。
4. **失败即拒(fail-closed)**:token 缺失/无效/过期、NocoBase 不可达 → 401。两类"拒绝"语义要分清:

   | 场景 | 响应 | 页面应对 |
   |---|---|---|
   | 无/坏 NocoBase token | **401**(auth 中间件) | 引导重新登录 NocoBase |
   | 身份有效但角色不许用 console | **200 + SSE error**「您已被禁止访问此智能体。」 | 提示"无权限" |

5. **缓存与登出时效**:正向缓存 TTL≈60s;负向处理区分——`auth:check` 明确 401 可短暂负缓存防刷;**网络错误/超时不缓存**,下次重试(避免一次抖动误挡满一个 TTL)。
6. **敏感数据**:日志不记完整 token(至多前缀/email);admin `api_token` 维持加密静态存储;用户 token 仅内存瞬时使用、不落盘。
7. **滥用防护**:`auth:check` 被缓存收敛;海量伪造 token 由负缓存 +(可选)简单限流兜底,不过度设计。

## 8. 测试策略

遵循 pytest、`unit/contract/integration` 分层、`p0/p1/p2` 标记、TDD 先红后绿。

**单元(mock NocoBase)**
- 核心 `auth.py`:注册表增删;`_resolve_external_identity` 返回首个非 None、吞异常继续、全 None→None;dispatch 三分支(QwenPaw token 优先且不调解析器 / 回退解析器成功 / 全失败 401);`_should_skip_auth` 回归守卫(鉴权开+无本地用户+有解析器→不跳过;+无解析器→跳过;公共路径始终跳过;`allow_no_auth_hosts` 生效)。
- 插件 `identity_resolver`:禁用→None;无头→None;缓存命中不发网络;未命中→校验+取 email+写缓存;失败→None;**sender_id 与 store key 一致性**。
- `verify_user_token`:200→dict;401→None;网络错误→None 且不可缓存;断言用用户 token 而非 admin token。
- `TokenIdentityCache`:TTL 命中/过期;正负缓存;惰性过期。

**契约(组件拼接,不连真 NocoBase)**
- 带 `X-NocoBase-Token` 的 `/api/console/chat`,解析器 mock 成 member→门禁 DENY;mock 成放行角色→进 agent。
- 优先级:同时带有效 QwenPaw token 与 `X-NocoBase-Token` → QwenPaw token 胜。

**集成(起后端 + 桩 NocoBase)**
- 桩 NocoBase 暴露 `auth:check`,驱动真中间件+真解析器+真门禁:有效 member→拒;有效放行角色→放行;无效 token→401;**NocoBase 宕机→401(fail-closed)**。等价于本会话手动端到端验证的自动化版,可进 CI。

**安全回归守卫(标 `p0`)**
1. fail-closed:校验不了→拒,永不开放。
2. 无旁路:只传 email 无可校验 token→进不来。
3. SSO 生效时 `_should_skip_auth` 不静默跳过。
4. `allow_no_auth_hosts` 空值被强制/文档化。

**范围外**:CI 不连真 NocoBase(用桩);封装页面不在本仓库(仅约定 header 契约)。

## 9. 假设与待确认

- **已确认**:`auth:check` 端点存在且行为符合预期(本会话实测)。`verify_token` 身份无关。
- **待实现期确认**:`auth:check` 是否需附加 `X-App` / `X-Authenticator` 等 NocoBase 头(取决于该实例的多应用/认证器配置);默认应用下裸 Bearer 已可 401 判定,实现时按需补头。
- **可调参数**:header 名 `X-NocoBase-Token`、缓存 TTL(60s)、CORS_ORIGINS 取值 —— 均为配置项,实现时按部署确定。

## 10. 影响的文件(预估)

- `src/qwenpaw/app/auth.py` — 扩展点 + `_should_skip_auth` 一处判断(核心,最小改动)。
- `~/.qwenpaw/plugins/nocobase_auth/identity_resolver.py` — 新增。
- `~/.qwenpaw/plugins/nocobase_auth/nocobase_client.py` — 新增 `verify_user_token`。
- `~/.qwenpaw/plugins/nocobase_auth/plugin.py` — 装配解析器 + 缓存生命周期。
- 缓存实现(插件内新增小模块或并入 `identity_resolver.py`)。
- 对应 `tests/` 单元/契约/集成用例。
- 用户文档:`website/public/docs/*`(SSO 接入 + header 契约),配置说明(`QWENPAW_AUTH_ENABLED`、`CORS_ORIGINS`、`allow_no_auth_hosts`)。
