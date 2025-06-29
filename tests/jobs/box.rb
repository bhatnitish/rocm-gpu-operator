from "registry.test.pensando.io:5000/pensando/nic:1.79"

user = getenv("USER")
group = getenv("GROUP_NAME")
uid = getenv("USER_UID")
gid = getenv("USER_GID")

if user == "root"
  # remove the games group as it conflicts with staff group for mac users
  run "groupdel games"

  # update user .bash_profile
  run "echo 'export GOPATH=/usr' >> /root/.bash_profile"
  run "echo 'export GOFLAGS=-mod=vendor' >> /root/.bash_profile"
  run "echo 'export PATH=/usr/local/go/bin:$PATH' >> /root/.bash_profile"
  run "echo 'export GRPC_ENABLE_FORK_SUPPORT=0' >> /root/.bash_profile"
  run "echo 'cd /usr/src/github.com/pensando/sw/nic' >> /root/.bash_profile"
  run "echo 'export LD_LIBRARY_PATH=/sw/nic/sdk/third-party/librocksdb/x86_64/lib/' >> /root/.bash_profile"

  run "localedef -i en_US -f UTF-8 en_US.UTF-8"
else
if user != ""
  # remove the games group as it conflicts with staff group for mac users
  run "groupdel games"

  # add user
  run "groupadd -g #{gid} #{group}"
  run "useradd -l -u #{uid} -g #{gid} #{user} -G docker"

  # go installs in /usr, make it world writeable
  run "chmod 777 /usr/bin"

  # update user .bash_profile
  run "echo 'export GOPATH=/usr' >> /home/#{user}/.bash_profile"
  run "echo 'export PATH=/usr/local/go/bin:$PATH' >> /home/#{user}/.bash_profile"
  run "echo 'export GOFLAGS=-mod=vendor' >> /home/#{user}/.bash_profile"
  run "echo 'export LD_LIBRARY_PATH=/sw/nic/sdk/third-party/librocksdb/x86_64/lib/' >> /home/#{user}/.bash_profile"
  run "echo 'export GRPC_ENABLE_FORK_SUPPORT=0' >> /home/#{user}/.bash_profile"
  run "echo 'sudo chown -R #{user} /sw/' >> /home/#{user}/.bash_profile"
  run "echo 'sudo chgrp -R #{user} /sw/' >> /home/#{user}/.bash_profile"
  run "echo 'cd /usr/src/github.com/pensando/sw/nic' >> /home/#{user}/.bash_profile"
  run "echo 'Defaults secure_path = /usr/local/go/bin:$PATH:/bin:/usr/sbin/' >> /etc/sudoers"

  run "echo '#{user} ALL=(root) NOPASSWD:ALL' > /etc/sudoers.d/#{user} && chmod 0440 /etc/sudoers.d/#{user}"

  run "localedef -i en_US -f UTF-8 en_US.UTF-8"
end
end

env GOPATH: "/usr"
env GOFLAGS: "-mod=vendor"
run "git config --global --add safe.directory ${GOPATH}/src/github.com/pensando/gpu-operator"

# A scratch pad file for exporting some host/workspace particulars into container, to be used for
# recording them into build packaging.
run "echo 'HOST_HOSTNAME=#{getenv("HOST_HOSTNAME")}' >> /usr/build_host_meta_data"
run "echo 'HOST_WORKSPACE=#{getenv("HOST_WORKSPACE")}' >> /usr/build_host_meta_data"

inside "/etc" do
  run "rm -f localtime"
  run "ln -s /usr/share/zoneinfo/US/Pacific localtime"
end

workdir "/gpu-operator"

copy "entrypoint.sh", "/entrypoint.sh"
run "chmod +x /entrypoint.sh"

entrypoint "/entrypoint.sh"
