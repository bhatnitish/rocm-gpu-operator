#!/usr/bin/bash

#
# Copyright (c) Advanced Micro Devices, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the \"License\");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an \"AS IS\" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

function usage() {
    echo ""
    echo "Usage: $0 [options]"
    echo "          --help print help/usage information"
    echo "          --skip-kube-config"
    echo "          --secrets secrets.json file"
    echo "          --amdgpu-driver-spec <driver-version-spec>"
    echo "          --image-manifest <path-to-image-manifest>"
    echo "          --module <module-name>. Eq: test_<module_name>.py"
    echo "          --testcase <testcase-name> Eq: def test_<tc_name>"
    echo "          --testbed <path-to-testbed-yaml>"
    echo "          --debug"
    echo ""
}

IMAGE_MANIFEST="NA"
TB_YAML="NA"
SKIP_KUBE_CONFIG="NO"
SECRETS="NA"
DEPLOYMENT="k8"
TC_MODULE="ALL"
TC_NAME="ALL"
ENABLE_DEBUGGING="NA"
DRIVER_SPEC="NA"

function collect_tech_support() {
    echo "Collect test run logs"
    tar -zcf pytest_logs.tgz logs/
    ls -ltr $PWD/pytest_logs.tgz
}

function upload_reports() {

    echo "JOB_ID=${JOB_ID}"
    echo "TARGET_NAME=${TARGET_NAME}"
    echo "TARGET_ID=${TARGET_ID}"
    echo "JOB_PR=${JOB_PR}"
    if [[ ! -z "${JOB_ID}" ]] ;
    then
        echo "Using JOBD Environment variables to evaluate PR/JOB/Target"
        final_report="${TARGET_ID}.html"
        sshpass -p vm timeout 30 ssh -o LogLevel=ERROR -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no vm@10.11.18.6 "rm -rf /var/www/html/${TARGET_NAME}/${TARGET_ID}"
        sshpass -p vm timeout 30 ssh -o LogLevel=ERROR -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no vm@10.11.18.6 "mkdir -p /var/www/html/${TARGET_NAME}/${TARGET_ID}"
        sshpass -p vm timeout 30 scp -o LogLevel=ERROR -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ${PWD}/logs/k8.html vm@10.11.18.6:/var/www/html/${TARGET_NAME}/${TARGET_ID}/${final_report}

        echo "Links:"
        echo "Consolidated report       : http://10.11.18.6/${TARGET_NAME}/${TARGET_ID}/${final_report}"
        echo ""
    fi
}

function setup_pyenv() {
    if [[ -f venv/bin/activate ]] ;
    then
        echo "pyvenv is already ready"
        source venv/bin/activate &> /dev/null
    else
        echo "Setup pyenv with all required packages"
        sh scripts/prepare_env.sh &> /dev/null
        source venv/bin/activate &> /dev/null
    fi
    export PYTHONPATH=$PYTHONPATH:$PWD
}

function install_helm_tool() {
    echo "Download helm utility and install in local folder"
    if [[ -f $PWD/bin/helm ]];
    then
        echo "helm tool already downloaded"
    else
        mkdir -p $PWD/bin
        curl -fsSL -o $PWD/bin/get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
        chmod 700 $PWD/bin/get_helm.sh
        HELM_INSTALL_DIR=$PWD/bin $PWD/bin/get_helm.sh --no-sudo
    fi
    export PATH=$PATH:$PWD/bin
}

function launch_pytest() {
    setup_pyenv
    mkdir -p logs
    local test_sel=${DEPLOYMENT}
    local html_file=logs/${test_sel}.html
    local xml_file=logs/${test_sel}.xml
    if [[ "${TC_MODULE}" != "ALL" ]];
    then
        if [[ "${TC_NAME}" != "ALL" ]];
        then
            html_file=logs/${DEPLOYMENT}_${TC_MODULE}_${TC_NAME}.html
            xml_file=logs/${DEPLOYMENT}_${TC_MODULE}_${TC_NAME}.xml
            test_sel=${DEPLOYMENT}/test_${TC_MODULE}.py::test_${TC_NAME}
        else
            test_sel=${DEPLOYMENT}/test_${TC_MODULE}.py
            html_file=logs/${test_sel}.html
            xml_file=logs/${test_sel}.xml
        fi
    fi
    CMD_OPT="--verbose --show-capture=log --no-header -p no:warnings --disable-warnings"
    #CMD_OPT="--verbose --show-capture=log --no-header -p no:warnings --disable-warnings --self-contained-html"
    if [[ "${ENABLE_DEBUGGING}" == "YES" ]];
    then
        CMD_OPT+=" --pause-on-failure"
    fi
    if [[ "${SKIP_KUBE_CONFIG}" == "NO" ]];
    then
        install_helm_tool
    else
        CMD_OPT+=" --skip-kube-config --testbed ${TB_YAML}"
    fi
    if [[ "${SECRETS}" != "NA" ]];
    then
        CMD_OPT+=" --secrets-json ${SECRETS}"
    fi
    if [[ "${DRIVER_SPEC}" != "NA" ]];
    then
        CMD_OPT+=" --amdgpu-driver-spec ${DRIVER_SPEC}"
    fi
    pytest ${test_sel} --log-file=logs/${DEPLOYMENT}_test_run.log \
        --junit-xml=${xml_file} --deployment ${DEPLOYMENT} \
        --image-manifest ${IMAGE_MANIFEST} ${CMD_OPT}
        #--junit-xml=${xml_file} --html ${html_file} --deployment ${DEPLOYMENT} \
    ret=$?
    collect_tech_support
    #upload_reports
    exit $ret
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --testbed)
            TB_YAML="$2"
            shift
        ;;
        --image-manifest)
            IMAGE_MANIFEST="$2"
            shift
        ;;
	--module)
	    TC_MODULE="$2"
	    shift
	;;
	--testcase)
	    TC_NAME="$2"
	    shift
	;;
        --skip-kube-config)
            SKIP_KUBE_CONFIG="YES"
        ;;
        --secrets)
            SECRETS="$2"
            shift
        ;;
        --amdgpu-driver-spec)
            DRIVER_SPEC="$2"
            shift
        ;;
	--debug)
            ENABLE_DEBUGGING="YES"
	;;
        --help)
            usage
            exit 0
        ;;
        --*)
            echo "Unknown option $1"
            exit 1
        ;;
    esac
    shift
done

if [[ "${SKIP_KUBE_CONFIG}" == "1" ]];
then
    if [[ "${TB_YAML}" == "NA" ]];
    then
        echo "ERROR: Missing argument --testbed"
        usage
        exit 1
    fi
fi

if [[ "${IMAGE_MANIFEST}" == "NA" ]];
then
    echo "ERROR: Missing argument --image-manifest"
    usage
    exit 1
fi

launch_pytest
