package e2e

import (
	"flag"
	"path/filepath"
	"testing"

	"github.com/pensando/gpu-operator/tests/e2e/client"
	log "github.com/sirupsen/logrus"
	. "gopkg.in/check.v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/client-go/util/homedir"
)

var kubeconfig = flag.String("kubeconfig", filepath.Join(homedir.HomeDir(), ".kube", "config"), "absolute path to the kubeconfig file")
var helmChart = flag.String("helmchart", "", "helmchart")
var operatorNS = flag.String("namespace", "kube-amd-gpu", "namespace")
var cfgName = flag.String("deviceConfigName", "test-device-config", "deviceConfig name")
var registry = flag.String("registry", "10.11.18.9:5000/ubuntu:amdgpu-6.1.3", "driver container registry")

// Hook up gocheck into the "go test" runner.
func Test(t *testing.T) {
	TestingT(t)
}

var _ = Suite(&E2ESuite{})

func (s *E2ESuite) SetUpSuite(c *C) {
	log.Infof("setupSuite:")
	s.helmChart = *helmChart
	s.kubeconfig = *kubeconfig
	s.ns = *operatorNS
	s.cfgName = *cfgName
	s.registry = *registry

	// use the current context in kubeconfig
	config, err := clientcmd.BuildConfigFromFlags("", s.kubeconfig)
	if err != nil {
		c.Fatalf(err.Error())
	}

	dcCli, err := client.Client(config)
	if err != nil {
		c.Fatalf(err.Error())
	}
	s.dClient = dcCli

	// creates the clientset
	cs, err := kubernetes.NewForConfig(config)
	if err != nil {
		c.Fatalf(err.Error())
	}
	s.clientSet = cs
}
func (s *E2ESuite) SetUpTest(c *C) {
	log.Info("setupTest:")

}
func (s *E2ESuite) TearDownTest(c *C) {
	log.Info("TearDownTest:")
	if l, err := s.dClient.DeviceConfigs(s.ns).List(metav1.ListOptions{}); err == nil {
		for _, cfg := range l.Items {
			log.Infof("delete %v", cfg.Name)
			if _, err := s.dClient.DeviceConfigs(s.ns).Delete(cfg.Name); err != nil {
				c.Fatalf(err.Error())
			}
		}
	}
}
func (s *E2ESuite) TearDownSuite(c *C) {
	log.Info("TearDownSuite:")
	if l, err := s.dClient.DeviceConfigs(s.ns).List(metav1.ListOptions{}); err == nil {
		for _, cfg := range l.Items {
			log.Infof("delete %v", cfg.Name)
			if _, err := s.dClient.DeviceConfigs(s.ns).Delete(cfg.Name); err != nil {
				c.Fatalf(err.Error())
			}
		}
	}
}
