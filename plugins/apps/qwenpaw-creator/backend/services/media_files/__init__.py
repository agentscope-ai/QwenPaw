# -*- coding: utf-8 -*-
"""File-native media execution services.

The package owns provider execution and convergence into ``project.json``.
It deliberately depends only on the filesystem Project and Runtime stores.
"""

from .image_execution import (
    ExistingImageProvider,
    FileImageExecutionResult,
    FileImageExecutionService,
    ImageProvider,
    execute_file_image_command,
)
from .local_execution import (
    FileLocalMediaExecutionResult,
    FileLocalMediaExecutionService,
    FfmpegLocalMediaRunner,
    LocalMediaExecutionSpec,
    LocalMediaInput,
    LocalMediaRunner,
    execute_file_local_media_command,
    recover_file_local_media_project,
)
from .r2v_execution import (
    ExistingR2VProvider,
    FileR2VDispatch,
    FileR2VExecutionService,
    R2VProvider,
    R2VTaskState,
    execute_file_r2v_command,
    file_r2v_execution_service,
    recover_interrupted_image_tasks,
    shutdown_file_media_execution_services,
    start_file_media_execution_services,
)

__all__ = [
    "ExistingImageProvider",
    "ExistingR2VProvider",
    "FileImageExecutionResult",
    "FileImageExecutionService",
    "FileLocalMediaExecutionResult",
    "FileLocalMediaExecutionService",
    "FfmpegLocalMediaRunner",
    "FileR2VDispatch",
    "FileR2VExecutionService",
    "ImageProvider",
    "LocalMediaExecutionSpec",
    "LocalMediaInput",
    "LocalMediaRunner",
    "R2VProvider",
    "R2VTaskState",
    "execute_file_image_command",
    "execute_file_local_media_command",
    "execute_file_r2v_command",
    "file_r2v_execution_service",
    "recover_file_local_media_project",
    "recover_interrupted_image_tasks",
    "shutdown_file_media_execution_services",
    "start_file_media_execution_services",
]
