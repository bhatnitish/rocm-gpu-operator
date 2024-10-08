/*
Copyright 2022.

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

package metricsexporter

import (
	"fmt"
	"strings"

	amdv1alpha1 "github.com/pensando/gpu-operator/api/v1alpha1"
	"github.com/rh-ecosystem-edge/kernel-module-management/pkg/labels"
	appsv1 "k8s.io/api/apps/v1"
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/utils/pointer"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

const (
	defaultMetricsExporterImage = "registry.test.pensando.io:5000/device-metrics-exporter/rocm-metrics-exporter:v1"
	defaultKubeRbacProxyImage   = "quay.io/brancz/kube-rbac-proxy:v0.18.1"
	servicePort                 = 5000
	rbacServicePort             = 8443
	nobodyUser                  = 65532
	ExporterName                = "metrics-exporter"
	KubeRbacName                = "kube-rbac-proxy"
	defaultSAName               = "amd-gpu-operator-metrics-exporter"
	kubeRbacSAName              = "amd-gpu-operator-metrics-exporter-rbac-proxy"
)

var metricsExporterLabelPair = []string{"app.kubernetes.io/name", ExporterName}

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
	mSpec := devConfig.Spec.MetricsExporter
	containerVolumeMounts := []v1.VolumeMount{
		{
			Name:      "dev-volume",
			MountPath: "/dev",
		},
		{
			Name:      "sys-volume",
			MountPath: "/sys",
		},
		{
			Name:      "pod-resources",
			MountPath: "/var/lib/kubelet/pod-resources",
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
		{
			Name: "pod-resources",
			VolumeSource: v1.VolumeSource{
				HostPath: &v1.HostPathVolumeSource{
					Path: "/var/lib/kubelet/pod-resources",
					Type: &hostPathDirectory,
				},
			},
		},
	}

	if mSpec.Config.Name != "" {
		volumes = append(volumes, v1.Volume{
			Name: "metrics-config-volume",
			VolumeSource: v1.VolumeSource{
				ConfigMap: &v1.ConfigMapVolumeSource{
					LocalObjectReference: v1.LocalObjectReference{
						Name: mSpec.Config.Name,
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
	var nodeSelector map[string]string

	if mSpec.Selector != nil {
		nodeSelector = mSpec.Selector
	} else {
		nodeSelector = devConfig.Spec.Selector
	}
	nodeSelector[labels.GetKernelModuleReadyNodeLabel(devConfig.Namespace, devConfig.Name)] = ""

	mxImage := defaultMetricsExporterImage
	if mSpec.Image != "" {
		mxImage = mSpec.Image
	}

	containers := []v1.Container{
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
				{
					Name:  "METRICS_EXPORTER_PORT",
					Value: fmt.Sprintf("%v", int32(servicePort)),
				},
			},
			Name:            ExporterName + "-container",
			WorkingDir:      "/root",
			Image:           mxImage,
			SecurityContext: &v1.SecurityContext{Privileged: pointer.Bool(true)},
			VolumeMounts:    containerVolumeMounts,
		},
	}

	serviceaccount := defaultSAName

	if mSpec.RbacConfig.Enable {
		// Bind service port to localhost only
		containers[0].Args = []string{"--bind=127.0.0.1:" + fmt.Sprintf("%v", int32(servicePort))}

		kubeImage := defaultKubeRbacProxyImage
		if mSpec.RbacConfig.Image != "" {
			kubeImage = mSpec.RbacConfig.Image
		}

		args := []string{
			"--upstream=http://127.0.0.1:" + fmt.Sprintf("%v", int32(servicePort)),
			"--logtostderr=true",
			"--v=10",
		}

		volumeMounts := []v1.VolumeMount{}
		if mSpec.RbacConfig.DisableHttps {
			args = append(args, "--insecure-listen-address=0.0.0.0:"+fmt.Sprintf("%v", int32(rbacServicePort)))
		} else {
			args = append(args, "--secure-listen-address=0.0.0.0:"+fmt.Sprintf("%v", int32(rbacServicePort)))

			// Load the tls-certs if provided
			if mSpec.RbacConfig.Secret != nil {
				volumes = append(volumes, v1.Volume{
					Name: "tls-certs",
					VolumeSource: v1.VolumeSource{
						Secret: &v1.SecretVolumeSource{
							SecretName: mSpec.RbacConfig.Secret.Name,
						},
					},
				})

				volumeMounts = append(volumeMounts, v1.VolumeMount{
					Name:      "tls-certs",
					MountPath: "/etc/tls",
					ReadOnly:  true,
				})

				args = append(args, "--tls-cert-file=/etc/tls/tls.crt")
				args = append(args, "--tls-private-key-file=/etc/tls/tls.key")
			}
		}

		containers = append(containers, v1.Container{
			Name:  KubeRbacName + "-container",
			Image: kubeImage,
			SecurityContext: &v1.SecurityContext{
				RunAsUser:                pointer.Int64(nobodyUser),
				AllowPrivilegeEscalation: pointer.Bool(false),
			},
			Args:         args,
			VolumeMounts: volumeMounts,
		})

		// Provide elevated privilege only when rbac-proxy is enabled
		serviceaccount = kubeRbacSAName
	}

	ds.Spec = appsv1.DaemonSetSpec{
		Selector: &metav1.LabelSelector{MatchLabels: matchLabels},
		Template: v1.PodTemplateSpec{
			ObjectMeta: metav1.ObjectMeta{
				Labels: matchLabels,
			},
			Spec: v1.PodSpec{
				Containers:         containers,
				PriorityClassName:  "system-node-critical",
				NodeSelector:       nodeSelector,
				ServiceAccountName: serviceaccount,
				Volumes:            volumes,
			},
		},
	}
	return controllerutil.SetControllerReference(devConfig, ds, nl.scheme)

}

func (nl *metricsExporter) SetMetricsServiceAsDesired(svc *v1.Service, devConfig *amdv1alpha1.DeviceConfig) error {
	mSpec := devConfig.Spec.MetricsExporter
	if svc == nil {
		return fmt.Errorf("service  is not initialized, zero pointer")
	}

	svc.Spec = v1.ServiceSpec{
		Selector: map[string]string{
			metricsExporterLabelPair[0]: metricsExporterLabelPair[1],
		},
	}

	targetPort := int32(servicePort)
	if mSpec.RbacConfig.Enable {
		targetPort = int32(rbacServicePort)
	}

	clusterIPPort := int32(servicePort)
	if mSpec.ClusterIPPort > 0 {
		clusterIPPort = mSpec.ClusterIPPort
	}

	switch strings.ToLower(mSpec.ServiceType) {
	case strings.ToLower(string(v1.ServiceTypeNodePort)):
		svc.Spec.Type = v1.ServiceTypeNodePort
		svc.Spec.ExternalTrafficPolicy = v1.ServiceExternalTrafficPolicyLocal
		svc.Spec.Ports = []v1.ServicePort{
			{
				Protocol:   v1.ProtocolTCP,
				Port:       clusterIPPort,
				TargetPort: intstr.FromInt32(targetPort),
				NodePort:   mSpec.NodePort,
			},
		}
	default:
		svc.Spec.Type = v1.ServiceTypeClusterIP
		svc.Spec.Ports = []v1.ServicePort{
			{
				Protocol:   v1.ProtocolTCP,
				Port:       clusterIPPort,
				TargetPort: intstr.FromInt32(targetPort),
			},
		}

	}

	return controllerutil.SetControllerReference(devConfig, svc, nl.scheme)
}
