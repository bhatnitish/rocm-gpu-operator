package client

import (
	"context"

	"github.com/pensando/gpu-operator/api/v1alpha1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/rest"
)

type ClientInterface interface {
	DeviceConfigs(namespace string) DeviceConfigsInterface
}

type DeviceConfigClient struct {
	restClient rest.Interface
}

func Client(c *rest.Config) (*DeviceConfigClient, error) {
	config := *c
	config.ContentConfig.GroupVersion = &v1alpha1.GroupVersion
	config.APIPath = "/apis"
	config.NegotiatedSerializer = scheme.Codecs.WithoutConversion()
	config.UserAgent = rest.DefaultKubernetesUserAgent()

	client, err := rest.RESTClientFor(&config)
	if err != nil {
		return nil, err
	}

	return &DeviceConfigClient{restClient: client}, nil
}

func (c *DeviceConfigClient) DeviceConfigs(namespace string) DeviceConfigsInterface {
	return &deviceConfigsClient{
		restClient: c.restClient,
		ns:         namespace,
	}
}

type deviceConfigsClient struct {
	restClient rest.Interface
	ns         string
}

type DeviceConfigsInterface interface {
	Create(config *v1alpha1.DeviceConfig) (*v1alpha1.DeviceConfig, error)
	List(opts metav1.ListOptions) (*v1alpha1.DeviceConfigList, error)
	Get(name string, options metav1.GetOptions) (*v1alpha1.DeviceConfig, error)
	Delete(name string) (*v1alpha1.DeviceConfig, error)
}

func (c *deviceConfigsClient) List(opts metav1.ListOptions) (*v1alpha1.DeviceConfigList, error) {
	result := v1alpha1.DeviceConfigList{}
	err := c.restClient.
		Get().
		Namespace(c.ns).
		Resource("deviceConfigs").
		//VersionedParams(&opts, scheme.ParameterCodec).
		Do(context.TODO()).
		Into(&result)

	return &result, err
}

func (c *deviceConfigsClient) Get(name string, opts metav1.GetOptions) (*v1alpha1.DeviceConfig, error) {
	result := v1alpha1.DeviceConfig{}
	err := c.restClient.
		Get().
		Namespace(c.ns).
		Resource("deviceConfigs").
		Name(name).
		//VersionedParams(&opts, scheme.ParameterCodec).
		Do(context.TODO()).
		Into(&result)

	return &result, err
}

func (c *deviceConfigsClient) Create(devCfg *v1alpha1.DeviceConfig) (*v1alpha1.DeviceConfig, error) {
	result := v1alpha1.DeviceConfig{}
	devCfg.TypeMeta = metav1.TypeMeta{
		Kind:       "DeviceConfig",
		APIVersion: "amd.com/v1alpha1",
	}
	err := c.restClient.
		Post().
		Namespace(c.ns).
		Resource("deviceConfigs").
		Body(devCfg).
		Do(context.TODO()).
		Into(&result)

	return &result, err
}
func (c *deviceConfigsClient) Delete(name string) (*v1alpha1.DeviceConfig, error) {
	result := v1alpha1.DeviceConfig{}
	err := c.restClient.
		Delete().
		Namespace(c.ns).
		Resource("deviceConfigs").
		Body(&v1alpha1.DeviceConfig{
			ObjectMeta: metav1.ObjectMeta{
				Name: name,
			},
		}).
		Do(context.TODO()).
		Into(&result)

	return &result, err
}
