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

package controllers

import (
	"context"
	"fmt"
	"github.com/rh-ecosystem-edge/kernel-module-management/pkg/labels"
	"strings"

	amdv1alpha1 "github.com/pensando/gpu-operator/api/v1alpha1"
	"github.com/pensando/gpu-operator/internal/kmmmodule"
	"github.com/pensando/gpu-operator/internal/nodelabeller"
	kmmv1beta1 "github.com/rh-ecosystem-edge/kernel-module-management/api/v1beta1"
	appsv1 "k8s.io/api/apps/v1"
	v1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"
)

const (
	DeviceConfigReconcilerName = "DriverAndPluginReconciler"
	deviceConfigFinalizer      = "amd.node.kubernetes.io/deviceconfig-finalizer"
)

// ModuleReconciler reconciles a Module object
type DeviceConfigReconciler struct {
	helper deviceConfigReconcilerHelperAPI
}

func NewDeviceConfigReconciler(
	client client.Client,
	kmmHandler kmmmodule.KMMModuleAPI,
	nlHandler nodelabeller.NodeLabeller) *DeviceConfigReconciler {
	helper := newDeviceConfigReconcilerHelper(client, kmmHandler, nlHandler)
	return &DeviceConfigReconciler{
		helper: helper,
	}
}

// SetupWithManager sets up the controller with the Manager.
//  1. Owns() will tell the manager that if any Module or Daemonset object or their status got updated
//     the DeviceConfig object in their ref field need to be reconciled
//  2. findDeviceConfigsForNMC: when a NMC changed, only trigger reconcile for related DeviceConfig
func (r *DeviceConfigReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&amdv1alpha1.DeviceConfig{}).
		Owns(&kmmv1beta1.Module{}).
		Owns(&appsv1.DaemonSet{}).
		Named(DeviceConfigReconcilerName).
		Watches(
			&kmmv1beta1.NodeModulesConfig{},
			handler.EnqueueRequestsFromMapFunc(r.helper.findDeviceConfigsForNMC),
			builder.WithPredicates(predicate.ResourceVersionChangedPredicate{}),
		).
		Complete(r)
}

//+kubebuilder:rbac:groups=amd.com,resources=deviceconfigs,verbs=get;list;watch;create;patch;update
//+kubebuilder:rbac:groups=amd.com,resources=deviceconfigs/status,verbs=get;patch;update
//+kubebuilder:rbac:groups=amd.com,resources=deviceconfigs/finalizers,verbs=update
//+kubebuilder:rbac:groups=kmm.sigs.x-k8s.io,resources=modules,verbs=get;list;watch;create;patch;update;delete
//+kubebuilder:rbac:groups=kmm.sigs.x-k8s.io,resources=modules/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=kmm.sigs.x-k8s.io,resources=modules/finalizers,verbs=get;update;watch
//+kubebuilder:rbac:groups=kmm.sigs.x-k8s.io,resources=nodemodulesconfigs,verbs=get;list;watch
//+kubebuilder:rbac:groups=kmm.sigs.x-k8s.io,resources=nodemodulesconfigs/status,verbs=get;list;watch
//+kubebuilder:rbac:groups=kmm.sigs.x-k8s.io,resources=nodemodulesconfigs/finalizers,verbs=get;update;watch
//+kubebuilder:rbac:groups=core,resources=configmaps,verbs=create;delete;get;list;patch;watch;create
//+kubebuilder:rbac:groups=core,resources=nodes,verbs=get;patch;list;watch
//+kubebuilder:rbac:groups=core,resources=nodes/status,verbs=get;update;watch
//+kubebuilder:rbac:groups=core,resources=nodes/finalizers,verbs=get;update;watch
//+kubebuilder:rbac:groups=apps,resources=daemonsets,verbs=create;delete;get;list;patch;watch
//+kubebuilder:rbac:groups=apps,resources=daemonsets/status,verbs=create;delete;get;list;patch;watch
//+kubebuilder:rbac:groups=apps,resources=daemonsets/finalizers,verbs=create;get;update;watch

func (r *DeviceConfigReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	res := ctrl.Result{}

	logger := log.FromContext(ctx)

	devConfig, err := r.helper.getRequestedDeviceConfig(ctx, req.NamespacedName)
	if err != nil {
		if k8serrors.IsNotFound(err) || strings.Contains(err.Error(), "not found") {
			logger.Info("DeviceConfig CR deleted")
			return ctrl.Result{}, nil
		}
		return res, fmt.Errorf("failed to get the requested %s CR: %v", req.NamespacedName, err)
	}

	if devConfig.GetDeletionTimestamp() != nil {
		// DeviceConfig is being deleted
		err = r.helper.finalizeDeviceConfig(ctx, devConfig)
		if err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to finalize DeviceConfig %s: %v", req.NamespacedName, err)
		}
		return ctrl.Result{}, nil
	}

	err = r.helper.setFinalizer(ctx, devConfig)
	if err != nil {
		return res, fmt.Errorf("failed to set finalizer for DeviceConfig %s: %v", req.NamespacedName, err)
	}

	nodes, err := kmmmodule.GetK8SNodes(kmmmodule.MapToLabelSelector(devConfig.Spec.Selector))
	if err != nil {
		return res, fmt.Errorf("failed to list Node for DeviceConfig %s: %v", req.NamespacedName, err)
	}

	logger.Info("start build configmap reconciliation")
	err = r.helper.handleBuildConfigMap(ctx, devConfig, nodes)
	if err != nil {
		return res, fmt.Errorf("failed to handle build ConfigMap for DeviceConfig %s: %v", req.NamespacedName, err)
	}

	logger.Info("start KMM reconciliation")
	err = r.helper.handleKMMModule(ctx, devConfig, nodes)
	if err != nil {
		return res, fmt.Errorf("failed to handle KMM module for DeviceConfig %s: %v", req.NamespacedName, err)
	}

	logger.Info("start kmm mod version label reconciliation")
	err = r.helper.handleKMMVersionLabel(ctx, devConfig, nodes)
	if err != nil {
		return res, fmt.Errorf("failed to handle kmm mod version label for DeviceConfig %s: %v", req.NamespacedName, err)
	}

	logger.Info("start node labeller reconciliation")
	err = r.helper.handleNodeLabeller(ctx, devConfig)
	if err != nil {
		return res, fmt.Errorf("failed to handle node labeller for DeviceConfig %s: %v", req.NamespacedName, err)
	}

	err = r.helper.updateDeviceConfigStatus(ctx, devConfig, nodes)
	if err != nil {
		return res, fmt.Errorf("failed to update status for DeviceConfig %s: %v", req.NamespacedName, err)
	}
	return res, nil
}

//go:generate mockgen -source=device_config_reconciler.go -package=controllers -destination=mock_device_config_reconciler.go deviceConfigReconcilerHelperAPI
type deviceConfigReconcilerHelperAPI interface {
	getRequestedDeviceConfig(ctx context.Context, namespacedName types.NamespacedName) (*amdv1alpha1.DeviceConfig, error)
	getDeviceConfigOwnedKMMModule(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig) (*kmmv1beta1.Module, error)
	updateDeviceConfigStatus(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error
	finalizeDeviceConfig(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig) error
	findDeviceConfigsForNMC(ctx context.Context, nmc client.Object) []reconcile.Request
	setFinalizer(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig) error
	handleKMMModule(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error
	handleKMMVersionLabel(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error
	handleBuildConfigMap(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error
	handleNodeLabeller(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig) error
}

type deviceConfigReconcilerHelper struct {
	client     client.Client
	kmmHandler kmmmodule.KMMModuleAPI
	nlHandler  nodelabeller.NodeLabeller
}

func newDeviceConfigReconcilerHelper(client client.Client,
	kmmHandler kmmmodule.KMMModuleAPI,
	nlHandler nodelabeller.NodeLabeller) deviceConfigReconcilerHelperAPI {
	return &deviceConfigReconcilerHelper{
		client:     client,
		kmmHandler: kmmHandler,
		nlHandler:  nlHandler,
	}
}

func (dcrh *deviceConfigReconcilerHelper) getRequestedDeviceConfig(ctx context.Context, namespacedName types.NamespacedName) (*amdv1alpha1.DeviceConfig, error) {
	devConfig := amdv1alpha1.DeviceConfig{}

	if err := dcrh.client.Get(ctx, namespacedName, &devConfig); err != nil {
		return nil, fmt.Errorf("failed to get DeviceConfig %s: %v", namespacedName, err)
	}
	return &devConfig, nil
}

// findDeviceConfigsForNMC when a NMC changed, only trigger reconcile for related DeviceConfig
func (drch *deviceConfigReconcilerHelper) findDeviceConfigsForNMC(ctx context.Context, nmc client.Object) []reconcile.Request {
	reqs := []reconcile.Request{}
	logger := log.FromContext(ctx)
	nmcObj, ok := nmc.(*kmmv1beta1.NodeModulesConfig)
	if !ok {
		logger.Error(fmt.Errorf("failed to convert object %+v to NodeModulesConfig", nmc), "")
		return reqs
	}
	if nmcObj.Status.Modules != nil && len(nmcObj.Status.Modules) > 0 {
		for _, module := range nmcObj.Status.Modules {
			reqs = append(reqs, reconcile.Request{
				NamespacedName: types.NamespacedName{
					Namespace: module.Namespace,
					Name:      module.Name,
				},
			})
		}
	}
	return reqs
}

func (dcrh *deviceConfigReconcilerHelper) updateDeviceConfigStatus(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error {
	// fetch DeviceConfig-owned custom resource
	// then retrieve its status and put it to DeviceConfig's status fields
	kmmModuleObj, err := dcrh.getDeviceConfigOwnedKMMModule(ctx, devConfig)
	if err != nil {
		return fmt.Errorf("failed to fetch owned kmm module for DeviceConfig %+v: %+v",
			types.NamespacedName{Namespace: devConfig.Namespace, Name: devConfig.Name}, err)
	}
	if kmmModuleObj != nil {
		devConfig.Status = amdv1alpha1.DeviceConfigStatus{
			DevicePlugin: amdv1alpha1.DeploymentStatus{
				NodesMatchingSelectorNumber: kmmModuleObj.Status.DevicePlugin.NodesMatchingSelectorNumber,
				DesiredNumber:               kmmModuleObj.Status.DevicePlugin.DesiredNumber,
				AvailableNumber:             kmmModuleObj.Status.DevicePlugin.AvailableNumber,
			},
			Drivers: amdv1alpha1.DeploymentStatus{
				NodesMatchingSelectorNumber: kmmModuleObj.Status.ModuleLoader.DesiredNumber,
				DesiredNumber:               kmmModuleObj.Status.ModuleLoader.DesiredNumber,
				AvailableNumber:             kmmModuleObj.Status.ModuleLoader.AvailableNumber,
			},
		}
	}

	// fetch latest node modules config, push their status back to DeviceConfig's status fields
	err = dcrh.updateDeviceConfigNodeStatus(ctx, devConfig, nodes)
	if err != nil {
		return err
	}

	// get the latest version of object right before update
	// to avoid issue "the object has been modified; please apply your changes to the latest version and try again"
	latestObj, err := dcrh.getRequestedDeviceConfig(ctx, types.NamespacedName{Namespace: devConfig.Namespace, Name: devConfig.Name})
	if err != nil {
		return err
	}
	devConfig.Status.DeepCopyInto(&latestObj.Status)
	if err := dcrh.client.Status().Update(ctx, latestObj); err != nil {
		return err
	}
	return nil
}

func (dcrh *deviceConfigReconcilerHelper) getDeviceConfigOwnedKMMModule(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig) (*kmmv1beta1.Module, error) {
	module := kmmv1beta1.Module{}
	namespacedName := types.NamespacedName{Namespace: devConfig.Namespace, Name: devConfig.Name}
	if err := dcrh.client.Get(ctx, namespacedName, &module); err != nil {
		return nil, fmt.Errorf("failed to get KMM Module %s: %v", namespacedName, err)
	}
	return &module, nil
}

func (dcrh *deviceConfigReconcilerHelper) updateDeviceConfigNodeStatus(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error {
	logger := log.FromContext(ctx)
	devConfig.Status.NodeModuleStatus = map[string]amdv1alpha1.ModuleStatus{}

	// for each node, fetch its status of modules configured by given DeviceConfig
	for _, node := range nodes.Items {
		// if there is no module configured for given node
		// the info under that node name will be empty
		// then it will be clear to see which node didn't get module configured
		devConfig.Status.NodeModuleStatus[node.Name] = amdv1alpha1.ModuleStatus{}

		nmc := kmmv1beta1.NodeModulesConfig{}
		err := dcrh.client.Get(ctx, types.NamespacedName{Name: node.Name}, &nmc)
		if err != nil {
			logger.Error(err, fmt.Sprintf("failed to fetch NMC for node %+v", node.Name))
			continue
		}
		if nmc.Status.Modules != nil {
			for _, module := range nmc.Status.Modules {
				// if there is any module was configured by given DeviceConfig
				// push their status back to DeviceConfig
				if module.Namespace == devConfig.Namespace &&
					module.Name == devConfig.Name {
					devConfig.Status.NodeModuleStatus[node.Name] = amdv1alpha1.ModuleStatus{
						ContainerImage:     module.Config.ContainerImage,
						KernelVersion:      module.Config.KernelVersion,
						LastTransitionTime: module.LastTransitionTime.String(),
					}
				}
			}
		}
	}

	return nil
}

func (dcrh *deviceConfigReconcilerHelper) setFinalizer(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig) error {
	if controllerutil.ContainsFinalizer(devConfig, deviceConfigFinalizer) {
		return nil
	}

	devConfigCopy := devConfig.DeepCopy()
	controllerutil.AddFinalizer(devConfig, deviceConfigFinalizer)
	return dcrh.client.Patch(ctx, devConfig, client.MergeFrom(devConfigCopy))
}

func (dcrh *deviceConfigReconcilerHelper) finalizeDeviceConfig(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig) error {
	logger := log.FromContext(ctx)

	nlDS := appsv1.DaemonSet{}
	namespacedName := types.NamespacedName{
		Namespace: devConfig.Namespace,
		Name:      devConfig.Name + "-node-labeller",
	}

	err := dcrh.client.Get(ctx, namespacedName, &nlDS)
	if err != nil {
		if !k8serrors.IsNotFound(err) {
			return fmt.Errorf("failed to get nodelabeller daemonset %s: %v", namespacedName, err)
		}
	} else {
		logger.Info("deleting nodelabeller daemonset", "daemonset", namespacedName)
		return dcrh.client.Delete(ctx, &nlDS)
	}

	mod := kmmv1beta1.Module{}
	namespacedName = types.NamespacedName{
		Namespace: devConfig.Namespace,
		Name:      devConfig.Name,
	}
	err = dcrh.client.Get(ctx, namespacedName, &mod)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			logger.Info("module already deleted, removing finalizer", "module", namespacedName)
			devConfigCopy := devConfig.DeepCopy()
			controllerutil.RemoveFinalizer(devConfig, deviceConfigFinalizer)
			return dcrh.client.Patch(ctx, devConfig, client.MergeFrom(devConfigCopy))
		}
		return fmt.Errorf("failed to get the requested Module %s: %v", namespacedName, err)
	}
	logger.Info("deleting KMM Module", "module", namespacedName)
	return dcrh.client.Delete(ctx, &mod)
}

func (dcrh *deviceConfigReconcilerHelper) handleBuildConfigMap(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error {
	if nodes == nil || len(nodes.Items) == 0 {
		return fmt.Errorf("No nodes found for the label selector %s", kmmmodule.MapToLabelSelector(devConfig.Spec.Selector))
	}

	savedCMName := map[string]bool{}
	for _, node := range nodes.Items {
		cmName, err := kmmmodule.GetCMName(node)
		if err != nil {
			return fmt.Errorf("invalid node %s, err: %v", node.Name, err)
		}
		if savedCMName[cmName] {
			// already saved a docker file for the OS-Version combo
			continue
		}

		buildDockerfileCM := &v1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Namespace: devConfig.Namespace,
				Name:      cmName,
			},
		}

		logger := log.FromContext(ctx)
		opRes, err := controllerutil.CreateOrPatch(ctx, dcrh.client, buildDockerfileCM, func() error {
			return dcrh.kmmHandler.SetBuildConfigMapAsDesired(buildDockerfileCM, devConfig)
		})

		if err == nil {
			logger.Info("Reconciled KMM build dockerfile ConfigMap", "name", buildDockerfileCM.Name, "result", opRes)
		}

		savedCMName[cmName] = true
	}

	return nil
}

func (dcrh *deviceConfigReconcilerHelper) handleKMMModule(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error {
	// the newly created KMM Module will always has the same namespace and name as its parent DeviceConfig
	kmmMod := &kmmv1beta1.Module{
		ObjectMeta: metav1.ObjectMeta{
			Namespace: devConfig.Namespace,
			Name:      devConfig.Name,
		},
	}
	logger := log.FromContext(ctx)
	opRes, err := controllerutil.CreateOrPatch(ctx, dcrh.client, kmmMod, func() error {
		return dcrh.kmmHandler.SetKMMModuleAsDesired(ctx, kmmMod, devConfig, nodes)
	})

	if err == nil {
		logger.Info("Reconciled KMM Module", "name", kmmMod.Name, "result", opRes)
	}
	return err
}

func (dcrh *deviceConfigReconcilerHelper) handleKMMVersionLabel(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig, nodes *v1.NodeList) error {
	// label corresponding node with given kmod version
	// so that KMM could manage the upgrade by watching the node's version label change
	err := dcrh.kmmHandler.SetNodeVersionLabelAsDesired(ctx, devConfig, nodes)
	if err != nil {
		return fmt.Errorf("failed to update node version label for DeviceConfig %s/%s: %v", devConfig.Namespace, devConfig.Name, err)
	}
	return nil
}

func (dcrh *deviceConfigReconcilerHelper) handleNodeLabeller(ctx context.Context, devConfig *amdv1alpha1.DeviceConfig) error {
	ds := &appsv1.DaemonSet{
		ObjectMeta: metav1.ObjectMeta{Namespace: devConfig.Namespace, Name: devConfig.Name + "-node-labeller"},
	}
	logger := log.FromContext(ctx)
	opRes, err := controllerutil.CreateOrPatch(ctx, dcrh.client, ds, func() error {
		return dcrh.nlHandler.SetNodeLabellerAsDesired(ds, devConfig)
	})

	if err != nil {
		return err
	}

	logger.Info("Reconciled node labeller", "namespace", ds.Namespace, "name", ds.Name, "result", opRes)

	// todo: temp. cleanup labels set by node-labeller
	// not required once label cleanup is added in node-labeller
	its, err := kmmmodule.GetK8SNodes("! " + labels.GetKernelModuleReadyNodeLabel(devConfig.Namespace, devConfig.Name))
	if err != nil {
		logger.Info("failed to get node list ", err)
		return nil
	}

	for i := range its.Items {
		node := &v1.Node{
			ObjectMeta: its.Items[i].ObjectMeta,
		}
		opRes, err := controllerutil.CreateOrPatch(ctx, dcrh.client, node, func() error {
			for k := range node.Labels {
				if strings.HasPrefix(k, "beta.amd.com") ||
					strings.HasPrefix(k, "amd.com") {
					delete(node.Labels, k)
				}
			}
			return nil
		})
		logger.Info("update node labels", "node", node.Name, "error", err, "response", opRes)
	}

	return nil
}
