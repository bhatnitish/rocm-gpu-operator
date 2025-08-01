#!/usr/bin/python3

from enum import Enum

class return_codes(Enum):
    SUCCESS                             = 0
    SKIPPED                             = 1
    UNKNOWN_FAILURE                     = 2
    BUILD_CMD_FAILURE                   = 4
    FS2_DOWNLOAD_FAILURE                = 5
    BUILD_DOWNLOAD_FAILURE              = 6
    MISSING_MAKEFILE_FAILURE            = 7
    MISSING_ARTIFACTS_COMMANDS_FAILURE  = 8
    MISSING_CMD_FAILURE                 = 9
    MISSING_ARG_FAILURE                 = 10
    ENV_VAR_PROCESS_FAILURE             = 11
    CMD_RUNTIME_FAILURE                 = 12
    DEPENDENT_TARGET_FAILURE            = 13
    INVALID_STORAGE_ID_PATTERN          = 14
    MINIO_DOWNLOAD_FAILURE              = 15
    MISSING_ARTIFACT_FAILURE            = 16

