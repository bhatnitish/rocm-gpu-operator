#!/bin/bash

#set -x
set -e

function usage() {
    local error_msg=$1
    echo $error_msg
    echo ""
    echo "Usage: $0 build-target-name [options]"
    echo "       --makefile {makefile name}             : Makefile to use to build, default Makefile"
    echo "       --alien-repo {repo-name}               : Pensando repo to use"
    echo "       --alien-branch {branch-name}           : Branch of pensando repo to use"
    echo "       --alien-tag {build-tag}                : CI assigned tag"
    echo "       --alien-target {target-name}           : target to build"
    echo "       --help                                 : Print this help message"
    echo ""
    echo "Additional Environment Variables:"
    echo "   a) set PRIVATE_SUBMISSION_ID={submission-id} : overrides {release-tag}"
    echo "   b) set PRIVATE_MINIO_VERSION={user-id}/{build-name}@{version} : overrides {release-tag}"
    echo ""
    echo "Examples:"
    echo "1): /gpu-operator/ci-internal/flexibuilder/build.sh build-iris-arm-elba"
    echo "2): /gpu-operator/ci-internal/flexibuilder/build.sh build-iris-arm-elba --makefile Makefile.build"
    echo ""
}

if [ "$#" -lt 1 ]; then
    usage
    exit 1
fi

BUILD_TARGET=$1
shift

ALIEN_REPO="${JOB_REPOSITORY}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --alien-repo)
      ALIEN_REPO=$2
      shift
      ;;
    --alien-target)
      ALIEN_TARGET=$2
      shift
      ;;
    --alien-branch)
      ALIEN_BRANCH_NAME=$2
      shift
      ;;
    --alien-tag)
      ALIEN_BUILD_TAG=$2
      shift
      ;;
    --makefile)
      MAKEFILE=$2
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option $1"
      usage
      exit 1
      ;;
  esac
  shift
done

CMD_ARGS=""
TARGET="NA"
OLDIFS="${IFS}"
IFS=/; for fld in $TARGET_NAME ; do
    if [[ $fld == *"build-"* ]];
    then
        TARGET=$fld
        IS="${OLDIFS}"
        break
    fi
done
IFS=$OLDIFS

if [[ ${GITHUB_LABELS} == *"CI-Use-Sanity-Build"* ]];
then
    echo "Found CI-Use-Sanity-Build label set, Use nightly image"
    CI_USE_SANITY_BUILD=1
fi

if [[ -z ${BUILD_TARGET} ]];
then
    echo "Missing build-target-name"
    usage
    exit 1
else
    if [[ "${BUILD_TARGET}" != "${TARGET}" ]];
    then
        echo ""
        echo "WARNING: Build-target mismatch with JOBD TARGET_NAME, ${BUILD_TARGET} vs ${TARGET}"
        echo ""
    fi
fi

CMD_ARGS+=" --target-name ${BUILD_TARGET}"

if [[ -z "${ALIEN_BRANCH_NAME+x}" ]];
then
    ALIEN_BRANCH_NAME=${JOB_BASE_BRANCH:="master"}
fi

if [[ -z "${ALIEN_BUILD_TAG+x}" ]];
then
    ALIEN_BUILD_TAG="latest"
fi


if [[ ! -z "${PRIVATE_SUBMISSION_ID+x}" ]];
then
    CMD_ARGS+=" --reuse-private-submission ${PRIVATE_SUBMISSION_ID}"
elif [[ ! -z "${PRIVATE_MINIO_VERSION+x}" ]];
then
    CMD_ARGS+=" --reuse-minio-version ${PRIVATE_MINIO_VERSION}"
elif [[ ! -z "${CI_USE_SANITY_BUILD+x}" ]] ;
then
    CMD_ARGS+=" --reuse-hourly-builds ${ALIEN_BUILD_TAG} --repository ${ALIEN_REPO} --branch ${ALIEN_BRANCH_NAME}"
    if [[ ! -z "${ALIEN_TARGET+x}" ]];
    then
        CMD_ARGS+=" --alien-target-name ${ALIEN_TARGET}"
    fi
    CMD_ARGS+=" --makefile "${MAKEFILE:="Makefile"}
else
    CMD_ARGS+=" --repository ${ALIEN_REPO} --makefile "${MAKEFILE:="Makefile"}
fi

echo CMD_ARGS=${CMD_ARGS}
ARGS=( $CMD_ARGS )
pip install beautifulsoup4
pip install PyYAML
time python3 $PWD/ci-internal/flexibuilder/fb.py ${ARGS[*]}
ret=$?

exit $ret

