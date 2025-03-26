# Export Test Runner logs to external storage

Test runner logs can be exported to external storage. Currently we support exporting the logs to Azure blob storage, AWS S3 bucket service and Minio server.

## Overview

Test runner logs can be exported to external storage buckets for audit and debug purposes. Exported logs are segregated into folders/sub-folders based on the trigger type, job name, node name, timestamp so that it is easier to search and track them. This feature is disabled by default. Following section describes the steps to enable the functionality.
User must specify the storage provider and bucket name in test runner config map. Credentials to connect to external storage must be provided as Kubernetes [Secret](https://kubernetes.io/docs/concepts/configuration/secret). Secret is mounted as a mount volume on test runner container. For manual, pre-start and cron jobs, the secret information should be mounted explicitly in their respective job yamls. Refer to [examples](https://github.com/ROCm/gpu-operator/tree/main/example/testrunner) folder for sample job yamls and config map.

## Configuration

Capture connectivity information as Kubernetes secret. Secret must be created within same Kubernetes Namespace as AMD GPU Operator/test runner. Information/keys captured as part of secret differ based on service provider.

### AWS Secret

AWS secret captures user [access key](https://aws.amazon.com/blogs/security/wheres-my-secret-access-key) information and aws region of bucket. Below are the keys needed:
- aws_access_key_id - AWS user access key
- aws_secret_access_key - AWS user secret
- aws_region - AWS region where the S3 bucket is hosted

Example:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aws-secret
  namespace: default
type: Opaque
data:
  aws_access_key_id: your-access-key-id
  aws_region: sample-aws-region
  aws_secret_access_key: your-secret-key
```

### Azure Secret

Azure secret captures storage account name and key info. Below are the keys needed:
- azure_storage_account - Azure blob storage account name
- azure_storage_key - Azure storage account key

Example:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: azure-secret
  namespace: default
type: Opaque
data:
  azure_storage_account: sample_azure_storage_account
  azure_storage_key: sample_azure_storage_key
```

### Minio Secret

Minio supports S3 compatible APIs for object storage. So for Minio, we can create AWS secret with extra field to capture Minio S3 endpoint URL. Below are the keys needed:
- aws_access_key_id - Minio user access key
- aws_secret_access_key - Minio user secret
- aws_region - For Minio, ```us-east-1``` can be used as default aws region
- aws_endpoint_url - Minio S3 endpoint url

Example:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: minio-secret
  namespace: default
type: Opaque
data:
  aws_access_key_id: your-minio-access-id
  aws_region: us-east-1
  aws_secret_access_key: your-minio-secret-key
  aws_endpoint_url: your-minio-s3-endpoint
```

### Storage provider and Bucket information in config map

Storage provider and bucket name are captured in test runner config map. Below is an example:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: test-runner-config
  namespace: kube-amd-gpu
data:
  config.json: |
    {
      "TestConfig": {
        "GPU_HEALTH_CHECK": {
          "TestLocationTrigger": {
            "global": {
              "TestParameters": {
                "AUTO_UNHEALTHY_GPU_WATCH": {
                  "TestCases": [
                    {
                      "Recipe": "gst_single",
                      "Iterations": 1,
                      "StopOnFailure": true,
                      "TimeoutSeconds": 600
                    }
                  ],
                  "LogsExportConfig": [
                    {
                      "Provider": "aws",
                      "BucketName": "aws-bucket-name",
                      "SecretName": "aws-secret"
                    },
                    {
                      "Provider": "azure",
                      "BucketName": "azure-bucket-name",
                      "SecretName": "azure-secret"
                    },
                    {
                      "Provider": "aws",
                      "BucketName": "minio-bucket-name",
                      "SecretName": "minio-secret"
                    }
                  ]
                }
              }
            }
          }
        }
      }
    }
```
### Auto Unhealthy GPU watch scenario

For Auto unhealthy gpu watch scenario, the secret information is passed in test runner section of device config Custom Resource(CR). We can export logs to multiple external services. We can specify multiple secrets in device config Custom Resource(CR) and associate each to a particular external storage service. Below is an example:

```yaml
  # Specify the testrunner config
  testRunner:
    # To enable/disable the testrunner, disabled by default
    enable: True

    # testrunner image
    image: docker.io/rocm/test-runner:v1.2.0-beta.0

    # image pull policy for the testrunner
    # default value is IfNotPresent for valid tags, Always for no tag or "latest" tag
    imagePullPolicy: "Always"

    # test runner config map
    config:
      # example config map can be found under examples/testrunner/configmap.json
      name: sample-configmap

    # specify the mount for test logs
    logsLocation:
      # mount path inside test runner container
      mountPath: "/var/log/amd-test-runner"

      # host path to be mounted into test runner container
      hostPath: "/var/log/amd-test-runner"

      # list of secrets that contain connectivity info to cloud providers
      logsExportSecrets:
      # the secrets mentioned below are associated with the test runner via config map. Refer examples/testrunner/configmap.json
      - name: azure-secret
      - name: aws-secret
```
