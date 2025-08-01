#!/usr/bin/python3

import pdb
import logging
import os
from utils.opts import GlobalOptions as GlobalOptions

def InitLogger():
    rl = logging.getLogger('root')
    rl.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s')

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    rl.addHandler(stream_handler)

    if not os.path.exists(GlobalOptions.logdir):
        os.makedirs(GlobalOptions.logdir, exist_ok=True)

    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s')
    file_handler = logging.FileHandler(os.path.join(GlobalOptions.logdir, GlobalOptions.logfile), mode = 'w')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    rl.addHandler(file_handler)
    return rl

def NewLogger(name):
    al = logging.getLogger(name)
    al.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s')

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.ERROR)
    stream_handler.setFormatter(formatter)
    al.addHandler(stream_handler)

    if not os.path.exists(GlobalOptions.logdir):
        os.makedirs(GlobalOptions.logdir, exist_ok=True)

    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s')
    file_handler = logging.FileHandler(os.path.join(GlobalOptions.logdir, GlobalOptions.logfile), mode = 'w')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    al.addHandler(file_handler)
    return al

Logger = InitLogger()

