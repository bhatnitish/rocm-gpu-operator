#!/bin/sh

set -euo pipefail
dir=/usr/src/github.com/pensando/gpu-operator
netns=/var/run/netns

term() {
    killall dockerd
    wait
}

dockerd -s vfs &

trap term INT TERM

mkdir -p ${dir}
mkdir -p ${netns}
mount -o bind /gpu-operator ${dir}
sysctl -w vm.max_map_count=262144

exec "$@"
