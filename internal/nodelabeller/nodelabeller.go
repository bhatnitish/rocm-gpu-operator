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

package nodelabeller

import (
	"fmt"

	amdv1alpha1 "github.com/pensando/gpu-operator/api/v1alpha1"
	"github.com/rh-ecosystem-edge/kernel-module-management/pkg/labels"
	appsv1 "k8s.io/api/apps/v1"
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/utils/pointer"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

//go:generate mockgen -source=nodelabeller.go -package=nodelabeller -destination=mock_nodelabeller.go NodeLabeller
type NodeLabeller interface {
	SetNodeLabellerAsDesired(ds *appsv1.DaemonSet, devConfig *amdv1alpha1.DeviceConfig) error
}

type nodeLabeller struct {
	scheme *runtime.Scheme
}

func NewNodeLabeller(scheme *runtime.Scheme) NodeLabeller {
	return &nodeLabeller{
		scheme: scheme,
	}
}

func (nl *nodeLabeller) SetNodeLabellerAsDesired(ds *appsv1.DaemonSet, devConfig *amdv1alpha1.DeviceConfig) error {
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

	initVolumeMounts := []v1.VolumeMount{
		{
			Name:      "etc-volume",
			MountPath: "/host-etc",
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

	initContainers := []v1.Container{}
	if devConfig.Spec.BlacklistDrivers {
		volumes = append(volumes, v1.Volume{
			Name: "etc-volume",
			VolumeSource: v1.VolumeSource{
				HostPath: &v1.HostPathVolumeSource{
					Path: "/etc",
					Type: &hostPathDirectory,
				},
			},
		})

		initContainers = []v1.Container{
			{
				Name:            "blacklist-driver",
				Image:           "busybox:1.36",
				Command:         []string{"sh", "-c", "echo \"# added by gpu operator \nblacklist amdgpu\" > /host-etc/modprobe.d/blacklist-amdgpu.conf"},
				ImagePullPolicy: v1.PullAlways,
				VolumeMounts:    initVolumeMounts,
			},
		}
	}

	matchLabels := map[string]string{"daemonset-name": devConfig.Name}
	nodeSelector := map[string]string{labels.GetKernelModuleReadyNodeLabel(devConfig.Namespace, devConfig.Name): ""}
	ds.Spec = appsv1.DaemonSetSpec{
		Selector: &metav1.LabelSelector{MatchLabels: matchLabels},
		Template: v1.PodTemplateSpec{
			ObjectMeta: metav1.ObjectMeta{
				Labels: matchLabels,
				//Finalizers: []string{constants.NodeLabelerFinalizer},
			},
			Spec: v1.PodSpec{
				InitContainers: initContainers,
				Containers: []v1.Container{
					{
						Args:    []string{"-c", "while [ ! -d /sys/class/kfd ]; do echo \"amdgpu driver is not loaded \"; sleep 1 ;done;./k8s-node-labeller -vram -cu-count -simd-count -device-id -family"},
						Command: []string{"sh"},
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
						Name:            "node-labeller-container",
						WorkingDir:      "/root",
						Image:           "rocm/k8s-device-plugin:labeller-latest",
						ImagePullPolicy: v1.PullAlways,
						SecurityContext: &v1.SecurityContext{Privileged: pointer.Bool(true)},
						VolumeMounts:    containerVolumeMounts,
					},
				},
				PriorityClassName:  "system-node-critical",
				NodeSelector:       nodeSelector,
				ServiceAccountName: "amd-gpu-operator-node-labeller",
				Volumes:            volumes,
			},
		},
	}

	return controllerutil.SetControllerReference(devConfig, ds, nl.scheme)
}
