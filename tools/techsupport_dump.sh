#!/bin/bash
# collect tech support logs
# usage:
#    techsupport_dump.sh node-name/all
#
set -e

TECH_SUPPORT_FILE=techsupport-$(date "+%F_%T" | sed -e 's/:/-/g')
DEFAULT_RESOURCES="nodes pods daemonsets deployments events"
NS_RESOURCES="modules deviceconfig nodemodulesconfig configmap"
OUTPUT_FORMAT="json"
WIDE=""
red='\033[0;31m'
green='\033[0;32m'
clr='\033[0m'

usage() {
	echo -e "$0 [-w] [-o yaml/json] [-k kubeconfig] <node-name/all>" 
	echo -e "   [-w] wide option "
	echo -e "   [-o yaml/json] output format, yaml/json(default)"
	echo -e "   [-k kubeconfig] path to kubeconfig(default ~/.kube/config)"
	exit 0
}

log() {
	echo -e "${green}[$(date +%F_%T) techsupport]$* ${clr}"
}

die() {
	echo -e "${red}$* ${clr}" && exit 1
}

while getopts who:k: opt; do
	case ${opt} in
	w)
		WIDE="-o wide"
		;;
	o)
		OUTPUT_FORMAT="${OPTARG}"
		;;
	k)
		KUBECONFIG="--kubeconfig ${OPTARG}"
		;;
	h)
		usage
		;;
	?)
		usage
		;;
	esac
done
shift "$((OPTIND - 1))"
NODES=$@
KUBECTL="kubectl ${KUBECONFIG}"

[ -z "${NODES}" ] && die "node-name/all required"
rm -rf ${TECH_SUPPORT_FILE}
mkdir -p ${TECH_SUPPORT_FILE}
${KUBECTL} version >${TECH_SUPPORT_FILE}/kubectl.txt || die "${KUBECTL} failed"

NFD_NS=$(${KUBECTL} get pods -A | grep "nfd-master\|node-feature-discovery-master" | awk '{ print $1 }' | sort -u | head -n1)
KMM_NS=$(${KUBECTL} get pods -A | grep "kmm-" | awk '{ print $1 }' | sort -u | head -n1)
AMD_NS=$(${KUBECTL} get pods -A | grep "amd-gpu" | awk '{ print $1 }' | sort -u | head -n1)
POD_NS=$(echo $NFD_NS $KMM_NS $AMD_NS | tr ' ' '\n' | sort -u)
echo -e "NFD_NS $NFD_NS \nKMM_NS $KMM_NS \nAMD_NS $AMD_NS" >${TECH_SUPPORT_FILE}/namespace.txt
echo "POD_NS $POD_NS" | tr '\n' ',' >>${TECH_SUPPORT_FILE}/namespace.txt

for resource in ${DEFAULT_RESOURCES}; do
	log "${resource}"
	${KUBECTL} get -A ${resource} ${WIDE} >${TECH_SUPPORT_FILE}/${resource}.txt
	${KUBECTL} describe -A ${resource} >>${TECH_SUPPORT_FILE}/${resource}.txt
	${KUBECTL} get -A ${resource} -o ${OUTPUT_FORMAT} >${TECH_SUPPORT_FILE}/${resource}.${OUTPUT_FORMAT}
done

KNS="${KUBECTL} -n ${AMD_NS}"
for resource in ${NS_RESOURCES}; do
	log "${AMD_NS}/${resource}"
	${KNS} get ${resource} ${WIDE} >${TECH_SUPPORT_FILE}/${AMD_NS}_${resource}.txt
	${KNS} describe ${resource} >>${TECH_SUPPORT_FILE}/${AMD_NS}_${resource}.txt
	${KNS} get ${resource} -o ${OUTPUT_FORMAT} >${TECH_SUPPORT_FILE}/${AMD_NS}_${resource}.${OUTPUT_FORMAT}
done

# logs
if [ "${NODES}" == "all" ]; then
	NODES=$(${KUBECTL} get nodes -o name)
fi

for lnode in ${NODES}; do
	node=$(basename ${lnode})
	mkdir -p ${TECH_SUPPORT_FILE}/${node}
	log "logs from ${node}"
	for ns in ${POD_NS}; do
		KNS="${KUBECTL} -n ${ns}"
		${KNS} get pods -o name --field-selector spec.nodeName=${node} >${TECH_SUPPORT_FILE}/${node}/${ns}_pods.txt
		${KUBECTL} describe nodes ${node} >${TECH_SUPPORT_FILE}/${node}/${node}.txt
		pods=$(${KNS} get pods -o name --field-selector spec.nodeName=$node)
		for lpod in ${pods}; do
			pod=$(basename ${lpod})
			log "   pod log ${ns}/${pod}"
			${KNS} logs "${pod}" >${TECH_SUPPORT_FILE}/${node}/${ns}_${pod}.txt
			${KNS} logs -p "${pod}" --tail 1 >/dev/null 2>&1 && ${KNS} logs -p "${pod}" >${TECH_SUPPORT_FILE}/${node}/${ns}_${pod}_previous.txt
		done
	done

	${KUBECTL} get pods -o name --field-selector spec.nodeName=${node} | grep node-debugger-${node} | xargs -r -n1 ${KUBECTL} delete
	${KUBECTL} debug node/${node} -q --profile=sysadmin --image=busybox -- sh -c "sleep infinity"
	dbgpod=$(${KUBECTL} get pods -o name --field-selector spec.nodeName=${node} | grep node-debugger-${node})
	# wait for the debug pod
	${KUBECTL} wait --for=condition=Ready=true ${dbgpod} >/dev/null
	log "   lsmod"
	${KUBECTL} exec -it ${dbgpod} -- sh -c "lsmod | grep amdgpu || true" >${TECH_SUPPORT_FILE}/${node}/lsmod.txt
	log "   dmesg"
	${KUBECTL} exec -it ${dbgpod} -- sh -c "dmesg || true" >${TECH_SUPPORT_FILE}/${node}/dmesg.txt
	${KUBECTL} delete ${dbgpod} >/dev/null
done
tar cfz ${TECH_SUPPORT_FILE}.tgz ${TECH_SUPPORT_FILE} && rm -rf ${TECH_SUPPORT_FILE} && log "${TECH_SUPPORT_FILE}.tgz is ready"
