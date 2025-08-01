#!/usr/bin/python3

import pdb
import os
import yaml
import glob
from os import path
import sys
import time
from utils import parser
from utils.opts import GlobalOptions as GlobalOptions
from utils.logger import Logger
from utils.builder import BuilderInterface
from utils import types


class FlexiBuilder(object):

    def __init__(self, target):
        self.__target_name = target
        return

    def __get_target_spec(self):
        # Read the target spec from root .job.yml and look for target
        root_job_yml = os.path.join(GlobalOptions.topdir, ".job.yml")
        if os.path.exists(root_job_yml):
            with open(root_job_yml) as rp:
                try:
                    data = yaml.safe_load(rp)
                except Exception as e:
                    Logger.error(f"Failed to load root job.yml {root_job_yml}, error: {e}")
                    return None
            if self.__target_name in data['builds']:
                return data['builds'][self.__target_name]
            else:
                Logger.error(f"Could not find build-target in {root_job_yml}")
        else:
            Logger.error(f"Root .job.yml does not exists, not found: {root_job_yml}")
        return None

    def Main(self):

        ret = types.return_codes.SUCCESS

        target_spec = self.__get_target_spec()
        if target_spec == None:
            return types.return_codes.UNKNOWN_FAILURE

        target_to_build = GlobalOptions.alien_target_name if GlobalOptions.alien_target_name else self.__target_name
        builder = BuilderInterface.GetBuilder(target_spec, target_to_build)
        ret = builder.Build()

        if ret not in [types.return_codes.SUCCESS, types.return_codes.SKIPPED]:
            return ret

        Logger.info(f"Build {ret.name}")
        ret = builder.CreateArtifacts()

        # Check if we can retry regular build - applicable in case of reuse_houly_build_release_tag enabled.
        if GlobalOptions.reuse_houly_build_release_tag:
            if ret == types.return_codes.SUCCESS:
                Logger.info(f"Release candidate: {builder.GetReleaseCandidate()}")
            else:
                Logger.error("Failed to find successful hourly build with artifacts available for download - reverting to regular build")
                GlobalOptions.reuse_houly_build_release_tag = None
                builder = BuilderInterface.GetBuilder(target_spec, target_to_build)
                ret = builder.Build()
                Logger.info(f"Build {ret.name}")
                ret = builder.CreateArtifacts()

        if ret != types.return_codes.SUCCESS:
            Logger.error(f"Build failure or missing artifacts, error-code: {ret.value}, error-name: {ret.name}")
        else:
            Logger.info("Build successful, all artifacts found")
        return ret

def Main():
    if GlobalOptions.target_name:
        target = GlobalOptions.target_name
    else:
        Logger.error("Error: Please specify target-name")
        return types.return_codes.MISSING_ARG_FAILURE

    Logger.info(f"Building target: {target}")
    fbldr = FlexiBuilder(target)
    ret = fbldr.Main()
    return ret

