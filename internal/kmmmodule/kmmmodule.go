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

package kmmmodule

import (
	"context"
	_ "embed"
	"fmt"
	"strings"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/discovery"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	ctrl "sigs.k8s.io/controller-runtime"

	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	amdv1alpha1 "github.com/pensando/gpu-operator/api/v1alpha1"
	kmmv1beta1 "github.com/rh-ecosystem-edge/kernel-module-management/api/v1beta1"
)

const (
	kubeletDevicePluginsVolumeName = "kubelet-device-plugins"
	kubeletDevicePluginsPath       = "/var/lib/kubelet/device-plugins"
	nodeVarLibFirmwarePath         = "/var/lib/firmware"
	gpuDriverModuleName            = "amdgpu"
	imageFirmwarePath              = "firmwareDir/updates"
	defaultDevicePluginImage       = "rocm/k8s-device-plugin"
	defaultOcDriversImageTemplate  = "image-registry.openshift-image-registry.svc:5000/$MOD_NAMESPACE/amd_gpu_kmm_modules:%s"
	// start local registry image-registry:5000 in k8s
	defaultDriversImageTemplate = "image-registry:5000/$MOD_NAMESPACE/amd_gpu_kmm_modules:%s-$KERNEL_FULL_VERSION`"
	defaultOcDriversVersion     = "el9-6.1.1"
	defaultDriversVersion       = "6.1.3"
)

var (
	//go:embed dockerfiles/amdDriversDockerfile.txt
	buildDockerfile string
	//go:embed dockerfiles/driversDockerfile.txt
	buildOcDockerfile string
)

//go:generate mockgen -source=kmmmodule.go -package=kmmmodule -destination=mock_kmmmodule.go KMMModuleAPI
type KMMModuleAPI interface {
	SetBuildConfigMapAsDesired(buildCM *v1.ConfigMap, devConfig *amdv1alpha1.DeviceConfig) error
	SetKMMModuleAsDesired(mod *kmmv1beta1.Module, devConfig *amdv1alpha1.DeviceConfig) error
}

type kmmModule struct {
	client      client.Client
	scheme      *runtime.Scheme
	isOpenShift bool
}

func NewKMMModule(client client.Client, scheme *runtime.Scheme) KMMModuleAPI {
	return &kmmModule{
		client:      client,
		scheme:      scheme,
		isOpenShift: isOpenshift(),
	}
}

func isOpenshift() bool {
	if dc, err := discovery.NewDiscoveryClientForConfig(ctrl.GetConfigOrDie()); err == nil {
		if gplist, err := dc.ServerGroups(); err == nil {
			for _, gp := range gplist.Groups {
				if gp.Name == "route.openshift.io" {
					return true
				}
			}
		}
	}
	return false
}

func (km *kmmModule) SetBuildConfigMapAsDesired(buildCM *v1.ConfigMap, devConfig *amdv1alpha1.DeviceConfig) error {
	if buildCM.Data == nil {
		buildCM.Data = make(map[string]string)
	}
	if km.isOpenShift {
		buildCM.Data["dockerfile"] = buildOcDockerfile
	} else {
		dockerfile, err := resolveDockerfile(buildCM.Name)
		if err != nil {
			return err
		}
		buildCM.Data["dockerfile"] = dockerfile
	}
	return controllerutil.SetControllerReference(devConfig, buildCM, km.scheme)
}

func resolveDockerfile(cmName string) (string, error) {
	splits := strings.SplitN(cmName, "-", 2)
	os := splits[0]
	version := splits[1]
	var dockerfileTemplate string
	switch os {
	case "ubuntu":
		dockerfileTemplate = buildDockerfile
	//TODO: add more mappings here
	default:
		return "", fmt.Errorf("no dockerfile found for OS: %s", os)
	}
	resolvedDockerfile := strings.Replace(dockerfileTemplate, "$$VERSION", version, -1)
	return resolvedDockerfile, nil
}

func (km *kmmModule) SetKMMModuleAsDesired(mod *kmmv1beta1.Module, devConfig *amdv1alpha1.DeviceConfig) error {
	err := setKMMModuleLoader(mod, devConfig, km.isOpenShift)
	if err != nil {
		return fmt.Errorf("failed to set KMM Module: %v", err)
	}
	setKMMDevicePlugin(mod, devConfig)
	return controllerutil.SetControllerReference(devConfig, mod, km.scheme)
}

func setKMMModuleLoader(mod *kmmv1beta1.Module, devConfig *amdv1alpha1.DeviceConfig, isOpenshift bool) error {
	kernelMappings, err := getKernelMappings(devConfig, isOpenshift)
	if err != nil {
		return err
	}
	mod.Spec.ModuleLoader.Container = kmmv1beta1.ModuleLoaderContainerSpec{
		Modprobe: kmmv1beta1.ModprobeSpec{
			ModuleName:   gpuDriverModuleName,
			FirmwarePath: imageFirmwarePath,
		},
		KernelMappings: kernelMappings,
	}
	mod.Spec.ModuleLoader.ServiceAccountName = "amd-gpu-operator-kmm-module-loader"
	mod.Spec.ImageRepoSecret = devConfig.Spec.ImageRepoSecret
	mod.Spec.Selector = getNodeSelector(devConfig)
	return nil
}

func getKernelMappings(devConfig *amdv1alpha1.DeviceConfig, isOpenshift bool) ([]kmmv1beta1.KernelMapping, error) {
	driversVersion := devConfig.Spec.DriversVersion
	if driversVersion == "" {
		if isOpenshift {
			driversVersion = defaultOcDriversVersion
		} else {
			driversVersion = defaultDriversVersion
		}
	}

	driversImage := devConfig.Spec.DriversImage
	if driversImage == "" {
		if isOpenshift {
			driversImage = fmt.Sprintf(defaultOcDriversImageTemplate, driversVersion)
		} else {
			driversImage = fmt.Sprintf(defaultDriversImageTemplate, driversVersion)
		}
	}

	if isOpenshift {
		return []kmmv1beta1.KernelMapping{
			{
				Regexp:               "^.+$",
				ContainerImage:       driversImage,
				InTreeModuleToRemove: gpuDriverModuleName,
				Build: &kmmv1beta1.Build{
					DockerfileConfigMap: &v1.LocalObjectReference{
						Name: getDockerfileCMName(devConfig),
					},
					BuildArgs: []kmmv1beta1.BuildArg{
						{
							Name:  "DRIVERS_VERSION",
							Value: driversVersion,
						},
					},
				},
			},
		}, nil
	}

	nodes, err := GetK8SNodes(devConfig)
	if err != nil {
		// unable to fetch nodes
		return nil, err
	}
	if nodes == nil || len(nodes.Items) == 0 {
		return nil, fmt.Errorf("No nodes found for the label selector %s", MapToLabelSelector(devConfig.Spec.Selector))
	}
	kernelMappings := []kmmv1beta1.KernelMapping{}
	kmSet := map[string]bool{}
	for _, node := range nodes.Items {
		km := getKM(driversImage, driversVersion, node)
		if kmSet[km.Literal] {
			continue
		}
		kernelMappings = append(kernelMappings, km)
		kmSet[km.Literal] = true
	}
	return kernelMappings, nil
}

func getKM(driversImage, driversVersion string, node v1.Node) kmmv1beta1.KernelMapping {
	return kmmv1beta1.KernelMapping{
		Literal:              node.Status.NodeInfo.KernelVersion,
		ContainerImage:       driversImage,
		InTreeModuleToRemove: gpuDriverModuleName,
		Build: &kmmv1beta1.Build{
			DockerfileConfigMap: &v1.LocalObjectReference{
				Name: GetCMName(node),
			},
			BuildArgs: []kmmv1beta1.BuildArg{
				{
					Name:  "DRIVERS_VERSION",
					Value: driversVersion,
				},
			},
		},
	}
}

func GetCMName(node v1.Node) string {
	osImage := strings.ToLower(node.Status.NodeInfo.OSImage)
	splits := strings.Split(osImage, " ")
	os := splits[0]
	version := splits[1]
	versionSplits := strings.Split(version, ".")
	trimmedVersion := strings.Join(versionSplits[:2], ".")
	return fmt.Sprintf("%s-%s", os, trimmedVersion)
}

func GetK8SNodes(devConfig *amdv1alpha1.DeviceConfig) (*v1.NodeList, error) {
	config, err := rest.InClusterConfig()
	if err != nil {
		return nil, err
	}
	// creates the clientset
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, err
	}
	options := metav1.ListOptions{
		LabelSelector: MapToLabelSelector(devConfig.Spec.Selector),
	}
	return clientset.CoreV1().Nodes().List(context.TODO(), options)
}

func MapToLabelSelector(selector map[string]string) string {
	selectorSlice := make([]string, 0)
	for k, v := range selector {
		selectorSlice = append(selectorSlice, fmt.Sprintf("%s=%s", k, v))
	}
	return strings.Join(selectorSlice, ",")
}

func setKMMDevicePlugin(mod *kmmv1beta1.Module, devConfig *amdv1alpha1.DeviceConfig) {
	devicePluginImage := devConfig.Spec.DevicePluginImage
	if devicePluginImage == "" {
		devicePluginImage = defaultDevicePluginImage
	}
	hostPathDirectory := v1.HostPathDirectory
	mod.Spec.DevicePlugin = &kmmv1beta1.DevicePluginSpec{
		ServiceAccountName: "amd-gpu-operator-kmm-device-plugin",
		Container: kmmv1beta1.DevicePluginContainerSpec{
			Image: devicePluginImage,
			VolumeMounts: []v1.VolumeMount{
				{
					Name:      "sys",
					MountPath: "/sys",
				},
			},
		},
		Volumes: []v1.Volume{
			{
				Name: "sys",
				VolumeSource: v1.VolumeSource{
					HostPath: &v1.HostPathVolumeSource{
						Path: "/sys",
						Type: &hostPathDirectory,
					},
				},
			},
		},
	}
}

func getDockerfileCMName(devConfig *amdv1alpha1.DeviceConfig) string {
	return "dockerfile-" + devConfig.Name
}

func getNodeSelector(devConfig *amdv1alpha1.DeviceConfig) map[string]string {
	if devConfig.Spec.Selector != nil {
		return devConfig.Spec.Selector
	}

	ns := make(map[string]string, 0)
	ns["feature.node.kubernetes.io/amd-gpu"] = "true"
	return ns
}
