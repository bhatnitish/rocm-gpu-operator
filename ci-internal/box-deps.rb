from "registry.test.pensando.io:5000/gpu-operator-build:v1.1"

run "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y podman kmod vim"

# remove existing docker
run "apt-get remove -y docker.io"

run "install -m 0755 -d /etc/apt/keyrings"

# download docker
run "curl -k -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc"
run "chmod a+r /etc/apt/keyrings/docker.asc"

run "echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu focal stable' > /etc/apt/sources.list.d/docker.list"

run "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
  && apt-get clean && rm -rf /var/lib/apt/lists/*"

copy "./daemon.json", "/etc/docker/daemon.json"

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
