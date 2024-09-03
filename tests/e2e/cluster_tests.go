package e2e

import (
	"context"
	"fmt"
	"github.com/pensando/gpu-operator/tests/e2e/utils"
	"os/user"
	"strings"
	"time"

	"github.com/pensando/gpu-operator/api/v1alpha1"
	log "github.com/sirupsen/logrus"
	"github.com/stretchr/testify/assert"
	. "gopkg.in/check.v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

func (s *E2ESuite) TestDeployment(c *C) {
	_, err := s.dClient.DeviceConfigs(s.ns).Get(s.cfgName, metav1.GetOptions{})
	assert.Errorf(c, err, fmt.Sprintf("config %v exists", s.cfgName))

	log.Infof("create %v", s.cfgName)

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
			Selector: map[string]string{"feature.node.kubernetes.io/amd-gpu": "true"},
		},
	}
	if s.openshift {
		devCfg.Spec.DriversVersion = "el9-6.1.1"
	}
	_, err = s.dClient.DeviceConfigs(s.ns).Create(devCfg)
	assert.NoError(c, err, "failed to create %v", s.cfgName)

	assert.Eventually(c, func() bool {
		ds, err := s.clientSet.AppsV1().DaemonSets(s.ns).Get(context.TODO(), utils.NFDWorkerName(s.openshift), metav1.GetOptions{})
		if err != nil {
			log.Errorf("failed to get node-feature-discovery %v", err)
			return false
		}
		log.Infof("node-feature-discovery-worker status %+v",
			ds.Status)
		return ds.Status.DesiredNumberScheduled > 0 &&
			ds.Status.NumberReady == ds.Status.DesiredNumberScheduled
	}, 5*time.Minute, 5*time.Second)

	assert.Eventually(c, func() bool {
		ds, err := s.clientSet.AppsV1().DaemonSets(s.ns).Get(context.TODO(), utils.NodeLabellerName(s.cfgName), metav1.GetOptions{})
		if err != nil {
			log.Errorf("failed to get node-labeller %v", err)
			return false
		}
		log.Infof("node-labeller status %+v",
			ds.Status)
		return ds.Status.NumberReady == ds.Status.DesiredNumberScheduled
	}, 5*time.Minute, 5*time.Second)

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
}
