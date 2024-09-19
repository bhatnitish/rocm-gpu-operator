package utils

import (
	"bufio"
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"github.com/pensando/gpu-operator/internal/kmmmodule"
	log "github.com/sirupsen/logrus"
	appsv1 "k8s.io/api/apps/v1"
	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/apimachinery/pkg/selection"
	"k8s.io/client-go/discovery"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
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

	//Set logging properties
	log.SetReportCaller(true)
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

func CheckDeploymentWithStandardKMMNFD(cl *kubernetes.Clientset, create bool) error {
	for _, d := range []struct {
		ns, name string
	}{
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-controller-manager"},
		{ns: "kmm-operator-system", name: "kmm-operator-controller"},
		{ns: "kmm-operator-system", name: "kmm-operator-webhook-server"},
		{ns: "node-feature-discovery", name: "nfd-master"},
	} {
		s, err := cl.AppsV1().Deployments(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if !create {
			if err == nil {
				return fmt.Errorf("Pod %v in namespace %v is not deleted yet", d.ns, d.name)
			}
		} else {
			if err != nil {
				return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
			}
			if s.Status.Replicas == 0 || s.Status.ReadyReplicas != s.Status.Replicas {
				return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
			}
		}
	}

	for _, d := range []struct {
		ns, name string
	}{
		{ns: "node-feature-discovery", name: "nfd-worker"},
	} {
		s, err := cl.AppsV1().DaemonSets(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if !create {
			if err == nil {
				return fmt.Errorf("Replica %v in namespace %v is not deleted yet", d.ns, d.name)
			}
		} else {
			if err != nil {
				return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
			}
			if s.Status.DesiredNumberScheduled == 0 || s.Status.DesiredNumberScheduled != s.Status.NumberReady {
				return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
			}
		}
	}
	return nil
}

func CheckOCDeploymentWithStandardKMMNFD(cl *kubernetes.Clientset, create bool) error {
	for _, d := range []struct {
		ns, name string
	}{
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-controller-manager"},
		{ns: "openshift-kmm", name: "kmm-operator-controller"},
		{ns: "openshift-kmm", name: "kmm-operator-webhook-server"},
		{ns: "openshift-nfd", name: "nfd-controller-manager"},
		{ns: "openshift-nfd", name: "nfd-master"},
	} {
		s, err := cl.AppsV1().Deployments(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if !create {
			if err == nil {
				return fmt.Errorf("Pod %v in namespace %v is not deleted yet", d.ns, d.name)
			}
		} else {
			if err != nil {
				return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
			}
			if s.Status.Replicas == 0 || s.Status.ReadyReplicas != s.Status.Replicas {
				return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
			}
		}
	}

	for _, d := range []struct {
		ns, name string
	}{
		{ns: "openshift-nfd", name: "nfd-worker"},
	} {
		s, err := cl.AppsV1().DaemonSets(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if !create {
			if err == nil {
				return fmt.Errorf("Replica %v in namespace %v is not deleted yet", d.ns, d.name)
			}
		} else {
			if err != nil {
				return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
			}
			if s.Status.DesiredNumberScheduled == 0 || s.Status.DesiredNumberScheduled != s.Status.NumberReady {
				return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
			}
		}
	}
	return nil
}

func CheckHelmOCDeployment(cl *kubernetes.Clientset, create bool) error {

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
		if !create {
			if err == nil {
				return fmt.Errorf("Pod %v in namespace %v is not deleted yet", d.ns, d.name)
			}
		} else {
			if err != nil {
				return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
			}
			if s.Status.Replicas == 0 || s.Status.ReadyReplicas != s.Status.Replicas {
				return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
			}
		}
	}

	for _, d := range []struct {
		ns, name string
	}{
		{ns: "kube-amd-gpu", name: "nfd-worker"},
	} {
		s, err := cl.AppsV1().DaemonSets(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if !create {
			if err == nil {
				return fmt.Errorf("Replica %v in namespace %v is not deleted yet", d.ns, d.name)
			}
		} else {
			if err != nil {
				return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
			}
			if s.Status.DesiredNumberScheduled == 0 || s.Status.DesiredNumberScheduled != s.Status.NumberReady {
				return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
			}
		}
	}
	return nil
}

func CheckHelmDeployment(cl *kubernetes.Clientset, ns string, create bool) error {
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
		if !create {
			if strings.Contains(d.name, "cert-manager") {
				continue
			}
			if err == nil {
				return fmt.Errorf("Pod %v in namespace %v is not deleted yet", d.ns, d.name)
			}
		} else {
			if err != nil {
				return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
			}
			if s.Status.Replicas == 0 || s.Status.ReadyReplicas != s.Status.Replicas {
				return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
			}
		}
	}

	for _, d := range []struct {
		ns, name string
	}{
		{ns: "kube-amd-gpu", name: "amd-gpu-operator-node-feature-discovery-worker"},
	} {
		s, err := cl.AppsV1().DaemonSets(d.ns).Get(context.TODO(), d.name, metav1.GetOptions{})
		if !create {
			if err == nil {
				return fmt.Errorf("Replica %v in namespace %v is not deleted yet", d.ns, d.name)
			}
		} else {
			if err != nil {
				return fmt.Errorf("failed to get %v/%v err %v", d.ns, d.name, err)
			}
			if s.Status.DesiredNumberScheduled == 0 || s.Status.DesiredNumberScheduled != s.Status.NumberReady {
				return fmt.Errorf("replicas not ready %v/%v status %v", d.ns, d.name, s.Status)
			}
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
	if err := DelDaemonset(cl, v1.NamespaceDefault, rocmDs); err != nil {
		return fmt.Errorf("failed to delete %v, %v", rocmDs, err)
	}
	if err := Retry(func() error {
		its, err := cl.CoreV1().Pods("").List(ctx, metav1.ListOptions{LabelSelector: kmmmodule.MapToLabelSelector(rocmLabel)})
		if err != nil {
			return fmt.Errorf("failed to list pods %v", err)
		}
		if len(its.Items) > 0 {
			return fmt.Errorf("pod %v exists", len(its.Items))
		}
		return nil
	}, time.Minute*5, time.Second*5); err != nil {
		return fmt.Errorf("pod(s) exist, %v", err)
	}
	return nil
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

func DeletePod(ctx context.Context, cl *kubernetes.Clientset, ns string,
	name string) error {
	rpodCli := cl.CoreV1().Pods(ns)
	return rpodCli.Delete(ctx, name, metav1.DeleteOptions{})
}

func CreateDaemonset(ctx context.Context, cl *kubernetes.Clientset, ns string,
	name string, image string, matchLabels map[string]string) error {

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
					NodeSelector: map[string]string{"feature.node.kubernetes.io/amd-gpu": "true"},
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
	tick := time.NewTicker(period)
	for {
		select {
		case <-timedout:
			return fmt.Errorf("timeout")
		case <-tick.C:
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

func RunCommand(command string) {
	log.Infof("  %v", command)
	cmd := exec.Command("bash", "-c", command)
	output, _ := cmd.StdoutPipe()
	if err := cmd.Start(); err != nil {
		log.Errorf("Command %v failed to start with error: %v", command, err)
		return
	}

	scanner := bufio.NewScanner(output)
	for scanner.Scan() {
		m := scanner.Text()
		log.Infof("    %v", m)
	}
	if err := cmd.Wait(); err != nil {
		log.Errorf("Coammand %v did not complete with error: %v", command, err)
	}
}

func GetWorkerNodes(cl *kubernetes.Clientset) []*v1.Node {
	ret := make([]*v1.Node, 0)

	labelSelector := labels.NewSelector()
	r, _ := labels.NewRequirement(
		"node-role.kubernetes.io/control-plane",
		selection.DoesNotExist,
		nil,
	)
	labelSelector = labelSelector.Add(*r)

	nodes, err := cl.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{
		LabelSelector: labelSelector.String(),
	})
	if err != nil {
		log.Errorf("GetWorkerNodes error: %v", err)
		return ret
	}
	for i := 0; i < len(nodes.Items); i++ {
		node := &nodes.Items[i]
		ret = append(ret, node)
	}
	return ret
}

func GetAMDGpuWorker(cl *kubernetes.Clientset) []*v1.Node {
	ret := make([]*v1.Node, 0)

	labelSelector := labels.NewSelector()
	r, _ := labels.NewRequirement(
		"node-role.kubernetes.io/control-plane",
		selection.DoesNotExist,
		nil,
	)
	labelSelector = labelSelector.Add(*r)
	r, _ = labels.NewRequirement("gpu.vendor",
		selection.Equals,
		[]string{"amd"},
	)
	labelSelector = labelSelector.Add(*r)

	nodes, err := cl.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{
		LabelSelector: labelSelector.String(),
	})
	if err != nil {
		log.Errorf("GetWorkerNodes error: %v", err)
		return ret
	}
	for i := 0; i < len(nodes.Items); i++ {
		node := &nodes.Items[i]
		ret = append(ret, node)
	}
	return ret
}

func GetNonAMDGpuWorker(cl *kubernetes.Clientset) []*v1.Node {
	ret := make([]*v1.Node, 0)

	labelSelector := labels.NewSelector()
	r, _ := labels.NewRequirement(
		"node-role.kubernetes.io/control-plane",
		selection.DoesNotExist,
		nil,
	)
	labelSelector = labelSelector.Add(*r)
	r, _ = labels.NewRequirement("gpu.vendor",
		selection.NotEquals,
		[]string{"amd"},
	)
	labelSelector = labelSelector.Add(*r)

	nodes, err := cl.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{
		LabelSelector: labelSelector.String(),
	})
	if err != nil {
		log.Errorf("GetWorkerNodes error: %v", err)
		return ret
	}
	for i := 0; i < len(nodes.Items); i++ {
		node := &nodes.Items[i]
		ret = append(ret, node)
	}
	return ret
}

func CreatePod(ctx context.Context, cl *kubernetes.Clientset, ns string,
	name string, image string, workerNodeName string) error {

	rpodCli := cl.CoreV1().Pods(ns)
	rpod := &v1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: name,
		},
		Spec: v1.PodSpec{
			Containers: []v1.Container{
				{
					Name:    name,
					Image:   image,
					Command: []string{"sh", "-c", "--"},
					Args:    []string{"sleep infinity"},
				},
			},
			NodeName: workerNodeName,
		},
	}

	// Create pod
	_, err := rpodCli.Create(context.TODO(), rpod, metav1.CreateOptions{})
	if err != nil {
		return fmt.Errorf("failed to create pod %v", err)
	}
	return err
}

func DeployRocmPodsByNodeNames(ctx context.Context, cl *kubernetes.Clientset,
	workerNodeNames []string) error {

	for _, name := range workerNodeNames {

		err := CreatePod(ctx, cl, v1.NamespaceDefault,
			fmt.Sprintf("%s-%s", rocmDs, name), "rocm/tensorflow:latest", name)
		if err != nil {
			return fmt.Errorf("failed to create rocm as e2e pods %v", err)
		}
	}

	if err := Retry(func() error {

		for _, name := range workerNodeNames {
			its, err := cl.CoreV1().Pods("").List(ctx, metav1.ListOptions{
				FieldSelector: fmt.Sprintf("spec.nodeName=%s", name),
			})
			if err != nil {
				return fmt.Errorf("failed to get rocm e2e pods %v", err)
			}

			for _, p := range its.Items {
				for _, c := range p.Status.ContainerStatuses {
					if !c.Ready {
						return fmt.Errorf("pod %v/%v is not ready(%v)",
							p.Name, c.Name, c.Ready)
					}
				}
			}
		}
		return nil
	}, time.Minute*5, time.Second*5); err != nil {
		return fmt.Errorf("pods not ready %v", err)
	}
	return nil
}

func ListRocmPodsByNodeNames(ctx context.Context,
	workerNodeNames []string) []string {

	ret := make([]string, 0)
	for _, name := range workerNodeNames {
		ret = append(ret, fmt.Sprintf("%s-%s", rocmDs, name))
	}
	return ret
}

func DelRocmPodsByNodeNames(ctx context.Context, cl *kubernetes.Clientset,
	workerNodeNames []string) error {

	for _, name := range workerNodeNames {
		if err := DeletePod(ctx, cl, v1.NamespaceDefault,
			fmt.Sprintf("%s-%s", rocmDs, name)); err != nil {
			return fmt.Errorf("failed to delete %v, %v", rocmDs, err)
		}
	}

	if err := Retry(func() error {
		for _, node := range workerNodeNames {
			its, err := cl.CoreV1().Pods("").List(ctx, metav1.ListOptions{
				FieldSelector: fmt.Sprintf("spec.nodeName=%s", node),
			})
			if err != nil {
				return fmt.Errorf("failed to get rocm e2e pods %v", err)
			}
			for _, p := range its.Items {
				if p.Name == rocmDs {
					return fmt.Errorf("pod %v exists", len(its.Items))
				}
			}
		}
		return nil
	}, time.Minute*5, time.Second*5); err != nil {
		return fmt.Errorf("pod(s) exist, %v", err)
	}
	return nil

}
