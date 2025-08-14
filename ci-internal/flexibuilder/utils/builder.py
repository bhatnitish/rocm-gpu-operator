#!/usr/bin/python3

import pdb
import os
from os import path
import subprocess
import urllib
import urllib.request
import time

from utils.opts import GlobalOptions
from utils.logger import Logger
import utils.runner as runner
import utils.types as types
import utils.common_routines as cmn_routines
import utils.timeprofiler as timeprofiler
from utils.jobd import JobdInterface


class BaseImageBuilder(object):

    def __init__(self, target_spec, target_name):
        self.target_spec = target_spec
        self.target_name = target_name

    def Build(self):
        Logger.info(f"BaseBuilder: NoOp for {self.target_name}")
        return types.return_codes.SKIPPED


class LocalWorkspaceImageBuilder(BaseImageBuilder):

    def __init__(self, target_spec, target_name):
        super().__init__(target_spec, target_name)

    def Build(self):

        if not os.path.exists(GlobalOptions.makefile):
            Logger.error(f"Missing file :{GlobalOptions.makefile}")
            return types.return_codes.MISSING_MAKEFILE_FAILURE

        if GlobalOptions.dryrun:
            cmd = f"echo 'make -f {GlobalOptions.makefile} {self.target_name}'"
        else:
            cmd = f"make -f {GlobalOptions.makefile} {self.target_name}"
        timer = timeprofiler.TimeProfiler()
        timer.Start()
        ret = runner.run_command(cmd.split(), os.environ.copy(), os.getcwd())
        timer.Stop()
        if ret != types.return_codes.SUCCESS:
            Logger.error(f"Failed to run the command: {cmd}, TotalTime: {timer.TotalTime()}")
            return ret
        else:
            Logger.info(f"Completed command: {cmd}, TotalTime: {timer.TotalTime()}")
        return types.return_codes.SUCCESS

class BuilderInterface:

    ROOT_BUILD_URL = "http://assets-hq.pensando.io/builds"

    class BaseBuilder(object):

        def __init__(self, target_spec, target_name):
            Logger.debug(f"Initializing base-class for {target_name}")
            self.target_name = target_name
            self.target_spec = target_spec
            self.builder = BaseImageBuilder(self.target_spec, self.target_name)

        def UploadArtifact(self):
            return types.return_codes.SUCCESS

        def Build(self):
            return self.builder.Build()

        def CreateArtifacts(self):
            result = types.return_codes.SUCCESS
            if 'artifacts' in self.target_spec:
                Logger.info(f"Checking {len(self.target_spec['artifacts'])} artifacts")
                result = types.return_codes.SUCCESS
                for idx, entry in enumerate(self.target_spec['artifacts']):
                    Logger.info(f"Check {idx}: {entry}")
                    if os.path.exists(entry):
                        Logger.info(f"Artifact available: {entry}")
                    else:
                        Logger.error(f"Artifact missing: {entry}")
                        result = types.return_codes.MISSING_ARTIFACT_FAILURE
            else:
                Logger.fatal("Missing 'artifacts' in build-specification - IGNORED")

            return result

    class AssetArtifactInterface(BaseBuilder):

        def __init__(self, target_spec, target_name, repository, release_tag):
            super().__init__(target_spec, target_name)
            self.__hourly_bld = release_tag

            folder_name = 'hourly'
            if repository == 'pensando/sw':
                self.__url_prefix = None
            else:
                if repository.startswith('pensando/'):
                    folder_name = repository[len('pensando/'):]
                self.__url_prefix = f"{BuilderInterface.ROOT_BUILD_URL}/hourly-{folder_name}/{release_tag}/"
            # Collect all the files from this url endpoints
            listing = cmn_routines.fetch_page(self.__url_prefix)
            self.__file_names = cmn_routines.get_file_names_from_html(listing)

        def _find_matching_file(self, asset_entry):
            basename = os.path.basename(asset_entry)
            asset_prefix = str(basename)
            if '.tar.gz' in basename:
                asset_prefix = str(basename).replace(".tar.gz", "")
            elif '.tgz' in basename:
                asset_prefix = str(basename).replace(".tgz", "")
            for entry in self.__file_names:
                if asset_prefix in entry:
                    return entry
            return None

        def DownloadArtifactsFromAssetURL(self):
            """
            Use jobd REST/APIs download each artifact
            """
            if self.__url_prefix == None or len(self.__file_names) == 0:
                Logger.error(f"Unsupported assets for AssetHQ Integration, url: {self.__url_prefix} and files: {self.__file_names}")
                return types.return_codes.MISSING_ARTIFACT_FAILURE

            if 'artifacts' in self.target_spec:
                resp = types.return_codes.SUCCESS
                timer = timeprofiler.TimeProfiler()
                timer.Start()
                Logger.info(f"Total number of artifacts to download: {len(self.target_spec['artifacts'])}")
                for idx, entry in enumerate(self.target_spec['artifacts']):
                    Logger.info(f"Artifact-{idx+1}: {entry}")
                    # Download file from self.__url_prefix + artifact-name + prefix/suffix
                    download_url = f"{self.__url_prefix}/{self._find_matching_file(entry)}"
                    if download_url:
                        resp = cmn_routines.download_file(download_url, entry)
                        if resp != types.return_codes.SUCCESS:
                            return resp
                    else:
                        Logger.error(f"Could not find downloadable URL for {entry}")
                        return types.return_codes.MISSING_ARTIFACT_FAILURE
                timer.Stop()
                Logger.info(f"Downloaded all artifacts from {self.__url_prefix}, TotalTime: {timer.TotalTime()}")
            else:
                Logger.warn("Missing 'artifacts' in build-specification - IGNORED")
            return types.return_codes.SUCCESS


        def CreateArtifacts(self):
            Logger.info(f"AssetArtifactInterface: Downloading for {self.target_name} from {self.__url_prefix}")
            return DownloadArtifactsFromAssetURL()

    class LocalWorkspaceArtifactBuilder(BaseBuilder):

        def __init__(self, target_spec, target_name):
            super().__init__(target_spec, target_name)
            Logger.debug(f"Initializing local-build for {target_name}")
            self.builder = LocalWorkspaceImageBuilder(self.target_spec, self.target_name)


    class DirtyJobArtifactBuilder(BaseBuilder):

        def __init__(self, target_spec, target_name, target_id):
            super().__init__(target_spec, target_name)
            self.__build_id = target_id

        def CreateArtifacts(self):
            return self.DownloadArtifactsFromBuild(self.__build_id)

        def DownloadArtifactsFromBuild(self, target_id):
            """
            Use jobd REST/APIs download each artifact
            """
            if 'artifacts' in self.target_spec:
                timer = timeprofiler.TimeProfiler()
                timer.Start()
                Logger.info(f"Total number of artifacts to download: {len(self.target_spec['artifacts'])}")
                for idx, entry in enumerate(self.target_spec['artifacts']):
                    Logger.info(f"Artifact-{idx+1}: {entry}")
                    resp = JobdInterface.DownloadBuildArtifact(target_id, entry, entry)
                    if resp != types.return_codes.SUCCESS:
                        return resp
                timer.Stop()
                Logger.info(f"Downloaded all artifacts from build: {target_id}, TotalTime: {timer.TotalTime()}")
            else:
                Logger.warn("Missing 'artifacts' in build-specification - IGNORED")
            return types.return_codes.SUCCESS

    class PrivateBuildArtifactBuilder(DirtyJobArtifactBuilder):

        def __init__(self, target_spec, target_name, repository, submission_id):
            super().__init__(target_spec, target_name, None)
            self.__repository = repository
            self.__submission_id = submission_id

        def CreateArtifacts(self):
            """
            Use JobdInterface to get submission-id for this branch/release_tag
            Look for the corresponding build-job for this target
            Use JobdInterface API to download required artifacts
            """

            target_id = JobdInterface.GetRootBuildTargetId(self.__submission_id, self.target_name)
            if target_id == None:
                Logger.error(f"Invalid target_name or missing artifacts. SubmissionId: {self.__submission_id}, target: {self.target_name}")
                return types.return_codes.UNKNOWN_FAILURE

            return self.DownloadArtifactsFromBuild(target_id)

    class SanityBuildArtifactBuilder(DirtyJobArtifactBuilder):

        def __init__(self, target_spec, target_name, repository, branch_name, release_tag = 'latest'):
            super().__init__(target_spec, target_name, None)
            self.__repository = repository
            self.__branch_name = branch_name
            self.__release_tag = release_tag
            self.__release_candidate = None

        def CreateArtifacts(self):
            """
            Use JobdInterface to get submission-id for this branch/release_tag
            Look for the corresponding build-job for this target
            Use JobdInterface API to download required artifacts
            """

            resp = types.return_codes.MISSING_ARTIFACT_FAILURE
            repo_submissions = JobdInterface.GetCISanityBuildSubmissionIds(self.__repository, self.__branch_name, self.__release_tag)
            if len(repo_submissions) == 0:
                Logger.error(f"Could not find submissions for branch: {self.__repository}/{self.__branch_name} and release-tag: {self.__release_tag}")
                resp = types.return_codes.UNKNOWN_FAILURE
            else:
                for submission in repo_submissions[:10]:
                    submission_id = submission["ID"]
                    target_id = JobdInterface.GetRootBuildTargetId(submission_id, self.target_name)
                    if target_id:
                        resp = self.DownloadArtifactsFromBuild(target_id)
                        if resp == types.return_codes.SUCCESS:
                            self.__release_candidate = submission["ReleaseTag"]
                            break
                    Logger.error(f"Error: {resp} processing submission {submission_id}, target-id: {target_id}")
                if resp != types.return_codes.SUCCESS:
                    Logger.warn("Failed to find successful CI-Sanity-Build root target with associated artifacts")
                    Logger.info("Using asset-hq/hourly")
                    for submission in repo_submissions:
                        release_tag = submission.get("ReleaseTag")
                        try:
                            assetIntf = BuilderInterface.AssetArtifactInterface(self.target_spec, self.target_name,
                                                                                GlobalOptions.repository, release_tag)
                            resp = assetIntf.DownloadArtifactsFromAssetURL()
                            if resp == types.return_codes.SUCCESS:
                                self.__release_candidate = submission["ReleaseTag"]
                                break
                        except Exception as e:
                            Logger.error(f"Error: Exception while downloading from minio server, {e}")
            return resp

        def GetReleaseCandidate(self):
            return self.__release_candidate

    class MinioStorageArtifactBuilder(BaseBuilder):

        def __init__(self, target_spec, target_name, repository, storage_id):
            super().__init__(target_spec, target_name)
            self.__repository = repository
            self.__storage_id = storage_id

        def CreateArtifacts(self):
            return self.DownloadArtifactsFromMinio(self.__storage_id)

        def DownloadArtifactsFromMinio(self, storage_id):
            """
            Parse storage_id to extract FQON & version and download asset.tgz

            storage_id pattern: (environment variable:PRIVATE_MINIO_VERSION)
            bucket-name: dev-pvt-builds
            asset-name: string, {username}/{build-name}
            version: string, {version} or {git-sha}

            storage_id := {asset-name}@{version}
            """

            ASSET_UTILITY = '/bin/asset-pull'
            ASSET_BUCKET_PREFIX = 'dev-pvt-images'


            if self.target_spec.get('artifacts', None) == None:
                Logger.fatal("Missing 'artifacts' in build-specification - IGNORED")
                return types.return_codes.SUCCESS

            if '@' not in storage_id:
                Logger.fatal(f"Incorrect asset storage_id: {storage_id} - ABORT")
                return types.return_codes.INVALID_STORAGE_ID_PATTERN

            asset_name, version = storage_id.split('@')
            user_id, build_name = asset_name.split('/')

            timer = timeprofiler.TimeProfiler()
            timer.Start()
            for idx, entry in enumerate(self.target_spec['artifacts']):
                asset_cmd = f"{ASSET_UTILITY} --bucket {ASSET_BUCKET_PREFIX} --asset-name {entry} {user_id}/{build_name} {version} {entry}"
                result = subprocess.run(asset_cmd.split(" "), stdout=subprocess.PIPE, stderr = subprocess.PIPE)
                if result.returncode != 0:
                    Logger.fatal("Failed to download assets {storage_id}, return code: {result.returncode}")
                    try:
                        Logger.error("Cmd std-out: {result.stdout.decode('utf-8').split('\n')} std-err: {result.stderr.decode('utf-8').split('\n')}")
                    except:
                        pass
                    return types.return_codes.MINIO_DOWNLOAD_FAILURE

            timer.Stop()
            Logger.info(f"Downloaded all artifacts, TotalTime: {timer.TotalTime()}")
            return types.return_codes.SUCCESS

    @staticmethod
    def GetBuilder(target_spec, target_name):
        # Check for environment variables

        if GlobalOptions.reuse_houly_build_release_tag:
            Logger.info(f"Skip-Build, Reconstruct artifacts from release-tag: {GlobalOptions.reuse_houly_build_release_tag}")
            return BuilderInterface.SanityBuildArtifactBuilder(target_spec, target_name,
                                                               GlobalOptions.repository,
                                                               GlobalOptions.branch,
                                                               GlobalOptions.reuse_houly_build_release_tag)
        elif GlobalOptions.reuse_private_submission_id:
            Logger.info(f"Skip-Build, Reconstruct artifacts from private-submission: {GlobalOptions.reuse_private_submission_id}")
            return BuilderInterface.PrivateBuildArtifactBuilder(target_spec, target_name,
                                                                GlobalOptions.repository,
                                                                GlobalOptions.reuse_private_submission_id)
        elif GlobalOptions.reuse_minio_storage:
            Logger.info(f"Skip-Build, Download private imfr from minio storage: {GlobalOptions.reuse_minio_storage}")
            return BuilderInterface.MinioStorageArtifactBuilder(target_spec, target_name,
                                                                GlobalOptions.repository,
                                                                GlobalOptions.reuse_minio_storage)
        else:
            Logger.info("Build in conventional-way from local ws")
            return BuilderInterface.LocalWorkspaceArtifactBuilder(target_spec, target_name)

