#!/usr/bin/python3

import pdb
import os
import glob
from os import path
import sys
import datetime
from utils import parser
from utils.opts import GlobalOptions as GlobalOptions
from utils.logger import Logger
import utils.runner as runner
from utils import types
from prettytable import PrettyTable
from multiprocessing import pool

class Target(object):

    def __init__(self, name, spec, workdir):
        self._target_name = name
        self._target_spec = spec
        self._workdir = workdir
        self._start_time = None
        self._end_time = None
        self._result = types.return_codes.UNKNOWN_FAILURE
        import utils.logger as logger
        self._logger = logger.NewLogger(name)
        self._cmd_out_file = os.path.join(GlobalOptions.logdir, f"{self._target_name}_cmd.out")
        self._std_out = None

    @property
    def name(self):
        return self._target_name

    @property
    def spec(self):
        return self._target_spec

    @property
    def workdir(self):
        return self._workdir

    @property
    def end_time(self):
        return self._end_time

    @property
    def start_time(self):
        return self._start_time

    @property
    def total_time(self):
        return self.end_time - self.start_time

    @property
    def result(self):
        return self._result

    @property
    def logger(self):
        return self._logger

    @property
    def std_out(self):
        return self._std_out

    def start(self):
        self._std_out = open(self._cmd_out_file, "w", buffering = 1)
        self._start_time = datetime.datetime.now()

    def end(self, result):
        self._std_out.close()
        self._end_time = datetime.datetime.now()
        self._result = result

def _run_target(target):
    target.logger.info(f"\n------------------------ Running Target : {target.name} ----------------------------\n")

    target.start()

    def __extract_env_variables(cmd_env):
        var_vals = os.environ.copy()
        if cmd_env == None:
            return var_vals

        tokens = cmd_env.split(';')
        for t in tokens:
            if '=' in t:
                var, val = t.split('=')
                var_vals[var] = val
        return var_vals

    if not hasattr(target.spec, 'commands'):
        target.logger.fatal(f"Missing 'comgands' for {target.name}")
        target.end(types.return_codes.MISSING_CMD_FAILURE)
        return

    for idx, cmd_def in enumerate(target.spec.commands):
        ret = None
        cmd_name = getattr(cmd_def, 'name', f'cmd-{idx}')
        if not hasattr(cmd_def, 'cmd'):
            target.logger.fatal("Cmd: {cmd_name} has empty cmd-field. Invalid rules.yml")
            target.end(types.return_codes.MISSING_CMD_FAILURE)
            return

        cmd_description = getattr(cmd_def, 'description', None)

        if hasattr(cmd_def, 'relative_path'):
            setattr(cmd_def, 'workdir', os.path.join(target.workdir, cmd_def.relative_path))
        else:
            setattr(cmd_def, 'workdir', target.workdir)

        target.logger.debug(f"Running Cmd: {cmd_name}, description: {cmd_description}")
        var_vals = __extract_env_variables(getattr(cmd_def, 'env', None))
        if var_vals:
            setattr(cmd_def, 'env', var_vals)
            target.logger.debug(f"Environment variables: {cmd_def.env}")
        else:
            target.logger.fatal(f"Failed to process env-variables: {cmd_name}")
            target.end(types.return_codes.ENV_VAR_PROCESS_FAILURE)
            return

        cmd_tokens = cmd_def.cmd.split()
        if GlobalOptions.dryrun:
            cmd_tokens.insert(0, 'echo')

        ret = runner.run_command(cmd_tokens, cmd_def.env, cmd_def.workdir, target.std_out)
        if ret != types.return_codes.SUCCESS:
            target.logger.fatal(f"Failed to run the command: {cmd_def.cmd}")
            target.end(ret)
            return
        else:
            target.logger.debug(f"Completed command: {cmd_def.cmd}")

    target.logger.info(f"\n------------------------ Completed Target : {target.name} ---------------------------\n")
    target.end(types.return_codes.SUCCESS)
    return

def work(target):
    _run_target(target)
    return True if target.result == types.return_codes.SUCCESS else False

class TargetRunner(object):

    def __init__(self, rules_file, targets_to_run):
        self.__rules_file = rules_file
        self.__targets = list()
        self.__rules_db = self.__load_rules()
        if self.__rules_db == None:
            raise Exception("Invalid rules-db file")

        target_names = list(map(lambda x: x.replace("-", "_"), targets_to_run.split(',')))
        for name in target_names:
            spec = self.__get_target_spec(name)
            if not spec:
                raise Exception(f"Target spec is None for {name}")
            self.__targets.append(Target(name, spec, self.__rules_db.meta.workdir))
        return

    def __load_rules(self):
        Logger.debug(f"Loading rules from {self.__rules_file}")
        try:
            return parser.YmlParse(self.__rules_file)
        except Exception as e:
            Logger.error(e)
            Logger.fatal(f"Failed to load rules from {self.__rules_file}")
        return None

    def __get_target_spec(self, name):
        if self.__rules_db == None:
            Logger.error("Missing rules")
            return None

        if hasattr(self.__rules_db, 'targets'):
            if hasattr(self.__rules_db.targets, name):
                spec = getattr(self.__rules_db.targets, name)
                return spec
        Logger.error("Invalid rules or missing target")
        return None

    def Main(self):

        workers = pool.ThreadPool(processes=5)

        ret = types.return_codes.SUCCESS
        Logger.info(f"\n------------------------ Running all targets ----------------------------\n")
        if GlobalOptions.enable_concurrency:
            all_targets = workers.map_async(work, self.__targets)
            all_targets.wait()
            if not all_targets.successful():
                ret = types.return_codes.UNKNOWN_FAILURE
        else:
            for target in self.__targets:
                _run_target(target)
                if target.result != types.return_codes.SUCCESS:
                    ret = target.result
        Logger.info(f"\n------------------------ Completed all targets ---------------------------\n")

        return ret

    def PrintReport(self, result):
        output = PrettyTable()
        output.field_names = ["Target", "Outcome", "Total Time"]
        output.align['Target'] = 'l'
        output.align['Outcome'] = 'r'
        for target in self.__targets:
            output.add_row([target.name, "Success" if target.result == types.return_codes.SUCCESS else "Failure", f"{target.total_time}"])
        print(output)
        print("")
        print(f"Overall Status: {result.name}")
        print("")
        return

def LookupRulesFile(name):
    files = glob.glob(f"{GlobalOptions.rules_db_path}/*.yml")
    if len(files) == 0:
        Logger.error(f"No rules.yml file found in {GlobalOptions.rules_db_path}")
        return None

    for fname in files:
        file_path = os.path.join(GlobalOptions.rules_db_path, fname)
        try:
            rb = parser.YmlParse(file_path)
            if rb.meta.name == name:
                return file_path
        except Exception as e:
            Logger.error(e)
            Logger.fatal(f"Failed to load target-rules from {file_path}")
    return None

def Main():
    if not GlobalOptions.target_names:
        Logger.error("Error: Please specify atleast one target-names")
        return types.return_codes.MISSING_ARG_FAILURE

    if not GlobalOptions.rules_name:
        Logger.error("Error: Please specify correct rules-name")
        return types.return_codes.MISSING_ARG_FAILURE

    rules_file = LookupRulesFile(GlobalOptions.rules_name)
    if rules_file:
        Logger.info(f"Running targets: {GlobalOptions.target_names}")
        runner = TargetRunner(rules_file, GlobalOptions.target_names)
        ret = runner.Main()
        runner.PrintReport(ret)
    else:
        ret = types.return_codes.INVALID_RULES_FILE
    return ret

