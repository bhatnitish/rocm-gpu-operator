#!/bin/bash
# collect tech support logs
# usage:
#    techsupport_dump.sh node-name/all
#
set -e

KUBECTL=kubectl
TECH_SUPPORT_FILE=techsupport-$(date "+%F_%T" | sed -e 's/:/-/g')
DEFAULT_RESOURCES="nodes pods daemonsets deployments events"
NS_RESOURCES="modules deviceconfig nodemodulesconfig configmap"
NS=kube-amd-gpu
KNS="${KUBECTL} -n ${NS}"
OUTPUT_FORMAT="json"
WIDE=""
red='\033[0;31m'
green='\033[0;32m'
clr='\033[0m'

usage() {
	echo -e "$0 -n <node-name/all>" && exit 0
}

log() {
	echo -e "${green}[$(date +%F_%T) techsupport]$* ${clr}"
}

die() {
	echo -e "${red}$* ${clr}" && exit 1
}

while getopts who: opt; do
	case ${opt} in
	w)
		WIDE="-o wide"
		;;
	o)
		OUTPUT_FORMAT="${OPTARG}"
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

[ -z "${NODES}" ] && die "node-name/all required"
rm -rf ${TECH_SUPPORT_FILE}
mkdir -p ${TECH_SUPPORT_FILE}
${KUBECTL} version >${TECH_SUPPORT_FILE}/kubectl.txt || die "${KUBECTL} failed"

for resource in ${DEFAULT_RESOURCES}; do
	log "${resource}"
	${KUBECTL} get -A ${resource} ${WIDE} >${TECH_SUPPORT_FILE}/${resource}.txt
	${KUBECTL} describe -A ${resource} >>${TECH_SUPPORT_FILE}/${resource}.txt
	${KUBECTL} get -A ${resource} -o ${OUTPUT_FORMAT} >${TECH_SUPPORT_FILE}/${resource}.${OUTPUT_FORMAT}
done

for resource in ${NS_RESOURCES}; do
	log "${resource}"
	${KNS} get ${resource} ${WIDE} >${TECH_SUPPORT_FILE}/${resource}.txt
	${KNS} describe ${resource} >>${TECH_SUPPORT_FILE}/${resource}.txt
	${KNS} get ${resource} -o ${OUTPUT_FORMAT} >${TECH_SUPPORT_FILE}/${resource}.${OUTPUT_FORMAT}
done

# logs
if [ "${NODES}" == "all" ]; then
	NODES=$(${KUBECTL} get nodes -o name)
fi

for lnode in ${NODES}; do
	node=$(basename ${lnode})
	mkdir -p ${TECH_SUPPORT_FILE}/${node}
	log "logs from ${node}"
	${KNS} get pods -o name --field-selector spec.nodeName=${node} >${TECH_SUPPORT_FILE}/${node}/pods.txt
	${KUBECTL} describe nodes ${node} >${TECH_SUPPORT_FILE}/${node}/${node}.txt
	pods=$(${KNS} get pods -o name --field-selector spec.nodeName=$node)
	for lpod in ${pods}; do
		pod=$(basename ${lpod})
		log "   pod log ${node}/${pod}"
		${KNS} logs "${pod}" >${TECH_SUPPORT_FILE}/${node}/${pod}.txt
		log "   pod log ${node}/${pod}"
		${KNS} logs -p "${pod}" --tail 1 > /dev/null 2>&1 && ${KNS} logs -p "${pod}" >${TECH_SUPPORT_FILE}/${node}/${pod}_previous.txt 
	done

	$(${KUBECTL} get pods -o name --field-selector spec.nodeName=${node} | grep node-debugger-${node} >/dev/null) &&
		$(${KUBECTL} get pods -o name --field-selector spec.nodeName=${node} | grep node-debugger-${node} | xargs -n1 ${KUBECTL} delete)
	${KUBECTL} debug node/${node} -q --profile=sysadmin --image=busybox -- sh -c "sleep infinity"
	dbgpod=$(${KUBECTL} get pods -o name --field-selector spec.nodeName=${node} | grep node-debugger-${node})
	# wait for the debug pod
	${KUBECTL} wait --for=condition=Ready=true ${dbgpod} >/dev/null
	log "   lsmod"
	${KUBECTL} exec -it ${dbgpod} -- sh -c "lsmod | grep amdgpu" >${TECH_SUPPORT_FILE}/${node}/lsmod.txt
	log "   dmesg"
	${KUBECTL} exec -it ${dbgpod} -- sh -c "dmesg" >${TECH_SUPPORT_FILE}/${node}/dmesg.txt
	${KUBECTL} delete ${dbgpod} >/dev/null
done
tar cfz ${TECH_SUPPORT_FILE}.tgz ${TECH_SUPPORT_FILE} && rm -rf ${TECH_SUPPORT_FILE} && log "${TECH_SUPPORT_FILE}.tgz is ready"
