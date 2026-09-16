"""管理员只读迁移预览接口。"""

from fastapi import APIRouter, Depends

from ...access.dependencies import require_platform_settings_manage
from ...migration.report import MigrationPreviewReport
from ...migration.scanner import scan_configured_migration_preview

router = APIRouter(
    prefix="/migration",
    tags=["migration"],
    dependencies=[Depends(require_platform_settings_manage)],
)


@router.get("/preview", response_model=MigrationPreviewReport)
async def get_migration_preview() -> MigrationPreviewReport:
    """返回只读扫描结果；本接口不包含迁移写入能力。"""
    return await scan_configured_migration_preview()
