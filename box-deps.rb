from "ubuntu:22.04"

run "apt-get update && apt-get install -y wget protobuf-compiler \
  curl locales ca-certificates build-essential git"
run "install -m 0755 -d /etc/apt/keyrings"

# download docker
run "curl -k -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc"
run "chmod a+r /etc/apt/keyrings/docker.asc"

run "echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu focal stable' > /etc/apt/sources.list.d/docker.list"

run "apt-get update && apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
  git && apt-get clean && rm -rf /var/lib/apt/lists/*"

copy "asset-build/daemon.json", "/etc/docker/daemon.json"

# remove old version of go
run "rm -rf /usr/local/go"

# download go1.20
run "wget https://go.dev/dl/go1.20.linux-amd64.tar.gz"
run "tar -C /usr/local/ -xzf go1.20.linux-amd64.tar.gz"

# download and install helm
run "curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3"
run "chmod 700 get_helm.sh"
run "./get_helm.sh"

# download and install helmify
run "wget https://github.com/arttor/helmify/releases/download/v0.4.13/helmify_Linux_x86_64.tar.gz"
run "tar -C /usr/local/bin/ -xzf helmify_Linux_x86_64.tar.gz"

# download and install kubectl 
run "curl -o /usr/local/bin/kubectl -LO https://dl.k8s.io/release/v1.30.0/bin/linux/amd64/kubectl"
run "chmod +x /usr/local/bin/kubectl"

if getenv("FLATTEN") != ""
  flatten
end
