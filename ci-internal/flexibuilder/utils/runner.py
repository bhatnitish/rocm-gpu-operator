import pdb
import subprocess
import sys
from utils.logger import Logger
import utils.types as types

def run_command(args, env_vars, workdir, out_handle = None):

    outhandle = None
    try:
        # Start subprocess
        # bufsize = 1 means output is line buffered
        # universal_newlines = True is required for line buffering

        stdout_handle = None
        if out_handle:
            stdout_handle = out_handle

        process = subprocess.Popen(args,
                                   universal_newlines=True,
                                   env=env_vars,
                                   cwd=workdir, shell = False,
                                   stdout = stdout_handle, stderr = subprocess.STDOUT)
        # Get process return code
        return_code = process.wait()
    except Exception as e:
        Logger.error(e)
        return types.return_codes.CMD_RUNTIME_FAILURE
    finally:
        if outhandle:
            outhandle.close()

    if return_code == 0:
        return types.return_codes.SUCCESS
    return types.return_codes.CMD_RUNTIME_FAILURE
