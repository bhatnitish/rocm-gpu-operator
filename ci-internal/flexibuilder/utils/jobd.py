#!/usr/bin/python3

import pdb
import os
from os import path
import subprocess
import shutil
import urllib.request
import requests

from utils.logger import Logger
import utils.types as types
import utils.timeprofiler as timeprofiler

class JobdInterface(object):

    JOBD_REST_URL = "http://jobd.test.pensando.io:3456"

    @staticmethod
    def DownloadBuildArtifact(target_id, artifact_name, output):
        url_prefix = f"{JobdInterface.JOBD_REST_URL}/savedbuilds/{target_id}"
        filename = f"{target_id}{artifact_name}"
        full_url = f"{url_prefix}?filename={filename}"
        Logger.debug(f"Downloading {full_url} into {output}")
        os.makedirs(os.path.dirname(output), exist_ok = True)
        timer = timeprofiler.TimeProfiler()
        try:
            timer.Start()
            with urllib.request.urlopen(full_url) as resp:
                with open(output, 'wb') as dest_file:
                    shutil.copyfileobj(resp, dest_file)
        except Exception as e:
            Logger.error(e)
            Logger.error(f"Failed to download - time spent {timer.TotalTime()}")
            return types.return_codes.BUILD_DOWNLOAD_FAILURE
        finally:
            timer.Stop()

        fileinfo = os.stat(output)
        Logger.debug(f"Downloaded {fileinfo.st_size/(1024.0 * 1024.0):.2f} MB in {timer.TotalTime()}")
        return types.return_codes.SUCCESS

    @staticmethod
    def RetrieveTags(repository, branch):
        url = f"{JobdInterface.JOBD_REST_URL}/tags/{repository}/{branch}"
        Logger.debug(f"Retrieve tags using: {url}")
        resp = requests.get(url)
        if resp.status_code != 200:
            Logger.error(f"Jobd URL {url} failed. Error while retrieving tags")
            return None

        repo_branch_tag = resp.json()
        Logger.debug(f"Using tag: {repo_branch_tag}")
        return repo_branch_tag

    @staticmethod
    def GetCISanityBuildSubmissionIds(repository, branch, rel_tag):
        submission_ids = list()

        tag_info = JobdInterface.RetrieveTags(repository, branch)
        if tag_info == None:
            return submission_ids

        label = tag_info.get("Label", "CI-Sanity-Build")
        url = f"{JobdInterface.JOBD_REST_URL}/submission?label={label}&branch={branch}&repo={repository}"
        Logger.debug(f"Retrieve SubmissionId using: {url}")
        resp = requests.get(url)
        if resp.status_code != 200:
            Logger.error(f"Jobd URL {url} failed. Error while retrieving submissions")
            return submission_ids

        repo_submissions = list()
        for submission in resp.json():
            if submission.get("Jobs", None):
                job = submission["Jobs"][0]
                if repository in job["Ref"]["Repository"]["Repository"]:
                    repo_submissions.append(submission)

        ret_val = repo_submissions
        if rel_tag == 'latest':
            submission_ids = list(map(lambda submission: submission.get("ID"), repo_submissions))
        else:
            rel_submissions = list(filter(lambda submission: submission.get("ReleaseTag", None) == rel_tag, repo_submissions))
            submission_ids = list(map(lambda submission: submission.get("ID"), rel_submissions))
            ret_val = repo_submissions

        Logger.debug(f"Found {len(submission_ids)} submissions: {submission_ids}")
        return ret_val

    @staticmethod
    def GetRootBuildTargetId(submission_id, target_name):

        url = f"{JobdInterface.JOBD_REST_URL}/submission/{submission_id}"
        Logger.debug(f"Retrieve root build details using: {url}")
        resp = requests.get(url)
        if resp.status_code != 200:
            Logger.error(f"Jobd URL {url} failed. Error while retrieving submission/targets")
            return None

        submission_info = resp.json()
        # Look for root-job
        target_id = None
        for job in submission_info.get("Jobs", []):
            for target in job.get("Targets", []):
                fqtn = target.get("Name", None)
                if '*root*/' in fqtn:
                    _, tmp = fqtn.split('/')
                    if target_name == tmp:
                        target_id = target.get("ID", None)
                        break
        if target_id:
            Logger.debug(f"Target: {target_name} target-id: {target_id}")
        else:
            Logger.error(f"Could not find target-id for target: {target_name}")

        return target_id

    @staticmethod
    def GetSubmissionReleaseTag(submission_id):
        url = f"{JobdInterface.JOBD_REST_URL}/submission/{submission_id}"
        Logger.debug(f"Retrieve root build details using: {url}")
        resp = requests.get(url)
        if resp.status_code != 200:
            Logger.error(f"Jobd URL {url} failed. Error while retrieving submission/targets")
            return None

        submission_info = resp.json()
        return submission_info.get("ReleaseTag", None)

    @staticmethod
    def GetAllRootBuildTargetIds(submission_id):

        url = f"{JobdInterface.JOBD_REST_URL}/submission/{submission_id}"
        Logger.debug(f"Retrieve root build details using: {url}")
        resp = requests.get(url)
        if resp.status_code != 200:
            Logger.error(f"Jobd URL {url} failed. Error while retrieving submission/targets")
            return None

        submission_info = resp.json()
        # Look for root-job
        target_id = None
        for job in submission_info.get("Jobs", []):
            for target in job.get("Targets", []):
                fqtn = target.get("Name", None)
                if '*root*/' in fqtn:
                    _, tmp = fqtn.split('/')
                    target_id = target.get("ID", None)
                    Logger.debug(f"Build :{tmp} JobId:{target_id}")

        return

    @staticmethod
    def GetSubmissionId(jobd_id):

        url = f"{JobdInterface.JOBD_REST_URL}/job/{jobd_id}"
        Logger.debug(f"Retrieve submission-id using: {url}")

        resp = requests.get(url)
        if resp.status_code != 200:
            Logger.error(f"Jobd URL {url} failed. Error while retrieving job details")
            return None

        job_info = resp.json()
        submission_id = job_info.get("SubmissionID")

        Logger.debug(f"Found the submission-id: {submission_id}")

        return submission_id

    @staticmethod
    def GetTargetStatus(submission_id, target_name):
        url = f"{JobdInterface.JOBD_REST_URL}/submission/{submission_id}"
        Logger.debug(f"Retrieve root build details using: {url}")
        resp = requests.get(url)

        assert resp.status_code == 200, f"Jobd URL {url} failed. Error while retrieving submission/targets"

        submission_info = resp.json()
        # Look for root-job
        status = None
        for job in submission_info.get("Jobs", []):
            for target in job.get("Targets", []):
                fqtn = target.get("Name", None)
                if '*root*/' in fqtn:
                    _, tmp = fqtn.split('/')
                    if target_name == tmp:
                        if target.get("FinishedAt", None) == None:
                            status = "Running"
                        elif target.get("Success", False) == False:
                            status ="Failed"
                        else:
                            status = "Success"
                        return status
        return status
