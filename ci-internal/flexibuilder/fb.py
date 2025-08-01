#!/usr/bin/python3

import pdb
import os
import glob
from os import path
import sys
import time
import subprocess
from utils import parser
from utils import opts
from utils.logger import Logger
from utils import types
from utils import flexibuilder


def LogEnvVariables():
    Logger.info("\n")
    Logger.info("Environment Variables:")
    jobd_variables = [
        "JOBD_VCPUS",
        "JOB_BASE_REPOSITORY",
        "JOB_FORK_REPOSITORY",
        "JOB_REPOSITORY",
        "JOB_ID",
        "JOB_PR",
        "JOB_BRANCH",
        "JOB_BASE_BRANCH",
        "TARGET_ID",
        "TARGET_NAME",
        "RELEASE",
        "GITHUB_LABELS",
    ]
    for var in jobd_variables:
        Logger.info(f"{var}={os.getenv(var, '')}")
    Logger.info("\n")
    return

if __name__ == '__main__':
    opts.InitFlexbuilderOptions()
    LogEnvVariables()
    ret = flexibuilder.Main()
    if ret == types.return_codes.SUCCESS:
        sys.exit(0)
    else:
        Logger.error(f"Build failed. error-code: {ret.value} and error-name: {ret.name}")
        sys.exit(ret.value)
