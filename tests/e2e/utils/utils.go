package utils

import (
	"context"
	"fmt"
	"github.com/pensando/gpu-operator/internal/kmmmodule"
	appsv1 "k8s.io/api/apps/v1"
	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/discovery"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"log"
	"os/exec"
	"time"
)

const ClusterTypeOpenShift = "openshift"
const ClusterTypeK8s = "kubernetes"
var kubectl = "kubectl"

func init() {
	c, err := exec.LookPath("kubectl")
	if err != nil {
		log.Fatalf("failed to find kubectl %v", err)
	}
	kubectl = c
}

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

func CheckHelmOCDeployment(cl *kubernetes.Clientset, ns string) error {
	for _, d := range []struct {
		ns, name string
	}{
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-controller-manager"},
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-kmm-controller"},
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-kmm-webhook-server"},
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-nfd-controller-manager"},
		{ns: "kube-amd-gpu", name: "nfd-master"},
	} {
		s, err := cl.AppsV1().Deployments(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if err != nil {
			return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
		}
		if s.Status.Replicas == 0 || s.Status.ReadyReplicas != s.Status.Replicas {
			return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
		}
	}

	for _, d := range []struct {
		ns, name string
	}{
		{ns: "kube-amd-gpu", name: "nfd-worker"},
	} {
		s, err := cl.AppsV1().DaemonSets(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if err != nil {
			return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
		}
		if s.Status.DesiredNumberScheduled == 0 || s.Status.DesiredNumberScheduled != s.Status.NumberReady {
			return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
		}
	}
	return nil
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
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-node-feature-discovery-gc"},
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-node-feature-discovery-master"},
	} {
		s, err := cl.AppsV1().Deployments(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if err != nil {
			return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
		}
		if s.Status.Replicas == 0 || s.Status.ReadyReplicas != s.Status.Replicas {
			return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
		}
	}

	for _, d := range []struct {
		ns, name string
	}{
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-node-feature-discovery-worker"},
	} {
		s, err := cl.AppsV1().DaemonSets(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if err != nil {
			return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
		}
		if s.Status.DesiredNumberScheduled == 0 || s.Status.DesiredNumberScheduled != s.Status.NumberReady {
			return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
		}
	}
	return nil
}

var rocmLabel = map[string]string{
	"e2e": "true",
}
var rocmDs = "e2e-rocm"

func DeployRocmPods(ctx context.Context, cl *kubernetes.Clientset) error {
	err := CreateDaemonset(ctx, cl, v1.NamespaceDefault, rocmDs, "rocm/tensorflow:latest", rocmLabel)
	if err != nil {
		return fmt.Errorf("failed to create e2e pods %v", err)
	}

	if err := Retry(func() error {
		its, err := cl.CoreV1().Pods("").List(ctx, metav1.ListOptions{LabelSelector: kmmmodule.MapToLabelSelector(rocmLabel)})
		if err != nil {
			return fmt.Errorf("failed to list pods %v", err)
		}
		for _, p := range its.Items {
			for _, c := range p.Status.ContainerStatuses {
				if !c.Ready {
					return fmt.Errorf("pod %v/%v is not ready(%v)", p.Name, c.Name, c.Ready)

				}
			}
		}
		return nil
	}, time.Minute*5, time.Second*5); err != nil {
		return fmt.Errorf("pods not ready %v", err)
	}
	return nil
}

func ListRocmPods(ctx context.Context, cl *kubernetes.Clientset) ([]string, error) {
	pods := []string{}
	its, err := cl.CoreV1().Pods("").List(ctx, metav1.ListOptions{LabelSelector: kmmmodule.MapToLabelSelector(rocmLabel)})
	if err != nil {
		return pods, err
	}
	for _, p := range its.Items {
		pods = append(pods, p.Name)
	}
	return pods, err
}

func DelRocmPods(ctx context.Context, cl *kubernetes.Clientset) error {
	return DelDaemonset(cl, v1.NamespaceDefault, rocmDs)
}

func GetRocmInfo(name string) (string, error) {
	return ExecPodCmd("rocm-smi --alldevices -i | grep Name", v1.NamespaceDefault, name)
}

func ListGpuDrivers(name string) (string, error) {
	return ExecPodCmd("lsmod | grep amdgpu", v1.NamespaceDefault, name)
}

func GetGpuDriverVersion(name string) (string, error) {
	return ExecPodCmd("rocm-smi --showdriverversion | grep Driver", v1.NamespaceDefault, name)
}

func CreateDaemonset(ctx context.Context, cl *kubernetes.Clientset, ns string, name string, image string, matchLabels map[string]string) error {
	dsCli := cl.AppsV1().DaemonSets(ns)
	ds := &appsv1.DaemonSet{
		ObjectMeta: metav1.ObjectMeta{
			Name: name,
		},
		Spec: appsv1.DaemonSetSpec{
			Selector: &metav1.LabelSelector{
				MatchLabels: matchLabels,
			},

			Template: v1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: matchLabels,
				},
				Spec: v1.PodSpec{
					Containers: []v1.Container{
						{
							Name:    name,
							Image:   image,
							Command: []string{"sh", "-c", "--"},
							Args:    []string{"sleep infinity"},
							Resources: v1.ResourceRequirements{
								Limits: v1.ResourceList{
									"amd.com/gpu": resource.MustParse("1"),
								},

								Requests: v1.ResourceList{
									"amd.com/gpu": resource.MustParse("1"),
								},
							},
						},
					},
				},
			},
		},
	}

	// Create Deployment
	_, err := dsCli.Create(context.TODO(), ds, metav1.CreateOptions{})
	if err != nil {
		return fmt.Errorf("failed to create daemonset %v", err)
	}

	// wait till it is ready, download time could vary
	return Retry(func() error {
		d, err := dsCli.Get(context.TODO(), ds.Name, metav1.GetOptions{})
		if err != nil {
			return fmt.Errorf("failed to get ds %v, %v", ds.Name, err)
		}
		if d.Status.NumberReady == 0 || d.Status.DesiredNumberScheduled != d.Status.NumberReady {
			return fmt.Errorf("ds %v not ready, %v", d.Name, d.Status)
		}
		return nil
	}, 10*time.Minute, time.Second*5)

}

func DelDaemonset(cl *kubernetes.Clientset, ns string, name string) error {
	dsCli := cl.AppsV1().DaemonSets(ns)
	deletePolicy := metav1.DeletePropagationForeground
	return dsCli.Delete(context.TODO(), name, metav1.DeleteOptions{
		PropagationPolicy: &deletePolicy,
	})
}

func NodeLabellerName(cfgName string) string {
	return cfgName + "-node-labeller"
}
func NFDWorkerName(isOpenshift bool) string {
	if isOpenshift {
		return "nfd-worker"
	}
	return "amd-gpu-operator-node-feature-discovery-worker"
}

func ExecPodCmd(command string, ns string, name string) (string, error) {
	cmd := exec.Command(kubectl, "exec", "-n", ns, name, "--", "sh", "-c", command)
	out, err := cmd.CombinedOutput()
	return string(out), err
}

func Retry(f func() error, timeout time.Duration, period time.Duration) error {
	timedout := time.After(timeout)
	tick := time.Tick(period)
	for {
		select {
		case <-timedout:
			return fmt.Errorf("timeout")
		case <-tick:
			if err := f(); err == nil {
				return nil
			}
		}
	}
}

func GetClusterType(cfg *rest.Config) string {
	if dc, err := discovery.NewDiscoveryClientForConfig(cfg); err == nil {
		if gplist, err := dc.ServerGroups(); err == nil {
			for _, gp := range gplist.Groups {
				if gp.Name == "route.openshift.io" {
					return ClusterTypeOpenShift
				}
			}
		}
	}
	return ClusterTypeK8s
}
