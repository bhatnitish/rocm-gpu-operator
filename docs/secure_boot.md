# Secure Boot

Secure boot is one mechanism to protect a system against malicious code being loaded and executed early in the boot process, before the operating system has been loaded. Fore more information, please take a look at [here](https://wiki.debian.org/SecureBoot). For how to sign the kernel module manually, please refer to [Ubuntu Tutorial](https://ubuntu.com/blog/how-to-sign-things-for-secure-boot) or [RedHat Linux Tutorial](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/managing_monitoring_and_updating_the_kernel/signing-a-kernel-and-modules-for-secure-boot_managing-monitoring-and-updating-the-kernel).

If users worker nodes have secure boot enabled, the system would have more security restrictions to load kernel module. The incoming kernel module must be signed with a valid key pair and the public key must be registered with Machine Owner Key (MOK) database. Otherwise the system would reject loading the kernel module.

As for AMD GPU Operator, there are 2 different methods to get the driver image:

1. Users prepare their own driver image and sign the kernel module by themselves.
2. Users ask AMD GPU Operator to build the driver image within the Kubernetes cluster.

For method 1, users are responsible to sign the kernel module correctly within the prepared driver image and make sure the signing public key has been registered on all selected worker nodes. Users could refer to the links mentioned above to do the kernel module signing.

For method 2, users could prepare a image signing key pair and registry the public key with MOK database, then ask for AMD GPU Operator to sign the kernel module.

### Image signing with the Operator

* Prerequisites:

    * A valid public/private key pair in the correct (der) format, for example the key pair could be created by running ```openssl req -x509 -new -nodes -utf8 -sha256 -days 36500 -batch -outform DER -out my_signing_key_pub.der -keyout my_signing_key.priv```
    * All secure boot enabled worker nodes have the public key registered within MOK database

* Add key pair for signing

    * Encode the key pair:
    ```
    cat my_signing_key.priv | base64 -w 0  > my_signing_key2.base64
    cat my_signing_key_pub.der | base64 -w 0 > my_signing_key_pub.base64
    ```
    * Prepare the secrets:
    ```
    apiVersion: v1
    kind: Secret
    metadata:
    name: my-signing-key-pub
    namespace: default
    type: Opaque
    data:
    cert: <base64 encoded secureboot public key>
    ---
    apiVersion: v1
    kind: Secret
    metadata:
    name: my-signing-key
    namespace: default
    type: Opaque
    data:
    key: <base64 encoded secureboot private key>
    ```
    * Create the secrets:
    ```
    kubectl apply -f <secrets yaml file>
    ```
    * Specify secret name in ```DeviceConfig```:
    ```
    metadata:
      ...
    spec:
      ...
      imageSignKeySecret:
        name: my-signing-key
      imageSignCertSecret:
        name: my-signing-key-pub
    ```

By following aforementioned steps, the operator would build the image within the cluster firstly, then sign the kernel module of the newly built image, ultimately use the newly built + signed image to load the AMD GPU driver kernel module on worker nodes.

### TroubleShooting

If the KMM operator worker failed to load the kernel module due to errors like ```modprobe: ERROR: could not insert '<your kmod name>': Required key not available``` or ```modprobe: ERROR: could not insert 'amdgpu': Operation not permitted```, the possible situations could be:
* The kernel modules within the driver image were not signed
* The kernel modules were signed with wrong key
* The public key was not registered within the worker node's MOK database correctly