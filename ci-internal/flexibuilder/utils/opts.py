#!/usr/bin/python3

import argparse
import os
import subprocess

GlobalOptions = argparse.Namespace()
try:
    GlobalOptions.topdir = subprocess.check_output(['git', 'rev-parse', '--show-toplevel']).decode("utf-8").strip()
except Exception:
    GlobalOptions.topdir = os.getcwd()
GlobalOptions.logdir = os.path.join(GlobalOptions.topdir, "logs")
GlobalOptions.logfile = 'runner.log'

def InitFlexbuilderOptions():
    cmd_parser = argparse.ArgumentParser(description='FlexiBuilder')
    cmd_parser.add_argument('--target-name', dest='target_name', default=None, required=True, help='Target name defined in /sw/.job.yml')
    cmd_parser.add_argument('--dryrun', dest='dryrun', action='store_true', help='Dryrun for local testing purpose')
    cmd_parser.add_argument('--repository', dest='repository', default='pensando/sw', help='Pensando Repository')
    cmd_parser.add_argument('--branch', dest='branch', default='master', help='Branch name')
    cmd_parser.add_argument('--reuse-hourly-builds', dest='reuse_houly_build_release_tag', default=None, help='Reuse hourly builds')
    cmd_parser.add_argument('--reuse-private-submission', dest='reuse_private_submission_id', default=None, help='Reuse private submission')
    cmd_parser.add_argument('--reuse-minio-version', dest='reuse_minio_storage', default=None, help='Reuse private minio storage')
    cmd_parser.add_argument('--makefile', dest='makefile', default=None, help='Makefile to use for new build')
    cmd_parser.add_argument('--alien-target-name', dest='alien_target_name', default=None, help='Cross repo target-name')
    options = cmd_parser.parse_args()
    GlobalOptions.__dict__.update(options.__dict__)
    return

def InitTargetRunnerOptions():
    cmd_parser = argparse.ArgumentParser(description='TargetRunner')
    cmd_parser.add_argument('--rules-db', dest='rules_db_path', default=None, required=True, help='Path to container rules files')
    cmd_parser.add_argument('--rules-name', dest='rules_name', default=None, help='Name of the rule to refer')
    cmd_parser.add_argument('--target-names', dest='target_names', default=None, help='Comma separate target names')
    cmd_parser.add_argument('--enable-concurrency', dest='enable_concurrency', action='store_true', help='Enable concurrency')
    cmd_parser.add_argument('--dryrun', dest='dryrun', action='store_true', help='Dryrun for local testing purpose')
    options = cmd_parser.parse_args()
    GlobalOptions.__dict__.update(options.__dict__)
    return

