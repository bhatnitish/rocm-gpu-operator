 #!/bin/bash

set -x

# Define Docker Hub credentials
DOCKER_USERNAME="amdpsdo"
DOCKER_PASSWORD="dckr_oat_YirfnS7e0IMqU1vv-jMTn8rdBnQZeO5K"

# Create a Docker registry secret with a name based on username and password
SECRET_NAME="dockerhub-secret"
kubectl create secret docker-registry "$SECRET_NAME" \
  --docker-username="$DOCKER_USERNAME" \
  --docker-password="$DOCKER_PASSWORD" \
  --docker-server="https://index.docker.io/" \
  --namespace=kube-amd-gpu \
  --dry-run=client -o yaml | kubectl apply -f -

# Verify the secret creation
echo "Docker registry secret $SECRET_NAME created successfully."

# Fetch all service accounts in the kube-amd-gpu namespace
service_accounts=$(kubectl get serviceaccount -n kube-amd-gpu -o jsonpath='{.items[*].metadata.name}')

# Loop over the service accounts and patch each with the created secret
for sa in $service_accounts; do
  echo "Patching service account: $sa"
  kubectl patch serviceaccount $sa -n kube-amd-gpu \
    -p "{\"imagePullSecrets\": [{\"name\": \"$SECRET_NAME\"}]}"
done

echo "Patching complete for all service accounts in the kube-amd-gpu namespace."