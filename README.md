# gcp-k8s-storage

## Description

This charm manages installation of the out of tree csi driver from google
kubernetes-sigs/gcp-compute-persistent-disk-csi-driver such that Charmed
Kubernetes can use its storage features.

## Usage

The charm requires gcp credentials and connection information, which
should be provided by relating to the gcp-integrator charm.

## Deployment

### The full process

```bash
juju deploy charmed-kubernetes
juju config kubernetes-control-plane allow-privileged=true
juju deploy gcp-integrator --trust
juju deploy gcp-k8s-storage

juju relate gcp-k8s-storage:certificates     easyrsa
juju relate gcp-k8s-storage:kube-control     kubernetes-control-plane
juju relate gcp-k8s-storage                  gcp-integrator:gcp
juju relate kubernetes-control-plane         gcp-integrator:gcp
juju relate kubernetes-worker                gcp-integrator:gcp

##  wait for the kubernetes-control-plane to be active/idle
kubectl describe nodes |egrep "Taints:|Name:|Provider"
```

### Details

* Requires a `charmed-kubernetes` deployment on a gcp cloud launched by juju
* Deploy the `gcp-integrator` charm into the model using `--trust` so juju provided gcp credentials
* Deploy the `gcp-k8s-storage` charm in the model relating to the integrator
* Once the model is active/idle, the charm will have successfully deployed the gcp persistent disk driver in the `gce-pd-csi-driver` namespace

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines
on enhancements to this charm following best practice guidelines, and
[CONTRIBUTING.md](https://github.com/charmed-kubernetes/gcp-k8s-storage/blob/main/CONTRIBUTING.md)
for developer guidance.
