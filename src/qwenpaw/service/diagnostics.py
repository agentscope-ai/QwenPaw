"""Actionable allowlisted diagnostics without driver messages or credentials."""

from .config import ServiceError

_HINTS = {
    "28P01": "数据库用户名或密码不匹配。核对 service.local.json 与数据库实际账户；修改 .env 不会更新已初始化数据库的密码。",
    "28000": "数据库身份认证失败，请核对实际数据库用户和认证配置。",
    "3D000": "目标数据库不存在，请核对连接串中的数据库名及容器初始化配置。",
    "3F000": "目标 schema 不存在，请执行 service database-upgrade --yes。",
    "42501": "数据库权限不足，请确认运行账户有目标 schema 的创建、迁移和访问权限。",
    "domain_migration_not_validated": "QWENPAW_CUTOVER_VALIDATED_DOMAINS 未完成配置；全新实例可用 service init --fresh，已有数据须先完成迁移核验。",
    "legacy_writes_not_frozen": "QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS 未完成配置；先停止旧存储写入，再声明切换。",
    "postgres_writes_not_open": "QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS 未完成配置；完成迁移核验后再开放 PostgreSQL 写入。",
    "schema_not_initialized": "数据库尚未初始化，请先执行 service database-upgrade --yes。",
    "schema_revision_incomplete": "数据库版本与代码不一致，请停服备份后执行 service database-upgrade --yes。",
    "nonempty_unversioned_schema": "目标 schema 已有业务表但无迁移版本，不能作为空库初始化；请核验已有数据及迁移记录。",
}


def safe_error_detail(exc: Exception) -> str:
    if isinstance(exc, ServiceError):
        return str(exc)
    pending = [exc]
    visited = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        for code in (
            getattr(current, "error_code", None),
            getattr(current, "sqlstate", None),
        ):
            if isinstance(code, str) and code in _HINTS:
                return f"{code}: {_HINTS[code]}"
        if type(current) is RuntimeError and current.args == (
            "nonempty_unversioned_schema",
        ):
            return _HINTS["nonempty_unversioned_schema"]
        for nested in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return type(exc).__name__
