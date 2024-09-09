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

package v1alpha1

import (
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

const (
	AMDPCIVendorID = "1002"
)

// DeviceConfigSpec describes how the AMD GPU operator should enable AMD GPU device for customer's use.
type DeviceConfigSpec struct {
	// if the in-tree driver should be used instead of OOT drivers
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="UseInTreeDrivers",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:useInTreeDrivers"}
	UseInTreeDrivers bool `json:"useInTreeDrivers,omitempty"`

	// skip driver install/uninstall
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="SkipDrivers",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:skipDrivers"}
	SkipDrivers bool `json:"skipDrivers,omitempty"`

	// blacklist amdgpu drivers on the host
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="BlacklistDrivers",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:blacklistDrivers"}
	BlacklistDrivers bool `json:"blacklistDrivers,omitempty"`

	// repo URL, https://repo.radeon.com/amdgpu-install by default
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="RepoURL",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:repoURL"}
	// +optional
	RepoURL string `json:"repoURL,omitempty"`

	// defines image that includes drivers and firmware blobs, don't include tag since it will be fully managed by operator
	// for vanilla k8s the default value is image-registry:5000/$MOD_NAMESPACE/amdgpu_kmod
	// for OpenShift the default value is image-registry.openshift-image-registry.svc:5000/$MOD_NAMESPACE/amdgpu_kmod
	// image tag will be in the format of <linux distro>-<release version>-<kernel version>-<driver version>
	// example tag is coreos-416.94-5.14.0-427.28.1.el9_4.x86_64-el9-6.1.1 and ubuntu-22.04-5.15.0-94-generic-6.1.3
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="DriversImage",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:driversImage"}
	// +optional
	DriversImage string `json:"driversImage,omitempty"`

	// version of the drivers source code, can be used as part of image of dockerfile source image
	// default value for different OS is: ubuntu: 6.1.3, coreOS: el9-6.1.1
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="DriversVersion",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:driversVersion"}
	// +optional
	DriversVersion string `json:"driversVersion,omitempty"`

	// device plugin image
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="DevicePluginImage",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:devicePluginImage"}
	// +optional
	DevicePluginImage string `json:"devicePluginImage,omitempty"`

	// node labeller image
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="NodeLabellerImage",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:nodeLabellerImage"}
	// +optional
	NodeLabellerImage string `json:"nodeLabellerImage,omitempty"`

	// pull secrets used for pull/push images from/to private registry specified in driversImage
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="ImageRepoSecret",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:imageRepoSecret"}
	// +optional
	ImageRepoSecret *v1.LocalObjectReference `json:"imageRepoSecret,omitempty"`

	// ImageSignKeySecret the private key used to sign kernel modules within image
	// necessary for secire boot enabled system
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="ImageSignKeySecret",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:imageSignKeySecret"}
	// +optional
	ImageSignKeySecret *v1.LocalObjectReference `json:"imageSignKeySecret,omitempty"`

	// ImageSignCertSecret the public key used to sign kernel modules within image
	// necessary for secire boot enabled system
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="ImageSignCertSecret",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:imageSignCertSecret"}
	// +optional
	ImageSignCertSecret *v1.LocalObjectReference `json:"imageSignCertSecret,omitempty"`

	// Selector describes on which nodes the GPU Operator should enable the GPU device.
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="Selector",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:selector"}
	// +optional
	Selector map[string]string `json:"selector,omitempty"`

	// RedhatSubscriptionUsername is the username for redhat subscription manager.
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="RedhatSubscriptionUsername",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:redhatSubscriptionUsername"}
	// +optional
	RedhatSubscriptionUsername string `json:"redhatSubscriptionUsername,omitempty"`

	// RedhatSubscriptionPassword is the password for redhat subscription manager.
	//+operator-sdk:csv:customresourcedefinitions:type=spec,displayName="RedhatSubscriptionPassword",xDescriptors={"urn:alm:descriptor:com.amd.deviceconfigs:redhatSubscriptionPassword"}
	// +optional
	RedhatSubscriptionPassword string `json:"redhatSubscriptionPassword,omitempty"`
}

// DeploymentStatus contains the status for a daemonset deployed during
// reconciliation loop
type DeploymentStatus struct {
	// number of nodes that are targeted by the DeviceConfig selector
	//+operator-sdk:csv:customresourcedefinitions:type=status,displayName="NodesMatchingSelectorNumber",xDescriptors="urn:alm:descriptor:com.amd.deviceconfigs:nodesMatchingSelectorNumber"
	NodesMatchingSelectorNumber int32 `json:"nodesMatchingSelectorNumber,omitempty"`
	// number of the pods that should be deployed for daemonset
	//+operator-sdk:csv:customresourcedefinitions:type=status,displayName="DesiredNumber",xDescriptors="urn:alm:descriptor:com.amd.deviceconfigs:desiredNumber"
	DesiredNumber int32 `json:"desiredNumber,omitempty"`
	// number of the actually deployed and running pods
	//+operator-sdk:csv:customresourcedefinitions:type=status,displayName="AvailableNumber",xDescriptors="urn:alm:descriptor:com.amd.deviceconfigs:availableNumber"
	AvailableNumber int32 `json:"availableNumber,omitempty"`
}

// ModuleStatus contains the status of driver module installed by operator on the node
type ModuleStatus struct {
	ContainerImage     string `json:"containerImage,omitempty"`
	KernelVersion      string `json:"kernelVersion,omitempty"`
	LastTransitionTime string `json:"lastTransitionTime,omitempty"`
}

// DeviceConfigStatus defines the observed state of Module.
type DeviceConfigStatus struct {
	// DevicePlugin contains the status of the Device Plugin deployment
	DevicePlugin DeploymentStatus `json:"devicePlugin,omitempty"`
	// Driver contains the status of the Drivers deployment
	Drivers DeploymentStatus `json:"driver,omitempty"`
	// NodeModuleStatus contains per node status of driver module installation
	//+operator-sdk:csv:customresourcedefinitions:type=status,displayName="NodeModuleStatus",xDescriptors="urn:alm:descriptor:com.amd.deviceconfigs:nodeModuleStatus"
	NodeModuleStatus map[string]ModuleStatus `json:"nodeModuleStatus,omitempty"`
}

//+kubebuilder:object:root=true
//+kubebuilder:resource:scope=Namespaced,shortName=gpue
//+kubebuilder:subresource:status

// DeviceConfig describes how to enable AMD GPU device
// +operator-sdk:csv:customresourcedefinitions:displayName="DeviceConfig",resources={{Module,v1beta1,modules.kmm.sigs.x-k8s.io},{Daemonset,v1,apps}}
type DeviceConfig struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   DeviceConfigSpec   `json:"spec,omitempty"`
	Status DeviceConfigStatus `json:"status,omitempty"`
}

//+kubebuilder:object:root=true

// DeviceConfigList contains a list of DeviceConfigs
type DeviceConfigList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []DeviceConfig `json:"items"`
}

func init() {
	SchemeBuilder.Register(&DeviceConfig{}, &DeviceConfigList{})
}
