package e2e

import (
	"context"
	"fmt"
	"github.com/pensando/gpu-operator/tests/e2e/utils"
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

	devCfg := &v1alpha1.DeviceConfig{
		ObjectMeta: metav1.ObjectMeta{
			Name: s.cfgName,
		},
		Spec: v1alpha1.DeviceConfigSpec{
			DriversImage:   "10.11.18.9:5000/ubuntu:amdgpu-6.1.3",
			DriversVersion: "6.1.3",
			Selector:       map[string]string{"feature.node.kubernetes.io/amd-gpu": "true"},
		},
	}
	_, err = s.dClient.DeviceConfigs(s.ns).Create(devCfg)
	assert.NoError(c, err, "failed to create %v", s.cfgName)

	assert.Eventually(c, func() bool {
		ds, err := s.clientSet.AppsV1().DaemonSets(s.ns).Get(context.TODO(), utils.NFDWorkerName(), metav1.GetOptions{})
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
		log.Infof("devplugin status %+v",
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
				log.Warnf("gpu not found in %v, %+v ", node.Name, node.Status.Capacity)
				return false
			}
		}
		return true

	}, 5*time.Minute, 5*time.Second)

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
}
