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
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"

	amdv1alpha1 "github.com/pensando/gpu-operator/api/v1alpha1"
	kmmv1beta1 "github.com/rh-ecosystem-edge/kernel-module-management/api/v1beta1"
	"golang.org/x/exp/maps"
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/discovery"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"
)

const (
	kubeletDevicePluginsVolumeName = "kubelet-device-plugins"
	kubeletDevicePluginsPath       = "/var/lib/kubelet/device-plugins"
	nodeVarLibFirmwarePath         = "/var/lib/firmware"
	gpuDriverModuleName            = "amdgpu"
	ttmModuleName                  = "amdttm"
	kclModuleName                  = "amdkcl"
	imageFirmwarePath              = "firmwareDir/updates"
	kmmNodeVersionLabelTemplate    = "kmm.node.kubernetes.io/version-module.%s.%s"
	defaultDevicePluginImage       = "rocm/k8s-device-plugin"
	defaultOcDriversImageTemplate  = "image-registry.openshift-image-registry.svc:5000/$MOD_NAMESPACE/amdgpu_kmod"
	// start local registry image-registry:5000 in k8s
	defaultDriversImageTemplate = "image-registry:5000/$MOD_NAMESPACE/amdgpu_kmod"
	defaultOcDriversVersion     = "el9-6.1.1"
	defaultRepo                 = "https://repo.radeon.com"
)

var (
	//go:embed dockerfiles/DockerfileTemplate.ubuntu
	dockerfileTemplateUbuntu string
	//go:embed dockerfiles/driversDockerfile.txt
	buildOcDockerfile string
	//go:embed dockerfiles/DockerfileTemplate.rhel
	dockerfileTemplateRHEL string
)

//go:generate mockgen -source=kmmmodule.go -package=kmmmodule -destination=mock_kmmmodule.go KMMModuleAPI
type KMMModuleAPI interface {
	SetNodeVersionLabelAsDesired(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error
	SetBuildConfigMapAsDesired(buildCM *v1.ConfigMap, devConfig *amdv1alpha1.DeviceConfig) error
	SetKMMModuleAsDesired(ctx context.Context, mod *kmmv1beta1.Module, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error
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

func (km *kmmModule) SetNodeVersionLabelAsDesired(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error {
	// for each selected node
	// put the KMM version label given by CR's driver version
	// KMM operator will watch on the version label and manage the kmod upgrade
	versionLabelKey := fmt.Sprintf(kmmNodeVersionLabelTemplate, devConfig.Namespace, devConfig.Name)
	for _, node := range nodes.Items {
		if version, ok := node.Labels[versionLabelKey]; ok && version == devConfig.Spec.DriversVersion {
			// no need to patch the label when it already has the desired value
			continue
		}
		patch := map[string]interface{}{
			"metadata": map[string]interface{}{
				"labels": map[string]string{
					versionLabelKey: devConfig.Spec.DriversVersion,
				},
			},
		}
		patchBytes, err := json.Marshal(patch)
		if err != nil {
			return fmt.Errorf("failed to marshal node label patch: %+v", err)
		}
		rawPatch := client.RawPatch(types.StrategicMergePatchType, patchBytes)
		if err := km.client.Patch(ctx, &node, rawPatch); err != nil {
			return fmt.Errorf("failed to patch node label: %+v", err)
		}
	}
	return nil
}

func (km *kmmModule) SetBuildConfigMapAsDesired(buildCM *v1.ConfigMap, devConfig *amdv1alpha1.DeviceConfig) error {
	if buildCM.Data == nil {
		buildCM.Data = make(map[string]string)
	}
	if km.isOpenShift {
		buildCM.Data["dockerfile"] = buildOcDockerfile
	} else {
		dockerfile, err := resolveDockerfile(buildCM.Name, devConfig)
		if err != nil {
			return err
		}
		buildCM.Data["dockerfile"] = dockerfile
	}
	return controllerutil.SetControllerReference(devConfig, buildCM, km.scheme)
}

var driverLabels = map[string]string{
	"20.04": "focal",
	"22.04": "jammy",
}

func resolveDockerfile(cmName string, devConfig *amdv1alpha1.DeviceConfig) (string, error) {
	splits := strings.SplitN(cmName, "-", 2)
	os := splits[0]
	version := splits[1]
	var dockerfileTemplate string
	switch os {
	case "ubuntu":
		dockerfileTemplate = dockerfileTemplateUbuntu
		driverLabel, present := driverLabels[version]
		if !present {
			return "", fmt.Errorf("invalid ubuntu version, expected to be one of %v", maps.Keys(driverLabels))
		}
		dockerfileTemplate = strings.Replace(dockerfileTemplate, "$$DRIVER_LABEL", driverLabel, -1)
	case "rhel":
		dockerfileTemplate = dockerfileTemplateRHEL
		versionSplits := strings.Split(version, ".")
		dockerfileTemplate = strings.Replace(dockerfileTemplate, "$$MAJOR_VERSION", versionSplits[0], -1)
		if devConfig.Spec.RedhatSubscriptionUsername == "" || devConfig.Spec.RedhatSubscriptionPassword == "" {
			return "", fmt.Errorf("Redhat subscription RedhatSubscriptionUsername and RedhatSubscriptionPassword required")
		}
		dockerfileTemplate = strings.Replace(dockerfileTemplate, "$$REDHAT_SUBSCRIPTION_USERNAME", devConfig.Spec.RedhatSubscriptionUsername, -1)
		dockerfileTemplate = strings.Replace(dockerfileTemplate, "$$REDHAT_SUBSCRIPTION_PASSWORD", devConfig.Spec.RedhatSubscriptionPassword, -1)
	default:
		return "", fmt.Errorf("not supported OS: %s", os)
	}
	resolvedDockerfile := strings.Replace(dockerfileTemplate, "$$VERSION", version, -1)
	return resolvedDockerfile, nil
}

func (km *kmmModule) SetKMMModuleAsDesired(ctx context.Context, mod *kmmv1beta1.Module, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error {
	err := setKMMModuleLoader(ctx, mod, devConfig, km.isOpenShift, nodes)
	if err != nil {
		return fmt.Errorf("failed to set KMM Module: %v", err)
	}
	setKMMDevicePlugin(mod, devConfig)
	return controllerutil.SetControllerReference(devConfig, mod, km.scheme)
}

func setKMMModuleLoader(ctx context.Context, mod *kmmv1beta1.Module, devConfig *amdv1alpha1.DeviceConfig, isOpenshift bool, nodes *v1.NodeList) error {
	kmlog := log.FromContext(ctx)
	kmlog.Info(fmt.Sprintf("isOpenshift %+v", isOpenshift))

	args := &kmmv1beta1.ModprobeArgs{}
	firmwarePath := imageFirmwarePath

	if devConfig.Spec.SkipDrivers {
		args = &kmmv1beta1.ModprobeArgs{
			Load:   []string{"-n"},
			Unload: []string{"-n"},
		}
		firmwarePath = ""
		kmlog.Info("skip driver install/uninstall")
	}

	kernelMappings, err := getKernelMappings(devConfig, isOpenshift, nodes)
	if err != nil {
		return err
	}

	var modLoadingOrder []string
	if !isOpenshift {
		// specify this order fror k8s in order to make sure amdttm and amdkcl was properly cleaned up after deletion of CR
		// module will be loaded in this order: amdkcl, amdttm, amdgpu
		// module will be unloaded in this order: amdgpu, amdttm, amdkcl
		modLoadingOrder = []string{
			gpuDriverModuleName,
			ttmModuleName,
			kclModuleName,
		}
	}

	mod.Spec.ModuleLoader.Container = kmmv1beta1.ModuleLoaderContainerSpec{
		Modprobe: kmmv1beta1.ModprobeSpec{
			ModuleName:          gpuDriverModuleName,
			FirmwarePath:        firmwarePath,
			Args:                args,
			ModulesLoadingOrder: modLoadingOrder,
		},
		Version:        devConfig.Spec.DriversVersion,
		KernelMappings: kernelMappings,
	}
	mod.Spec.ModuleLoader.ServiceAccountName = "amd-gpu-operator-kmm-module-loader"
	mod.Spec.ImageRepoSecret = devConfig.Spec.ImageRepoSecret
	mod.Spec.Selector = getNodeSelector(devConfig)
	return nil
}

func getKernelMappings(devConfig *amdv1alpha1.DeviceConfig, isOpenshift bool, nodes *v1.NodeList) ([]kmmv1beta1.KernelMapping, error) {

	inTreeModuleToRemove := gpuDriverModuleName
	if devConfig.Spec.SkipDrivers {
		inTreeModuleToRemove = ""
	}

	if nodes == nil || len(nodes.Items) == 0 {
		return nil, fmt.Errorf("No nodes found for the label selector %s", MapToLabelSelector(devConfig.Spec.Selector))
	}
	kernelMappings := []kmmv1beta1.KernelMapping{}
	kmSet := map[string]bool{}
	for _, node := range nodes.Items {
		km, err := getKM(devConfig, node, inTreeModuleToRemove, isOpenshift)
		if err != nil {
			return nil, fmt.Errorf("error constructing a kernel mapping for node: %s, err: %v", node.Name, err)
		}
		if kmSet[km.Literal] {
			continue
		}
		kernelMappings = append(kernelMappings, km)
		kmSet[km.Literal] = true
	}
	return kernelMappings, nil
}

func getKM(devConfig *amdv1alpha1.DeviceConfig, node v1.Node, inTreeModuleToRemove string, isOpenShift bool) (kmmv1beta1.KernelMapping, error) {
	driversVersion := devConfig.Spec.DriversVersion
	driversImage := devConfig.Spec.DriversImage
	var err error
	cmName, err := GetCMName(node)
	if err != nil {
		return kmmv1beta1.KernelMapping{}, err
	}

	if isOpenShift {
		if driversVersion == "" {
			driversVersion = defaultOcDriversVersion
		}
		if driversImage == "" {
			driversImage = defaultOcDriversImageTemplate
		}
		driversImage = addNodeInfoSuffixToImageTag(driversImage, cmName, driversVersion)
	} else {
		if driversVersion == "" {
			driversVersion, err = getDefaultDriversVersion(node)
			if err != nil {
				return kmmv1beta1.KernelMapping{}, err
			}
		}
		if driversImage == "" {
			driversImage = defaultDriversImageTemplate
		}
		driversImage = addNodeInfoSuffixToImageTag(driversImage, cmName, driversVersion)
	}

	repoURL := defaultRepo
	if devConfig.Spec.RepoURL != "" {
		repoURL = devConfig.Spec.RepoURL
	}

	return kmmv1beta1.KernelMapping{
		Literal:              node.Status.NodeInfo.KernelVersion,
		ContainerImage:       driversImage,
		InTreeModuleToRemove: inTreeModuleToRemove,
		Build: &kmmv1beta1.Build{
			DockerfileConfigMap: &v1.LocalObjectReference{
				Name: cmName,
			},
			BuildArgs: []kmmv1beta1.BuildArg{
				{
					Name:  "DRIVERS_VERSION",
					Value: driversVersion,
				},
				{
					Name:  "REPO_URL",
					Value: repoURL,
				},
			},
		},
	}, nil
}

func addNodeInfoSuffixToImageTag(imgStr string, cmName, driversVersion string) string {
	// KMM will render and fulfill the value of ${KERNEL_FULL_VERSION}
	tag := cmName + "-${KERNEL_FULL_VERSION}-" + driversVersion
	// tag cannot be more than 128 chars
	if len(tag) > 128 {
		tag = tag[len(tag)-128:]
	}
	return imgStr + ":" + tag
}

func getDefaultDriversVersion(node v1.Node) (string, error) {
	osImageStr := strings.ToLower(node.Status.NodeInfo.OSImage)
	for os, mapper := range defaultDriverversionsMappers {
		if strings.Contains(osImageStr, os) {
			return mapper(osImageStr)
		}
	}
	return "", fmt.Errorf("OS: %s not supported. Should be one of %v", osImageStr, maps.Keys(cmNameMappers))
}

func GetCMName(node v1.Node) (string, error) {
	osImageStr := strings.ToLower(node.Status.NodeInfo.OSImage)

	// sort the key of cmNameMappers
	// make sure in the given OS string, coreos was checked before all other types of RHEL string
	keys := make([]string, 0, len(cmNameMappers))
	for key := range cmNameMappers {
		keys = append(keys, key)
	}
	sort.Strings(keys)

	for _, os := range keys {
		if strings.Contains(osImageStr, os) {
			return cmNameMappers[os](osImageStr), nil
		}
	}

	return "", fmt.Errorf("OS: %s not supported. Should be one of %v", osImageStr, maps.Keys(cmNameMappers))
}

var defaultDriverversionsMappers = map[string]func(fullImageStr string) (string, error){
	"ubuntu": ubuntuDefaultDriverVersionsMapper,
	"rhel": func(f string) (string, error) {
		return "6.1.3", nil // rocm 6.2 could trigger system reboot if we unload + load amdgpu again, let's use 6.1.3 as default version
	},
	"redhat": func(f string) (string, error) {
		return "6.1.3", nil // rocm 6.2 could trigger system reboot if we unload + load amdgpu again, let's use 6.1.3 as default version
	},
	"red hat": func(f string) (string, error) {
		return "6.1.3", nil // rocm 6.2 could trigger system reboot if we unload + load amdgpu again, let's use 6.1.3 as default version
	},
}

func ubuntuDefaultDriverVersionsMapper(fullImageStr string) (string, error) {
	if strings.Contains(fullImageStr, "20.04") {
		return "6.1.3", nil // due to a known ROCM issue, 6.2 unload + load back may cause system reboot, let's use 6.1.3 as default
	}
	if strings.Contains(fullImageStr, "22.04") {
		return "6.1.3", nil // due to a known ROCM issue, 6.2 unload + load back may cause system reboot, let's use 6.1.3 as default
	}
	return "", errors.New("invalid ubuntu version, should be one of [20.04, 22.04]")
}

var cmNameMappers = map[string]func(fullImageStr string) string{
	"ubuntu":  ubuntuCMNameMapper,
	"coreos":  rhelCoreOSNameMapper,
	"rhel":    rhelCMNameMapper,
	"red hat": rhelCMNameMapper,
	"redhat":  rhelCMNameMapper,
}

func rhelCMNameMapper(osImageStr string) string {
	// Check if the input contains "Red Hat Enterprise Linux"
	// Use regex to find the release version
	re := regexp.MustCompile(`(\d+\.\d+)`)
	matches := re.FindStringSubmatch(osImageStr)
	if len(matches) > 1 {
		return fmt.Sprintf("%s-%s", "rhel", matches[1])
	}
	return "rhel-" + osImageStr
}

func rhelCoreOSNameMapper(osImageStr string) string {
	// Check if the input contains "Red Hat Enterprise Linux"
	// Use regex to find the release version
	re := regexp.MustCompile(`(\d+\.\d+)`)
	matches := re.FindStringSubmatch(osImageStr)
	if len(matches) > 1 {
		return fmt.Sprintf("%s-%s", "coreos", matches[1])
	}
	return "coreos-" + osImageStr
}

func ubuntuCMNameMapper(osImageStr string) string {
	splits := strings.Split(osImageStr, " ")
	os := splits[0]
	version := splits[1]
	versionSplits := strings.Split(version, ".")
	trimmedVersion := strings.Join(versionSplits[:2], ".")
	return fmt.Sprintf("%s-%s", os, trimmedVersion)
}

func GetK8SNodes(ls string) (*v1.NodeList, error) {
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
		LabelSelector: ls,
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
			Command: []string{"sh"},
			Args:    []string{"-c", "while [ ! -d /sys/class/kfd ]; do echo \"amdgpu driver is not loaded \"; sleep 1 ;done; ./k8s-device-plugin -logtostderr=true -stderrthreshold=INFO -v=5"},
			Image:   devicePluginImage,
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
