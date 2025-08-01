#!/usr/bin/python3

import pdb
import os
import sys
import shutil
from utils.logger import Logger
import utils.types as types
from bs4 import BeautifulSoup
import urllib.request
import requests
import utils.timeprofiler as timeprofiler

def create_compressed_tar(output, cmd_args, work_dir="."):
    Logger.info(f"Running routine: create_compressed_tar")

    if not hasattr(cmd_args, 'folders'):
        Logger.error("Missing files in cmd_args")
        return types.return_codes.MISSING_ARG_FAILURE

    cmd = f"tar -zvc -f {output}"

    if hasattr(cmd_args, "exclude"):
        cmd += f" --exclude={cmd_args.exclude}"

    fld_list = " ".join(cmd_args.folders)
    cmd += f" {fld_list}"

    Logger.info(f"Building output: {output} with cmd: {cmd}, dir: {work_dir}")
    cwd = os.getcwd()
    ret = 0
    try:
        os.chdir(work_dir)
        ret = os.system(cmd)
    finally:
        os.chdir(cwd)

    if ret != 0:
        return types.return_codes.CMD_RUNTIME_FAILURE
    return types.return_codes.SUCCESS

def fetch_page(url):
    Logger.debug(f"Retrieve : {url}")
    resp = requests.get(url)
    if resp.status_code != 200:
        Logger.error(f"Jobd URL {url} failed. Error while retrieving tags")
        return None
    return resp.text

def download_file(full_url, dest_file):
    os.makedirs(os.path.dirname(dest_file), exist_ok = True)
    timer = timeprofiler.TimeProfiler()
    try:
        timer.Start()
        with urllib.request.urlopen(full_url) as resp:
            with open(dest_file, 'wb') as fp:
                shutil.copyfileobj(resp, fp)
    except Exception as e:
        Logger.error(e)
        Logger.error(f"Failed to download - time spent {timer.TotalTime()}")
        return types.return_codes.BUILD_DOWNLOAD_FAILURE
    finally:
        timer.Stop()

    fileinfo = os.stat(dest_file)
    Logger.debug(f"Downloaded {fileinfo.st_size/(1024.0 * 1024.0):.2f} MB in {timer.TotalTime()}")
    return types.return_codes.SUCCESS

def get_file_names_from_html(html_doc):
    """
    Parses an HTML document and extracts file names from <a> tags within <td> elements,
    excluding "Parent Directory".

    Args:
        html_doc (str): The HTML content as a string.

    Returns:
        list: A list of strings, where each string is a file name.
    """
    soup = BeautifulSoup(html_doc, 'html.parser')
    file_names = []

    # Find all <a> tags within <td> elements
    # These typically correspond to the file/directory links in such index pages
    for link_tag in soup.find_all('td'):
        anchor_tag = link_tag.find('a')
        if anchor_tag:
            # Get the text content of the <a> tag
            file_name = anchor_tag.text.strip()
            # We want to exclude the "Parent Directory" link
            if file_name and file_name != "Parent Directory":
                # In this specific HTML, the actual file name is in the href attribute
                # and the text content might be truncated.
                # So, we'll use the href attribute to get the full file name.
                href = anchor_tag.get('href')
                if href and not href.endswith('/'): # Exclude directory links that end with '/'
                    # We can use os.path.basename to get the file name from the path if needed
                    # import os
                    # file_names.append(os.path.basename(href))
                    file_names.append(href)
    return file_names
