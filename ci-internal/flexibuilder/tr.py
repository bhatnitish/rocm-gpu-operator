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
from utils import targetrunner


if __name__ == '__main__':
    opts.InitTargetRunnerOptions()
    ret = targetrunner.Main()
    if ret == types.return_codes.SUCCESS:
        Logger.info(f"Success")
        sys.exit(0)
    else:
        Logger.error(f"Failed. error-code: {ret.value} and error-name: {ret.name}")
        sys.exit(ret.value)
