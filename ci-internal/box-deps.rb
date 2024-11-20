from "ubuntu:22.04"

run "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y wget protobuf-compiler \
  curl locales ca-certificates build-essential git podman sudo kmod vim"
run "install -m 0755 -d /etc/apt/keyrings"

# download docker
run "curl -k -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc"
run "chmod a+r /etc/apt/keyrings/docker.asc"

run "echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu focal stable' > /etc/apt/sources.list.d/docker.list"

run "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
  && apt-get clean && rm -rf /var/lib/apt/lists/*"

copy "./daemon.json", "/etc/docker/daemon.json"

# remove old version of go
run "rm -rf /usr/local/go"

# download go1.20
run "wget https://go.dev/dl/go1.20.14.linux-amd64.tar.gz && tar -C /usr/local/ -xzf go1.20.14.linux-amd64.tar.gz && rm go1.20.14.linux-amd64.tar.gz"

# download and install helm
run "curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 && chmod 700 get_helm.sh && ./get_helm.sh"

# download and install helmify
run "curl -sSL https://github.com/arttor/helmify/releases/download/v0.4.13/helmify_Linux_x86_64.tar.gz | tar xz -C /usr/local/bin/"

run "curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key |
        gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg"

run "echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.31/deb/ /' |
        tee /etc/apt/sources.list.d/kubernetes.list "

run "curl -fsSL https://pkgs.k8s.io/addons:/cri-o:/stable:/v1.31/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/cri-o-apt-keyring.gpg"

run "echo 'deb [signed-by=/etc/apt/keyrings/cri-o-apt-keyring.gpg] https://pkgs.k8s.io/addons:/cri-o:/stable:/v1.31/deb/ /' | tee /etc/apt/sources.list.d/cri-o.list"


run "apt update && apt install cri-o kubelet kubeadm -y"

run "curl -o /usr/local/bin/kubectl -LO 'https://dl.k8s.io/release/v1.30.4/bin/linux/amd64/kubectl' | chmod +x /usr/local/bin/kubectl"

# download and install nerdctl for kind installation
#run "curl -sSL https://github.com/containerd/nerdctl/releases/download/v2.0.0/nerdctl-2.0.0-linux-amd64.tar.gz | tar xzf -C /usr/local/bin && chmod +x /usr/local/bin/nerdctl"

# install kind
run "wget -O/usr/local/bin/kind https://kind.sigs.k8s.io/dl/v0.25.0/kind-linux-amd64 && chmod +x /usr/local/bin/kind"

if getenv("FLATTEN") != ""
  flatten
end
