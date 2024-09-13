package e2e

import (
	"bufio"
	"context"
	"fmt"
	"github.com/pensando/gpu-operator/tests/e2e/utils"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/util/intstr"
	"os/exec"
	"os/user"
	"strings"
	"time"

	"github.com/pensando/gpu-operator/api/v1alpha1"
	log "github.com/sirupsen/logrus"
	"github.com/stretchr/testify/assert"
	. "gopkg.in/check.v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

func (s *E2ESuite) getDeviceConfig(c *C) *v1alpha1.DeviceConfig {
	userInfo, err := user.Current()
	assert.Errorf(c, err, "failed to get user")
	devCfg := &v1alpha1.DeviceConfig{
		ObjectMeta: metav1.ObjectMeta{
			Name: s.cfgName,
		},
		Spec: v1alpha1.DeviceConfigSpec{
			DriversImage:   fmt.Sprintf("registry.test.pensando.io:5000/e2e/%v", userInfo.Username),
			DriversVersion: "6.1.3",
			//SkipDrivers:    true,
			MetricsExport: v1alpha1.MetricsExportSpec{
				Port: 32501,
			},
			Selector: map[string]string{"feature.node.kubernetes.io/amd-gpu": "true"},
		},
	}
	if s.openshift {
		devCfg.Spec.DriversVersion = "el9-6.1.1"
	}
	return devCfg
}

func (s *E2ESuite) createDevice(devCfg *v1alpha1.DeviceConfig, c *C) {
	_, err := s.dClient.DeviceConfigs(s.ns).Create(devCfg)
	assert.NoError(c, err, "failed to create %v", s.cfgName)
}

func (s *E2ESuite) checkNFDWorkerStatus(ns string, c *C, workerName string) {
	if workerName == "" {
		workerName = utils.NFDWorkerName(s.openshift)
	}
	assert.Eventually(c, func() bool {
		ds, err := s.clientSet.AppsV1().DaemonSets(ns).Get(context.TODO(), workerName, metav1.GetOptions{})
		if err != nil {
			log.Errorf("failed to get node-feature-discovery %v", err)
			return false
		}
		log.Infof("node-feature-discovery-worker status %+v",
			ds.Status)
		return ds.Status.DesiredNumberScheduled > 0 &&
			ds.Status.NumberReady == ds.Status.DesiredNumberScheduled
	}, 5*time.Minute, 5*time.Second)
}

func (s *E2ESuite) checkNodeLabellerStatus(ns string, c *C) {
	assert.Eventually(c, func() bool {
		ds, err := s.clientSet.AppsV1().DaemonSets(ns).Get(context.TODO(), utils.NodeLabellerName(s.cfgName), metav1.GetOptions{})
		if err != nil {
			log.Errorf("failed to get node-labeller %v", err)
			return false
		}
		log.Infof("node-labeller status %+v", ds.Status)
		return ds.Status.NumberReady > 0 && ds.Status.NumberReady == ds.Status.DesiredNumberScheduled
	}, 5*time.Minute, 5*time.Second)
}

func (s *E2ESuite) checkMetricsExportStatus(devCfg *v1alpha1.DeviceConfig, ns string, c *C) {
	assert.Eventually(c, func() bool {
		ds, err := s.clientSet.AppsV1().DaemonSets(ns).Get(context.TODO(), s.cfgName+"-metrics-export", metav1.GetOptions{})
		if err != nil {
			log.Errorf("failed to get metrics export %v", err)
			return false
		}
		log.Infof("metrics export %+v", ds.Status)
		svc, err := s.clientSet.CoreV1().Services(ns).Get(context.TODO(), s.cfgName+"-metrics-export", metav1.GetOptions{})
		if err != nil {
			log.Errorf("failed to get metrics service %v", err)
			return false
		}
		log.Infof("metrics service %+v", svc.Spec)

		return ds.Status.NumberReady > 0 && ds.Status.NumberReady == ds.Status.DesiredNumberScheduled &&
			svc.Spec.Type == corev1.ServiceTypeNodePort && len(svc.Spec.Ports) > 0 && svc.Spec.Ports[0].TargetPort == intstr.FromInt32(5000) &&
			svc.Spec.Ports[0].NodePort == devCfg.Spec.MetricsExport.Port
	}, 5*time.Minute, 5*time.Second)
}

func (s *E2ESuite) TestDeployment(c *C) {
	_, err := s.dClient.DeviceConfigs(s.ns).Get(s.cfgName, metav1.GetOptions{})
	assert.Errorf(c, err, fmt.Sprintf("config %v exists", s.cfgName))

	log.Infof("create %v", s.cfgName)
	devCfg := s.getDeviceConfig(c)
	s.createDevice(devCfg, c)
	s.checkNFDWorkerStatus(s.ns, c, "")
	s.checkNodeLabellerStatus(s.ns, c)
	s.checkMetricsExportStatus(devCfg, s.ns, c)

	assert.Eventually(c, func() bool {
		devCfg, err := s.dClient.DeviceConfigs(s.ns).Get(s.cfgName, metav1.GetOptions{})
		if err != nil {
			log.Errorf("failed to get deviceConfig %v", err)
			return false
		}
		log.Infof("driver status %+v",
			devCfg.Status.Drivers)
		log.Infof("device-plugin status %+v",
			devCfg.Status.DevicePlugin)

		return devCfg.Status.DevicePlugin.NodesMatchingSelectorNumber > 0 &&
			devCfg.Status.Drivers.NodesMatchingSelectorNumber == devCfg.Status.Drivers.AvailableNumber &&
			devCfg.Status.Drivers.DesiredNumber == devCfg.Status.Drivers.AvailableNumber &&
			devCfg.Status.DevicePlugin.NodesMatchingSelectorNumber == devCfg.Status.DevicePlugin.AvailableNumber &&
			devCfg.Status.DevicePlugin.DesiredNumber == devCfg.Status.DevicePlugin.AvailableNumber
	}, 5*time.Minute, 5*time.Second)

	assert.Eventually(c, func() bool {
		nodes, err := s.clientSet.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{
			LabelSelector: func() string {
				s := []string{}
				for k, v := range devCfg.Spec.Selector {
					s = append(s, fmt.Sprintf("%v=%v", k, v))
				}
				return strings.Join(s, ",")
			}(),
		})
		if err != nil {
			log.Errorf("failed to get nodes %v", err)
			return false
		}

		for _, node := range nodes.Items {
			if !utils.CheckGpuLabel(node.Status.Capacity) {
				log.Infof("gpu not found in %v, %v ", node.Name, node.Status.Capacity)
				return false
			}
		}
		for _, node := range nodes.Items {
			if !utils.CheckGpuLabel(node.Status.Allocatable) {
				log.Infof("allocatable gpu not found in %v, %v ", node.Name, node.Status.Allocatable)
				return false
			}
		}
		return true

	}, 5*time.Minute, 5*time.Second)

	err = utils.DeployRocmPods(context.TODO(), s.clientSet)
	assert.NoError(c, err, "failed to deploy pods")
	pods, err := utils.ListRocmPods(context.TODO(), s.clientSet)
	assert.NoError(c, err, "failed to deploy pods")
	for _, p := range pods {
		v, err := utils.GetRocmInfo(p)
		assert.NoError(c, err, "rocm-smi failed on", p, v)
		log.Infof("rocm-smi %v  \n %v", p, v)
		v, err = utils.ListGpuDrivers(p)
		assert.NoError(c, err, "list drivers failed on", p, v)
		log.Infof("gpudrivers %v \n%v ", p, v)
		v, err = utils.GetGpuDriverVersion(p)
		assert.NoError(c, err, "drivers version failed on", p, v)
		log.Infof("gpudrivers %v \n%v ", p, v)
	}

	// delete
	_, err = s.dClient.DeviceConfigs(s.ns).Delete(s.cfgName)
	assert.NoErrorf(c, err, "failed to delete %v", s.cfgName)

	assert.Eventually(c, func() bool {
		_, err := s.clientSet.AppsV1().DaemonSets(s.ns).Get(context.TODO(), s.cfgName+"-node-labeller", metav1.GetOptions{})
		if err == nil {
			log.Warnf("waiting to delete node-labeller ")
			return false
		}
		return true
	}, 5*time.Minute, 5*time.Second)

	assert.Eventually(c, func() bool {
		_, err := s.dClient.DeviceConfigs(s.ns).Get(s.cfgName, metav1.GetOptions{})
		if err == nil {
			log.Warnf("waiting to delete deviceConfig")
			return false
		}
		return true
	}, 5*time.Minute, 5*time.Second)

	pods, err = utils.ListRocmPods(context.TODO(), s.clientSet)
	assert.NoError(c, err, "failed to deploy pods")
	for _, p := range pods {
		v, err := utils.GetRocmInfo(p)
		assert.Errorf(c, err, "rocm-smi available oni %v %v", p, v)
		log.Infof("rocm-smi %v \n %v", p, v)
		v, err = utils.ListGpuDrivers(p)
		assert.Errorf(c, err, "drivers available on %v %v", p, v)
		log.Infof("gpudrivers %v \n%v ", p, v)
		v, err = utils.GetGpuDriverVersion(p)
		assert.Errorf(c, err, "driver version available on %v %v", p, v)
		log.Infof("driver version %v \n%v ", p, v)
	}

	err = utils.DelRocmPods(context.TODO(), s.clientSet)
	assert.NoError(c, err, "failed to remove rocm pods")
	log.Infof("Test completed")

}

func (s *E2ESuite) getNFDCurrentCSV() (currentCSV string) {
	command := "oc get subscription nfd -n openshift-nfd -oyaml | grep currentCSV"
	log.Infof("  %v", command)
	cmd := exec.Command("bash", "-c", command)
	output, _ := cmd.StdoutPipe()
	cmd.Start()
	scanner := bufio.NewScanner(output)
	for scanner.Scan() {
		m := scanner.Text()
		log.Infof("    %v", m)
		if strings.Contains(m, "currentCSV") {
			csvSplits := strings.Split(m, ":")
			if len(csvSplits) > 1 {
				currentCSV = csvSplits[1]
			}
			break
		}
	}
	cmd.Wait()
	return
}

func (s *E2ESuite) TestDeploymentWithPreInstalledKMMAndNFD(c *C) {
	var deployCommand, undeployCommand, deployWithoutNFDKMMCommand string
	var nfdInstallCommands, nfdUnInstallCommands []string
	var kmmInstallCommand, kmmUnInstallCommand string
	var standardNFDNamespace, standardNFDWorkerName, standardSelector string
	if s.openshift {
		standardNFDNamespace = "openshift-nfd"
		standardSelector = "feature.node.kubernetes.io/pci-1002.present"
		deployCommand = "OPENSHIFT=1 make -C ../../ helm-install"
		undeployCommand = "OPENSHIFT=1 make -C ../../ helm-uninstall"
		deployWithoutNFDKMMCommand  = "OPENSHIFT=1 SKIP_NFD=1 SKIP_KMM=1 make -C ../../ helm-install"
		nfdInstallCommands = append(nfdInstallCommands, "oc create -f ./yamls/openshift/nfd-namespace.yaml")
		nfdInstallCommands = append(nfdInstallCommands, "oc create -f ./yamls/openshift/nfd-operatorgroup.yaml")
		nfdInstallCommands = append(nfdInstallCommands, "oc create -f ./yamls/openshift/nfd-sub.yaml")
		nfdInstallCommands = append(nfdInstallCommands, "oc apply -f ./yamls/openshift/nfd-instance.yaml")
		nfdUnInstallCommands = append(nfdUnInstallCommands, "oc delete -f ./yamls/openshift/nfd-instance.yaml")
		nfdUnInstallCommands = append(nfdUnInstallCommands, "oc delete subscription nfd -n openshift-nfd")
		nfdUnInstallCommands = append(nfdUnInstallCommands, "oc delete -f ./yamls/openshift/nfd-operatorgroup.yaml")
		nfdUnInstallCommands = append(nfdUnInstallCommands, "oc delete clusterserviceversion -n openshift-nfd %s")
		nfdUnInstallCommands = append(nfdUnInstallCommands, "oc delete -f ./yamls/openshift/nfd-namespace.yaml")
		kmmInstallCommand = "oc apply -k https://github.com/rh-ecosystem-edge/kernel-module-management/config/default"
		kmmUnInstallCommand = "oc delete -k https://github.com/rh-ecosystem-edge/kernel-module-management/config/default"

	} else {
		standardSelector = "feature.node.kubernetes.io/amd-gpu"
		standardNFDNamespace = "node-feature-discovery"
		standardNFDWorkerName = "nfd-worker"
		deployCommand =  "make -C ../../ helm-install"
		undeployCommand = "make -C ../../ helm-uninstall"
		deployWithoutNFDKMMCommand = "SKIP_NFD=1 SKIP_KMM=1 make -C ../../ helm-install"
		nfdInstallCommands = append(nfdInstallCommands, "kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/node-feature-discovery/v0.7.0/nfd-master.yaml.template")
		nfdInstallCommands = append(nfdInstallCommands, "kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/node-feature-discovery/v0.7.0/nfd-worker-daemonset.yaml.template")
		nfdUnInstallCommands = append(nfdUnInstallCommands, "kubectl delete -f https://raw.githubusercontent.com/kubernetes-sigs/node-feature-discovery/v0.7.0/nfd-worker-daemonset.yaml.template")
		nfdUnInstallCommands = append(nfdUnInstallCommands, "kubectl delete -f https://raw.githubusercontent.com/kubernetes-sigs/node-feature-discovery/v0.7.0/nfd-master.yaml.template")
		kmmInstallCommand = "kubectl apply -k https://github.com/kubernetes-sigs/kernel-module-management/config/default"
		kmmUnInstallCommand = "kubectl delete -k https://github.com/kubernetes-sigs/kernel-module-management/config/default"
	}

	log.Infof("Un-Deploying the e2e deployment")
	// Delete the current Deployment
	utils.RunCommand(undeployCommand)
	log.Infof("Waiting for cleanup after undeploy")
	if s.openshift == false {
		assert.Eventually(c, func() bool {
			if err := utils.CheckHelmDeployment(s.clientSet, s.ns, false); err != nil {
				log.Infof("%v", err)
				return false
			}
			return true
		}, 5*time.Minute, 5*time.Second)
	} else {
		assert.Eventually(c, func() bool {
			if err := utils.CheckHelmOCDeployment(s.clientSet,false); err != nil {
				log.Infof("    %v", err)
				return false
			}
			return true
		}, 5*time.Minute, 5*time.Second)
	}


	log.Infof("Deploying standard NFD and KMM Operator")
	// Deploy standard NFD and KMM Operator
	for _, cmd := range nfdInstallCommands {
		utils.RunCommand(cmd)
	}
	utils.RunCommand(kmmInstallCommand)

	log.Infof("Deploying GPU opertor without NFD and KMM Operator")
	// Deploy GPU operator. Skip NFD and KMM
	utils.RunCommand(deployWithoutNFDKMMCommand)

	log.Infof("Verify GPU operator deployment with standard NFD and KMM operator")
	if s.openshift == false {
		assert.Eventually(c, func() bool {
			if err := utils.CheckDeploymentWithStandardKMMNFD(s.clientSet, true); err != nil {
				log.Infof("%v", err)
				return false
			}
			return true
		}, 5*time.Minute, 5*time.Second)
	} else {
		assert.Eventually(c, func() bool {
			if err := utils.CheckOCDeploymentWithStandardKMMNFD(s.clientSet,true); err != nil {
				log.Infof("    %v", err)
				return false
			}
			return true
		}, 5*time.Minute, 5*time.Second)
	}

	devCfg := s.getDeviceConfig(c)
	devCfg.Spec.Selector = map[string]string{standardSelector: "true"}
	s.createDevice(devCfg, c)
	s.checkNFDWorkerStatus(standardNFDNamespace, c, standardNFDWorkerName)
	s.checkNodeLabellerStatus("kube-amd-gpu", c)

	log.Infof("Un-Deploying the current deployment")

	// Delete the current Deployment
	utils.RunCommand(undeployCommand)
	utils.RunCommand(kmmUnInstallCommand)
	nfdCurrentCSV := s.getNFDCurrentCSV()
	for _, cmd := range nfdUnInstallCommands {
		if strings.Contains(cmd, "clusterserviceversion") {
			utils.RunCommand(fmt.Sprintf(cmd, nfdCurrentCSV))
			continue
		}
		utils.RunCommand(cmd)
	}

	log.Infof("m4")
	log.Infof("Waiting for cleanup with standard KMM NFD deployment")
	if s.openshift == false {
		assert.Eventually(c, func() bool {
			if err := utils.CheckDeploymentWithStandardKMMNFD(s.clientSet, false); err != nil {
				log.Infof("%v", err)
				return false
			}
			return true
		}, 5*time.Minute, 5*time.Second)
	} else {
		assert.Eventually(c, func() bool {
			if err := utils.CheckOCDeploymentWithStandardKMMNFD(s.clientSet,false); err != nil {
				log.Infof("    %v", err)
				return false
			}
			return true
		}, 5*time.Minute, 5*time.Second)
	}

	log.Infof("Re-Deploying the e2e deployment")
	// Restore E2E Deployment
	utils.RunCommand(deployCommand)
	if s.openshift == false {
		assert.Eventually(c, func() bool {
			if err := utils.CheckHelmDeployment(s.clientSet, s.ns, true); err != nil {
				log.Infof("%v", err)
				return false
			}
			return true
		}, 5*time.Minute, 5*time.Second)
	} else {
		assert.Eventually(c, func() bool {
			if err := utils.CheckHelmOCDeployment(s.clientSet,true); err != nil {
				log.Infof("    %v", err)
				return false
			}
			return true
		}, 5*time.Minute, 5*time.Second)
	}
}
