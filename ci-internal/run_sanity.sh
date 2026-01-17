#!/bin/bash

#set -x

function usage() {
    echo ""
    echo "Usage: $0 [options]"
    echo "          --help print help/usage information"
    echo "          --deployment <deployment> Eg: k8, openshift, standalone"
    echo "          --app <app-name> Eg: gpu-operator, exporter, network-operator, debian, docker"
    echo "          --type <selection: sanity|compat>"
    echo "          --registry <selection: local|master|global>"
    echo "          --testbed /path/to/testbed.json, default /warmd.json"
    echo "          --amdgpu-driver <selection: inbox|deviceconfig, default deviceconfig"
    echo "          --seed-image-manifest <path-to-seed-image-manifest>"
    echo ""
}

LOCAL_REGISTRY_PORT="5000"
REGISTRY_SELECTION="local"
TESTBED_JSON="/warmd.json"
DEPLOYMENT="NA"
AMDGPU_DRIVER="deviceconfig"
GEN_IMAGE_MANIFEST="/tmp/images.yaml"
SEED_IMAGE_MANIFEST="/gpu-operator/ci-internal/sanity-images.yml"
GLOBAL_REGISTRY="registry.test.pensando.io:5000"
TYPE="NA"
APP_NAME="NA"

REGISTRY=""

function collect_logs() {
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
        sshpass -p vm timeout 30 scp -o LogLevel=ERROR -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ${PWD}/logs/${DEPLOYMENT}/${APP_NAME}.html vm@10.11.18.6:/var/www/html/${TARGET_NAME}/${TARGET_ID}/${final_report}

        echo "Links:"
        echo "Consolidated report       : http://10.11.18.6/${TARGET_NAME}/${TARGET_ID}/${final_report}"
        echo ""
    fi
}

function start_registry() {
    # Maximum number of retries
    local MAX_RETRIES=20
    # Retry counter
    local RETRY_COUNT=0

    # Start Docker if START_DOCKER is set
    if [ ! -z "$START_DOCKER" ]; then
        echo "START_DOCKER is set. Attempting to start Docker..."
        dockerd -s vfs &
        sleep 2 # Give some time for the daemon to potentially start
    fi

    # Check if a `docker run` command succeeds
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        # start local docker registry for sanity ci test
        docker run -d -p $LOCAL_REGISTRY_PORT:$LOCAL_REGISTRY_PORT --name registry --restart always registry.test.pensando.io:5000/pensando/registry:2
        if [ $? -eq 0 ]; then
            echo "Registry is ready, mark it insecure for pushing images"
            DOCKER_CONFIG_FILE="/etc/docker/daemon.json"
            sudo jq --arg host_ip "$HOST_IP" --arg reg_port "$LOCAL_REGISTRY_PORT"   '.["insecure-registries"] += ["\($host_ip):\($reg_port)"]' "$DOCKER_CONFIG_FILE" > /tmp/daemon.json.tmp && sudo mv /tmp/daemon.json.tmp "$DOCKER_CONFIG_FILE"
            sudo pkill -HUP dockerd
            sleep 30
            return
        fi

        ((RETRY_COUNT++))
        echo "Registry is not ready. Retrying... ($RETRY_COUNT/$MAX_RETRIES)"
        sleep 2
    done

    echo "Docker is not ready after $MAX_RETRIES attempts."
    exit 1
}

function setup_registry() {
    echo ""
    if [[ ${REGISTRY_SELECTION} == "local" ]];
    then
        echo "Setting up local registry"
        start_registry
        REGISTRY="${HOST_IP}:${LOCAL_REGISTRY_PORT}"
    elif [[ ${REGISTRY_SELECTION} == "master" ]];
    then
        echo "Extract master node details, setup registry : TODO"
        exit 1
    elif [[ ${REGISTRY_SELECTION} == "global" ]];
    then
        REGISTRY=${GLOBAL_REGISTRY}
    else
        echo "FATAL ERROR: Invalid registry-selection - ABORT"
        exit 1
    fi
    echo ""
}

function load_images() {
    echo ""
    echo "Run k8_jobd_ctl to "
    echo "    (1) load images into registry : ${REGISTRY}"
    echo "    (2) generate image-manifest-yaml for test"
    echo ""

    /gpu-operator/ci-internal/k8_jobd_ctl.py image --load-images --seed-image-manifest $SEED_IMAGE_MANIFEST --registry $REGISTRY --image-manifest $GEN_IMAGE_MANIFEST --testbed $TESTBED_JSON --setup-insecure-registry --target $DEPLOYMENT
    RET=$?
    if [[ "$RET" != "0" ]]
    then
        echo "FATAL ERROR: Failed load images and generate image-manfiest-yaml "
        exit $RET
    fi
    echo ""

    echo ""
    echo "Run k8_jobd_ctl to "
    echo "    (1) update insecure-registry for each node in the cluster"
    echo ""
    /gpu-operator/ci-internal/k8_jobd_ctl.py image --seed-image-manifest $SEED_IMAGE_MANIFEST --registry $REGISTRY --testbed $TESTBED_JSON --setup-insecure-registry --target $DEPLOYMENT
    RET=$?
    if [[ "$RET" != "0" ]]
    then
        echo "FATAL ERROR: Failed to setup insecure-registry at each node in the k8 cluster"
        exit $RET
    fi
    echo ""

    echo ""
    echo "Run k8_jobd_ctl to "
    echo "    (1) pull images for each worker node in the cluster"
    echo ""
    /gpu-operator/ci-internal/k8_jobd_ctl.py image --seed-image-manifest $SEED_IMAGE_MANIFEST --registry $REGISTRY --testbed $TESTBED_JSON --pull-images --target $DEPLOYMENT
    RET=$?
    if [[ "$RET" != "0" ]]
    then
        echo "WARNING : Failed to pull images on each worker node(s)"
    fi
    echo ""
}

function prepare_cluster() {
    echo "Run k8_jobd_ctl to "
    echo "    (1) reboot worker-nodes"
    echo "    (2) fetch kube-config"
    echo ""
    /gpu-operator/ci-internal/k8_jobd_ctl.py testbed --testbed $TESTBED_JSON --reboot-workers --fetch-kube-config
    RET=$?
    if [[ "$RET" != "0" ]]
    then
        echo "FATAL ERROR: Failed to reboot-worker nodes and/or fetch kube-config from master"
        exit $RET
    fi
    echo ""
    jq .Instances[].RawJSON ${TESTBED_JSON} | tee /gpu-operator/tests/pytests/testbed.json
}

function launch_pytest_k8() {
    echo "Launching k8_test_launcher"
    local SECRETS="/tmp/secrets.json"
    curl -s http://pm.test.pensando.io/systest/gpu-operator-secrets/secrets.json -o ${SECRETS}
    CMD_OPTS=" --image-manifest ${GEN_IMAGE_MANIFEST} --secrets ${SECRETS} --app ${APP_NAME}"
    if [[ "${AMDGPU_DRIVER}" == "inbox" ]];
    then
        CMD_OPTS+=" --amdgpu-driver-spec lib/files/amd-inbox-driver-spec.json"
    elif [[ "${AMDGPU_DRIVER}" == "deviceconfig" ]];
    then
        CMD_OPTS+=" --amdgpu-driver-spec lib/files/amd-deviceconfig-default-driver-spec.json"
    fi
    echo "Running k8 pytests with CMD_OPTS: ${CMD_OPTS}"
    if [[ "${APP_NAME}" == "gpu-operator" ]];
    then
        cp /gpu-operator/tools/techsupport_dump.sh /gpu-operator/tests/pytests/gpu_operator_techsupport_dump.sh
        chmod +x /gpu-operator/tests/pytests/gpu_operator_techsupport_dump.sh
        export TECH_SUPPORT_TOOL=/gpu-operator/tests/pytests/gpu_operator_techsupport_dump.sh
    fi
    if [[ "${APP_NAME}" == "exporter" ]];
    then
        cp /device-metrics-exporter/tools/techsupport_dump.sh /gpu-operator/tests/pytests/exporter_techsupport_dump.sh
        chmod +x /gpu-operator/tests/pytests/exporter_techsupport_dump.sh
        export TECH_SUPPORT_TOOL=/gpu-operator/tests/pytests/exporter_techsupport_dump.sh
    fi
    /gpu-operator/tests/pytests/k8_test_launcher.sh ${CMD_OPTS}
    RET=$?
    echo ""
    /gpu-operator/ci-internal/k8_jobd_ctl.py report --show --testbed $TESTBED_JSON
    echo ""
    upload_reports
    collect_logs
    if [[ "$RET" != "0" ]]
    then
        exit $RET
    fi
}

function launch_pytest_openshift() {
    echo "Launching oc_test_launcher"
    local SECRETS="/tmp/secrets.json"
    curl -s http://pm.test.pensando.io/systest/gpu-operator-secrets/secrets.json -o ${SECRETS}
    CMD_OPTS=" --image-manifest ${GEN_IMAGE_MANIFEST} --secrets ${SECRETS} --app ${APP_NAME}"
    CMD_OPTS+=" --amdgpu-driver-spec lib/files/amd-deviceconfig-default-driver-spec.json"
    echo "Running openshift pytests with CMD_OPTS: ${CMD_OPTS}"
    TECH_SUPPORT_TOOL=/gpu-operator/tools/techsupport_dump.sh /gpu-operator/tests/pytests/oc_test_launcher.sh ${CMD_OPTS}
    RET=$?
    echo ""
    /gpu-operator/ci-internal/k8_jobd_ctl.py report --show --testbed $TESTBED_JSON
    echo ""
    upload_reports
    collect_logs
    if [[ "$RET" != "0" ]]
    then
        exit $RET
    fi
}

function launch_pytest_standalone() {
    echo "Launching standalone_test_launcher"
    local SECRETS="/tmp/secrets.json"
    curl -s http://pm.test.pensando.io/systest/gpu-operator-secrets/secrets.json -o ${SECRETS}
    CMD_OPTS=" --image-manifest ${GEN_IMAGE_MANIFEST} --secrets ${SECRETS} --app ${APP_NAME}"
    CMD_OPTS+=" --amdgpu-driver-spec lib/files/amd-deviceconfig-default-driver-spec.json"
    CMD_OPTS+=" --testbed /gpu-operator/tests/pytests/testbed.json"
    echo "Running standalone pytests with CMD_OPTS: ${CMD_OPTS}"
    /gpu-operator/tests/pytests/standalone_test_launcher.sh ${CMD_OPTS}
    RET=$?
    echo ""
    /gpu-operator/ci-internal/k8_jobd_ctl.py report --show --testbed $TESTBED_JSON
    RPT=$?
    echo ""
    upload_reports
    collect_logs
    if [[ "$RET" != "0" ]]
    then
        exit $RET
    fi
    exit $RPT
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --deployment)
            DEPLOYMENT="$2"
            shift
        ;;
        --app)
            APP_NAME="$2"
            shift
        ;;
        --type)
            TYPE="$2"
            shift
        ;;
        --registry)
            REGISTRY_SELECTION="$2"
            shift
        ;;
        --testbed)
            TESTBED_JSON="$2"
            shift
        ;;
        --amdgpu-driver)
            AMDGPU_DRIVER="$2"
            shift
        ;;
        --seed-image-manifest)
            SEED_IMAGE_MANIFEST="$2"
            shift
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

function main() {
    if [[ "${TYPE}" == "sanity" ]];
    then
        echo "Running sanity-setup"
        setup_registry
        load_images
        echo "Completed setting up registry and loading images"
    elif [[ "${TYPE}" == "compat" ]];
    then
        echo "Running compat-setup"
    else
        echo "Invalid target type : ${TYPE} or is unspecified"
        usage
        exit 1
    fi
    prepare_cluster
    echo "Completed setting up environment for ${TYPE}-run, launching pytest"
    if [[ "${DEPLOYMENT}" == "k8" ]];
    then
        launch_pytest_k8
    elif [[ "${DEPLOYMENT}" == "openshift" ]];
    then
        launch_pytest_openshift
    elif [[ "${DEPLOYMENT}" == "standalone" ]];
    then
        launch_pytest_standalone
    else
        echo "Invalid selection for DEPLOYMENT=${DEPLOYMENT}"
        exit 1
    fi
}

main
