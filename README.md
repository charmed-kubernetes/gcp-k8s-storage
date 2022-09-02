# gcp-cloud-provider

## Description

This subordinate charm manages the cloud-provider and ebs-csi-driver components in GCP.

## Prerequisites

It's important to understand that the control-plane and worker nodes will need
access to GCP credentials to facilitate features like creating loadbalancers, 
mounting volumes, and the like. GCP recommends accomplishing this by giving
each instance a set number of [policies](https://cloud-provider-gcp.sigs.k8s.io/prerequisites/).

Use this policies to create instance-profiles which juju can use as constraints
for the worker and control-plane nodes.  See [juju instance-profiles](https://discourse.charmhub.io/t/using-gcp-instance-profiles-with-juju-2-9/5185).

## Usage

The charm requires gcp credentials and connection information, which
can be provided either directly, via config, or via the `juju trust`

## Deployment

### The full process

```bash
juju deploy charmed-kubernetes
juju config kubernetes-control-plane allow-privileged=true
juju deploy gcp-integrator --trust
juju deploy gcp-cloud-provider --trust

juju relate gcp-cloud-provider:certificates     easyrsa
juju relate gcp-cloud-provider:kube-control     kubernetes-control-plane
juju relate gcp-cloud-provider                  gcp-integrator:clients
juju relate kubernetes-control-plane            gcp-integrator:clients
juju relate kubernetes-worker                   gcp-integrator:clients

##  wait for the kubernetes-control-plane to be active/idle
kubectl describe nodes |egrep "Taints:|Name:|Provider"
```

### Details

* Requires a `charmed-kubernetes` deployment on a gcp cloud launched by juju
* Deploy the `gcp-integrator` charm into the model using `--trust` so juju provided gcp credentials
* Deploy the `gcp-cloud-provider` charm in the model relating to the integrator and to charmed-kubernetes components
* Once the model is active/idle, the cloud-provider charm will have successfully deployed the gcp ebs-csi in the kube-system namespace

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines
on enhancements to this charm following best practice guidelines, and
[CONTRIBUTING.md](https://github.com/charmed-kubernetes/gcp-cloud-provider/blob/main/CONTRIBUTING.md)
for developer guidance.
