/*
Copyright 2024.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package metricsexporter

import (
	"fmt"
	amdv1alpha1 "github.com/pensando/gpu-operator/api/v1alpha1"
	"github.com/rh-ecosystem-edge/kernel-module-management/pkg/labels"
	appsv1 "k8s.io/api/apps/v1"
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/utils/pointer"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"strings"
)

const (
	defaultMetricsExporterImage = "registry.test.pensando.io:5000/device-metrics-exporter/rocm-metrics-exporter:v1"
	metricsPort                 = 5000
)

var metricsExporterLabelPair = []string{"app.kubernetes.io/name", "metrics-exporter"}

//go:generate mockgen -source=metricsexporter.go -package=metricsexporter -destination=mock_metricsexporter.go MetricsExporter
type MetricsExporter interface {
	SetMetricsExporterAsDesired(ds *appsv1.DaemonSet, devConfig *amdv1alpha1.DeviceConfig) error
	SetMetricsServiceAsDesired(svc *v1.Service, devConfig *amdv1alpha1.DeviceConfig) error
}

type metricsExporter struct {
	scheme *runtime.Scheme
}

func NewMetricsExporter(scheme *runtime.Scheme) MetricsExporter {
	return &metricsExporter{
		scheme: scheme,
	}
}

func (nl *metricsExporter) SetMetricsExporterAsDesired(ds *appsv1.DaemonSet, devConfig *amdv1alpha1.DeviceConfig) error {
	if ds == nil {
		return fmt.Errorf("daemon set is not initialized, zero pointer")
	}
	containerVolumeMounts := []v1.VolumeMount{
		{
			Name:      "dev-volume",
			MountPath: "/dev",
		},
		{
			Name:      "sys-volume",
			MountPath: "/sys",
		},
	}

	hostPathDirectory := v1.HostPathDirectory

	volumes := []v1.Volume{
		{
			Name: "dev-volume",
			VolumeSource: v1.VolumeSource{
				HostPath: &v1.HostPathVolumeSource{
					Path: "/dev",
					Type: &hostPathDirectory,
				},
			},
		},
		{
			Name: "sys-volume",
			VolumeSource: v1.VolumeSource{
				HostPath: &v1.HostPathVolumeSource{
					Path: "/sys",
					Type: &hostPathDirectory,
				},
			},
		},
	}

	if devConfig.Spec.MetricsExporter.Config.Name != "" {
		volumes = append(volumes, v1.Volume{
			Name: "metrics-config-volume",
			VolumeSource: v1.VolumeSource{
				ConfigMap: &v1.ConfigMapVolumeSource{
					LocalObjectReference: v1.LocalObjectReference{
						Name: devConfig.Spec.MetricsExporter.Config.Name,
					},
				},
			},
		})

		containerVolumeMounts = append(containerVolumeMounts, v1.VolumeMount{
			Name:      "metrics-config-volume",
			MountPath: "/etc/metrics/",
		})
	}

	matchLabels := map[string]string{
		"daemonset-name":            devConfig.Name,
		metricsExporterLabelPair[0]: metricsExporterLabelPair[1], // in amdgpu namespace
	}
	nodeSelector := map[string]string{}

	if devConfig.Spec.MetricsExporter.Selector != nil {
		nodeSelector = devConfig.Spec.MetricsExporter.Selector
	} else {
		nodeSelector = devConfig.Spec.Selector
	}
	nodeSelector[labels.GetKernelModuleReadyNodeLabel(devConfig.Namespace, devConfig.Name)] = ""

	mxImage := defaultMetricsExporterImage
	if devConfig.Spec.MetricsExporter.Image != "" {
		mxImage = devConfig.Spec.MetricsExporter.Image
	}

	ds.Spec = appsv1.DaemonSetSpec{
		Selector: &metav1.LabelSelector{MatchLabels: matchLabels},
		Template: v1.PodTemplateSpec{
			ObjectMeta: metav1.ObjectMeta{
				Labels: matchLabels,
			},
			Spec: v1.PodSpec{
				Containers: []v1.Container{
					{
						Env: []v1.EnvVar{
							{
								Name: "DS_NODE_NAME",
								ValueFrom: &v1.EnvVarSource{
									FieldRef: &v1.ObjectFieldSelector{
										FieldPath: "spec.nodeName",
									},
								},
							},
						},
						Name:            metricsExporterLabelPair[1] + "-container",
						WorkingDir:      "/root",
						Image:           mxImage,
						SecurityContext: &v1.SecurityContext{Privileged: pointer.Bool(true)},
						VolumeMounts:    containerVolumeMounts,
					},
				},

				PriorityClassName: "system-node-critical",
				NodeSelector:      nodeSelector,
				Volumes:           volumes,
			},
		},
	}

	return controllerutil.SetControllerReference(devConfig, ds, nl.scheme)

}

func (nl *metricsExporter) SetMetricsServiceAsDesired(svc *v1.Service, devConfig *amdv1alpha1.DeviceConfig) error {
	if svc == nil {
		return fmt.Errorf("service  is not initialized, zero pointer")
	}

	svc.Spec = v1.ServiceSpec{
		Selector: map[string]string{
			metricsExporterLabelPair[0]: metricsExporterLabelPair[1],
		},
	}

	switch strings.ToLower(devConfig.Spec.MetricsExporter.ServiceType) {
	case strings.ToLower(string(v1.ServiceTypeNodePort)):
		svc.Spec.Type = v1.ServiceTypeNodePort
		svc.Spec.Ports = []v1.ServicePort{
			{
				Protocol:   v1.ProtocolTCP,
				Port:       metricsPort,
				TargetPort: intstr.FromInt32(metricsPort),
				NodePort:   devConfig.Spec.MetricsExporter.NodePort,
			},
		}
	default:
		svc.Spec.Type = v1.ServiceTypeClusterIP
		svc.Spec.Ports = []v1.ServicePort{
			{
				Protocol:   v1.ProtocolTCP,
				Port:       metricsPort,
				TargetPort: intstr.FromInt32(metricsPort),
			},
		}

	}

	return controllerutil.SetControllerReference(devConfig, svc, nl.scheme)
}
