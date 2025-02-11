/*
Copyright (c) Advanced Micro Devices, Inc. All rights reserved.

Licensed under the Apache License, Version 2.0 (the \"License\");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

	http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an \"AS IS\" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/
package e2e

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/pensando/gpu-operator/api/v1alpha1"
	"github.com/pensando/gpu-operator/internal/testrunner"
	"github.com/pensando/gpu-operator/tests/e2e/utils"
	"github.com/stretchr/testify/assert"
	. "gopkg.in/check.v1"
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
)

func (s *E2ESuite) checkTestRunnerStatus(devCfg *v1alpha1.DeviceConfig, expectDSExist bool, c *C) {
	if expectDSExist {
		assert.Eventually(c, func() bool {
			_, err := s.clientSet.AppsV1().DaemonSets(s.ns).Get(context.TODO(), devCfg.Name+"-"+testrunner.TestRunnerName, metav1.GetOptions{})
			if err != nil {
				log.Errorf("cannot find expected test runner daemonset, err %+v", err)
				return false
			}
			return true
		}, 5*time.Minute, 10*time.Second)
	} else {
		assert.Eventually(c, func() bool {
			trDS, err := s.clientSet.AppsV1().DaemonSets(s.ns).Get(context.TODO(), devCfg.Name+"-"+testrunner.TestRunnerName, metav1.GetOptions{})
			if err == nil {
				log.Errorf("found expected test runner daemonset but expect it doesn't exist %+v", trDS)
				return false
			}
			return true
		}, 5*time.Minute, 10*time.Second)
	}
}

func (s *E2ESuite) simulateOneGPUUnhealthyStatus(ns string, c *C) {
	// inject the UE to one of the exporter pod
	labelMap := make(map[string]string)
	log.Infof("Marking GPU unhealthy")
	err := utils.SetGPUHealthOnNode(s.clientSet, ns, "0", "unhealthy")
	assert.NoError(c, err, fmt.Sprintf("failed to mark GPU 0 unhealthy. Error:%v", err))
	labelMap["metricsexporter.amd.com.gpu.0.state"] = "unhealthy"
	log.Print("Verifying unhealthy label on the node(s)")
	assert.Eventually(c, func() bool {
		nodes, err := s.clientSet.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{
			LabelSelector: labels.SelectorFromSet(labelMap).String(),
		})
		if err != nil || len(nodes.Items) == 0 {
			return false
		}
		log.Printf("Got %d nodes with unhealthy label", len(nodes.Items))
		return true
	}, 90*time.Second, 10*time.Second, "expected gpu 0 to become unhealthy but got healthy")
}

func (s *E2ESuite) deleteTestRunnerPod(node string, devCfg *v1alpha1.DeviceConfig, c *C) {
	// delete the test runner pod during the test
	// check logs to make sure that the test will be restarted
	// and test runner was bale to detect the incomplete test run and restart it
	assert.Eventually(c, func() bool {
		pods, err := s.clientSet.CoreV1().Pods(devCfg.Namespace).List(context.TODO(), metav1.ListOptions{})
		if err != nil || len(pods.Items) == 0 {
			return false
		}
		for _, pod := range pods.Items {
			if pod.Spec.NodeName == node &&
				strings.Contains(pod.Name, devCfg.Name+"-"+testrunner.TestRunnerName) {
				err = s.clientSet.CoreV1().Pods(devCfg.Namespace).Delete(context.TODO(), pod.Name, metav1.DeleteOptions{})
				if err != nil {
					log.Printf("failed to delete pod %+v err %+v", pod.Name, err)
					return false
				}
				return true
			}
		}
		log.Printf("cannot find test runner pods")
		return false
	}, 90*time.Second, 10*time.Second, "expected to delete test runner pod on node %+v", node)
}

func (s *E2ESuite) verifyRestartIncompleteTest(node string, devCfg *v1alpha1.DeviceConfig, c *C) {
	// new test runner pod will be brought up automatically by k8s
	// verify that its logs are saying it is restarting incomplete test
	assert.Eventually(c, func() bool {
		pods, err := s.clientSet.CoreV1().Pods(devCfg.Namespace).List(context.TODO(), metav1.ListOptions{})
		if err != nil || len(pods.Items) == 0 {
			return false
		}
		for _, pod := range pods.Items {
			if pod.Spec.NodeName == node &&
				strings.Contains(pod.Name, devCfg.Name+"-"+testrunner.TestRunnerName) {
				req := s.clientSet.CoreV1().Pods(devCfg.Namespace).GetLogs(pod.Name, &v1.PodLogOptions{Container: "test-runner-container"})
				podLogs, err := req.Stream(context.TODO())
				if err != nil {
					fmt.Printf("failed to get pod logs err %+v", err)
					return false
				}
				defer podLogs.Close()

				// Print the logs
				buf := new(bytes.Buffer)
				_, err = io.Copy(buf, podLogs)
				if err != nil {
					fmt.Printf("failed to get pod logs err %+v", err)
					return false
				}
				if strings.Contains(buf.String(), "incomplete test") {
					log.Print("found test runner pod that has restarted the incomplete test")
					return true
				}
			}
		}
		log.Printf("cannot find test runner pods restarting the incomplete test")
		return false
	}, 90*time.Second, 10*time.Second, "expected to delete test runner pod on node %+v", node)
}

func (s *E2ESuite) verifyTestResultEvts(node string, devCfg *v1alpha1.DeviceConfig, c *C) {
	// verify that the test run event got generated
	log.Print("Verifying test result event(s)")
	testEventLabel := map[string]string{
		"testrunner.amd.com/category": "gpu_health_check",
		"testrunner.amd.com/trigger":  "auto_unhealthy_gpu_watch",
		"testrunner.amd.com/recipe":   "gst_single",
		"testrunner.amd.com/hostname": node,
	}
	assert.Eventually(c, func() bool {
		evts, err := s.clientSet.CoreV1().Events(devCfg.Namespace).List(context.TODO(), metav1.ListOptions{
			LabelSelector: labels.SelectorFromSet(testEventLabel).String(),
		})
		if err != nil || len(evts.Items) == 0 {
			return false
		}
		log.Printf("Got %d events with test events label: %+v", len(evts.Items), evts.Items)
		for _, evt := range evts.Items {
			// make sure that the event messages are json parsable
			assert.True(c, utils.IsJSONParsable(evt.Message), "event message is not json parsable %+v", evt)
		}
		return true
	}, 600*time.Second, 10*time.Second, "expected test run result event but got nothing")
}

func (s *E2ESuite) cleanupTestRunnerEvts(devCfg *v1alpha1.DeviceConfig, c *C) {
	// cleanup
	// need to remove the existing test runner event
	// so that other test runner test cases won't be affected
	log.Print("Clean up test runner events")
	assert.Eventually(c, func() bool {
		evts, err := s.clientSet.CoreV1().Events(devCfg.Namespace).List(context.TODO(), metav1.ListOptions{})
		if err != nil {
			log.Printf("failed to list events err %+v", err)
			return false
		}
		for _, evt := range evts.Items {
			if strings.Contains(evt.Name, "amd-test-runner") {
				err = s.clientSet.CoreV1().Events(devCfg.Namespace).Delete(context.TODO(), evt.Name, metav1.DeleteOptions{})
				if err != nil {
					log.Printf("failed to delete event %+v err %+v", evt.Name, err)
					return false
				}
			}
		}
		return true
	}, 60*time.Second, 10*time.Second, "expected test runner events to be cleaned up")
}

func (s *E2ESuite) TestTestRunnerEnablement(c *C) {
	_, err := s.dClient.DeviceConfigs(s.ns).Get(s.cfgName, metav1.GetOptions{})
	assert.Errorf(c, err, fmt.Sprintf("config %v exists", s.cfgName))

	log.Infof("create %v", s.cfgName)
	devCfg := s.getDeviceConfig(c)
	// test runner shouldn't be brought up when it is disabled
	enableTestRunner := false
	enableExporter := false
	devCfg.Spec.TestRunner.Enable = &enableTestRunner
	devCfg.Spec.MetricsExporter.Enable = &enableExporter
	devCfg.Spec.Driver.Version = "6.3.2"
	s.createDeviceConfig(devCfg, c)
	s.verifyDevicePluginStatus(s.ns, c, devCfg)
	s.checkTestRunnerStatus(devCfg, false, c)
	// if we only enable test runner but didn't enable exporter, test runner daemonset shouldn't be brought up
	enableTestRunner = true
	devCfg.Spec.TestRunner.Enable = &enableTestRunner
	s.patchTestRunnerEnablement(devCfg, c)
	s.checkTestRunnerStatus(devCfg, false, c)
	// enable both metrics exporter and test runner will bring up test runner daemonset
	enableTestRunner = true
	enableExporter = true
	devCfg.Spec.TestRunner.Enable = &enableTestRunner
	devCfg.Spec.MetricsExporter.Enable = &enableExporter
	s.patchTestRunnerEnablement(devCfg, c)
	s.patchMetricsExporterEnablement(devCfg, c)
	s.checkTestRunnerStatus(devCfg, true, c)
}

func (s *E2ESuite) TestTestRunnerAutoUnhealthyGPUWatchTrigger(c *C) {
	if s.simEnable {
		c.Skip("Skipping for non amd gpu testbed")
	}

	_, err := s.dClient.DeviceConfigs(s.ns).Get(s.cfgName, metav1.GetOptions{})
	assert.Errorf(c, err, fmt.Sprintf("config %v exists", s.cfgName))
	log.Infof("create %v", s.cfgName)
	devCfg := s.getDeviceConfig(c)
	// test runner should be brought up
	// when both exporter and test runner are enabled
	enableTestRunner := true
	enableExporter := true
	devCfg.Spec.TestRunner.Enable = &enableTestRunner
	devCfg.Spec.MetricsExporter.Enable = &enableExporter
	devCfg.Spec.MetricsExporter.Image = "registry.test.pensando.io:5000/device-metrics-exporter/exporter:v1.2.0"
	devCfg.Spec.Driver.Version = "6.3.2"
	s.createDeviceConfig(devCfg, c)
	s.verifyDevicePluginStatus(s.ns, c, devCfg)
	s.checkMetricsExporterStatus(devCfg, s.ns, v1.ServiceTypeClusterIP, c)
	s.checkTestRunnerStatus(devCfg, true, c)

	s.simulateOneGPUUnhealthyStatus(devCfg.Namespace, c)
	// verify that the test run started
	log.Print("Verifying test running label on the node(s)")
	testRunningLabel := map[string]string{
		"testrunner.amd.com.gpu_health_check.gst_single": "running",
	}
	hostName := ""
	assert.Eventually(c, func() bool {
		nodes, err := s.clientSet.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{
			LabelSelector: labels.SelectorFromSet(testRunningLabel).String(),
		})
		if err != nil || len(nodes.Items) == 0 {
			return false
		}
		hostName = nodes.Items[0].Name
		log.Printf("Got %d nodes with test running label", len(nodes.Items))
		return true
	}, 90*time.Second, 10*time.Second, "expected one node to start test run but got no node to start test run")

	// delete the test runner pod during the test
	// check logs to make sure that the test will be restarted
	// and test runner was bale to detect the incomplete test run and restart it
	s.deleteTestRunnerPod(hostName, devCfg, c)
	// new test runner pod will be brought up automatically by k8s
	// verify that its logs are saying it is restarting incomplete test
	s.verifyRestartIncompleteTest(hostName, devCfg, c)

	// verify that the test run event got generated
	s.verifyTestResultEvts(hostName, devCfg, c)

	// verify that the test running label gets removed after the test completed
	log.Print("Verifying that the test running label gets removed after the test completed")
	assert.Eventually(c, func() bool {
		nodes, err := s.clientSet.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{
			LabelSelector: labels.SelectorFromSet(testRunningLabel).String(),
		})
		if err != nil {
			log.Printf("failed to list nodes err %+v", err)
			return false
		}
		if len(nodes.Items) != 0 {
			return false
		}
		log.Printf("Got %d nodes with test running label", len(nodes.Items))
		return true
	}, 600*time.Second, 10*time.Second, "expected test running label removed from node")

	// cleanup
	// need to remove the existing test runner event
	// so that other test runner test cases won't be affected
	s.cleanupTestRunnerEvts(devCfg, c)
}
