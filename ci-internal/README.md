## Container/CI tasks

### Prerequisite
1. OS: ubuntu 22.04
2. Docker: default docker version is higher, need install lower version to be supported. Run `make install-docker`
3. Edit `/etc/docker/daemon.json` to have the following content:

```json
{
    "insecure-registries" : ["srv1.pensando.io:5000", "registry.test.pensando.io:5000"],
    "ipv6": true,
    "fixed-cidr-v6": "2001:db8:1::/64"
}
```

* restart docker (`sudo systemctl restart docker` usually)


4. Run `mount | grep cgroup`, if output like below, you can skip this step.
```
$ mount | grep cgroup
tmpfs on /sys/fs/cgroup type tmpfs (ro,nosuid,nodev,noexec,size=4096k,nr_inodes=1024,mode=755,inode64)
cgroup2 on /sys/fs/cgroup/unified type cgroup2 (rw,nosuid,nodev,noexec,relatime)
cgroup on /sys/fs/cgroup/systemd type cgroup (rw,nosuid,nodev,noexec,relatime,xattr,name=systemd)
cgroup on /sys/fs/cgroup/misc type cgroup (rw,nosuid,nodev,noexec,relatime,misc)
cgroup on /sys/fs/cgroup/pids type cgroup (rw,nosuid,nodev,noexec,relatime,pids)
cgroup on /sys/fs/cgroup/rdma type cgroup (rw,nosuid,nodev,noexec,relatime,rdma)
cgroup on /sys/fs/cgroup/cpu,cpuacct type cgroup (rw,nosuid,nodev,noexec,relatime,cpu,cpuacct)
cgroup on /sys/fs/cgroup/net_cls,net_prio type cgroup (rw,nosuid,nodev,noexec,relatime,net_cls,net_prio)
cgroup on /sys/fs/cgroup/perf_event type cgroup (rw,nosuid,nodev,noexec,relatime,perf_event)
cgroup on /sys/fs/cgroup/devices type cgroup (rw,nosuid,nodev,noexec,relatime,devices)
cgroup on /sys/fs/cgroup/memory type cgroup (rw,nosuid,nodev,noexec,relatime,memory)
cgroup on /sys/fs/cgroup/hugetlb type cgroup (rw,nosuid,nodev,noexec,relatime,hugetlb)
cgroup on /sys/fs/cgroup/freezer type cgroup (rw,nosuid,nodev,noexec,relatime,freezer)
cgroup on /sys/fs/cgroup/blkio type cgroup (rw,nosuid,nodev,noexec,relatime,blkio)
cgroup on /sys/fs/cgroup/cpuset type cgroup (rw,nosuid,nodev,noexec,relatime,cpuset)
```

If output like below, please follow below steps:
```
vm@ubuntu2204:~$ mount | grep cgroup
cgroup2 on /sys/fs/cgroup type cgroup2 (rw,nosuid,nodev,noexec,relatime,nsdelegate,memory_recursiveprot)
```
1. edit `/etc/default/grub`, and make sure `systemd.unified_cgroup_hierarchy=0` is added at line
`GRUB_CMDLINE_LINUX_DEFAULT="quiet systemd.unified_cgroup_hierarchy=0"`
2. after save, run `sudo update-grub`
3. reboot vm
4. after reboot, run `mount | grep cgroup` again, it should have both `cgroup` and `cgroup2`


### Doing development in the CI/Container environment

**NOTE**: There are several tasks in the
[Makefile](https://github.com/pensando/gpu-operator/blob/main/ci-internal/Makefile)
which you can read for additional information should this documentation be lacking.

To get started, you can follow below steps to jump into docker based development environment.
This need to be done at root of cloned workspace
1. cd ci-internal
2. make docker/shell
3. after inside the shell, cd /gpu-operator/ci-internal
4. run ./deploy_k8s_by_kind.sh.
5. now the local k8s is started, and token are saved in ~/.kube folder inside container

The first time you do this it will:
* pull a large docker image
* install the [box](https://box-builder.github.io/box) tool (and require root
  to install it if it doesn't exist)
* build a temporary image for you to use and run a shell inside of it

Note that in any situation, your directories are bind mounted (somewhat like VM
file sharing) into the container so you are able to work both inside and
outside of the container. e.g., you can vim or emacs or whatever you prefer
outside the container and your changes will be reflected inside too. Likewise
in the opposite direction.

Because of this, and the UID differences between inside and outside of the
container, you may run into permission issues with your build artifacts
specifically.
