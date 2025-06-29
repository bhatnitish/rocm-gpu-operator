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
    echo "          --testbed <path-to-testbed-yaml>"
    echo "          --image-manifest <path-to-image-manifest>"
    echo "          --module <module-name>. Eq: test_<module_name>.py"
    echo "          --testcase <testcase-name> Eq: def test_<tc_name>"
    echo "          --debug"
    echo ""
}

IMAGE_MANIFEST="NA"
TB_YAML="NA"
GPU_OPERATOR_VERSION="NA"
EXPORTER_VERSION="NA"
DEPLOYMENT="standalone"
TC_MODULE="ALL"
TC_NAME="ALL"
ENABLE_DEBUGGING="NA"

function collect_tech_support() {
    echo "Collect tech-support"
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

function launch_pytest() {
    setup_pyenv
    mkdir -p logs
    local test_sel=${DEPLOYMENT}
    local html_file=logs/${test_sel}.html
    local sml_file=logs/${test_sel}.xml
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
    CMD_OPT="--verbose --show-capture=log --no-header -p no:warnings --disable-warnings --self-contained-html"
    if [[ "${ENABLE_DEBUGGING}" == "YES" ]];
    then
        CMD_OPT="${CMD_OPT} --pause-on-failure"
    fi
    pytest ${test_sel} --log-file=logs/${DEPLOYMENT}_test_run.log \
        --junit-xml=${xml_file} --html ${html_file} --testbed ${TB_YAML} --deployment ${DEPLOYMENT} \
        --image-manifest ${IMAGE_MANIFEST} ${CMD_OPT}
    ret=$?
    collect_tech_support
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

if [[ "${TB_YAML}" == "NA" ]];
then
    echo "ERROR: Missing argument --testbed"
    usage
    exit 1
fi

if [[ "${IMAGE_MANIFEST}" == "NA" ]];
then
    echo "ERROR: Missing argument --image-manifest"
    usage
    exit 1
fi

launch_pytest
