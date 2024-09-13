package e2e

import (
	"github.com/pensando/gpu-operator/tests/e2e/client"
	"k8s.io/client-go/kubernetes"
)

// E2ESuite e2e config
type E2ESuite struct {
	clientSet            *kubernetes.Clientset
	dClient              *client.DeviceConfigClient
	cfgName              string
	registry             string
	helmChart            string
	ns                   string
	kubeconfig           string
	clusterType          string
	defaultDriverVersion string
	openshift            bool
}
