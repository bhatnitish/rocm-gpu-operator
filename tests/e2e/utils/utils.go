package utils

import (
	"context"
	"fmt"
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

func CheckGpuLabel(rl v1.ResourceList) bool {
	s, ok := rl["amd.com/gpu"]
	if !ok {
		return false
	}

	if s.String() == "0" {
		return false
	}
	return true
}

func CheckHelmDeployment(cl *kubernetes.Clientset, ns string) error {
	for _, d := range []struct {
		ns, name string
	}{
		{ns: "cert-manager", name: "cert-manager"},
		{ns: "cert-manager", name: "cert-manager-cainjector"},
		{ns: "cert-manager", name: "cert-manager-webhook"},
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-controller-manager"},
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-kmm-controller"},
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-kmm-webhook-server"},
	} {
		s, err := cl.AppsV1().Deployments(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if err != nil {
			return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
		}
		if s.Status.ReadyReplicas != s.Status.Replicas {
			return fmt.Errorf("replicas not ready %v/%v status %+v", d.ns, d.name, s.Status)
		}
	}
	return nil
}

// todo:
func CheckDriver(cl *kubernetes.Clientset, ns string) error {
	return nil
}

// todo:
func VerifyRocm(cl *kubernetes.Clientset, ns string) error {
	return nil
}

func NodeLabellerName(cfgName string) string {
	return cfgName + "-node-labeller"
}
func NFDWorkerName() string {
	return "amd-gpu-operator-node-feature-discovery-worker"
}
