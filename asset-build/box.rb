from "registry.test.pensando.io:5000/pensando/nic:1.76"

inside "/etc" do
  run "rm localtime"
  run "ln -s /usr/share/zoneinfo/US/Pacific localtime"
end

env GOFLAGS: "-mod=vendor"
env GRPC_ENABLE_FORK_SUPPORT: "0"
run "curl -o /usr/bin/asset-pull http://pm.test.pensando.io/tools/asset-pull"
run "chmod +x /usr/bin/asset-pull"
run "curl -o /usr/bin/asset-push http://pm.test.pensando.io/tools/asset-push"
run "chmod +x /usr/bin/asset-push"
copy "asset-build/gpuoperator-asset-push.sh", "/gpuoperator-asset-push.sh"
run "chmod +x /gpuoperator-asset-push.sh"
copy "asset-build/entrypoint.sh", "/entrypoint.sh"
run "chmod +x /entrypoint.sh"

workdir "/gpu-operator"
entrypoint "/entrypoint.sh"
