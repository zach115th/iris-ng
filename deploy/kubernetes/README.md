# IRIS-NG on Kubernetes (Helm)

The chart in `charts/` deploys the IRIS-NG app, its worker and its AI worker, PostgreSQL, RabbitMQ, and an
Ingress in front of the app. It pulls the published images (`ghcr.io/zach115th/iriswebapp_app` and
`ghcr.io/zach115th/iriswebapp_db`) at the chart's `appVersion`, so nothing needs to be built. There is no nginx
pod: your Ingress controller terminates TLS and talks to the app directly.

## Prerequisites

- **A Kubernetes version your provider still supports.** The chart needs 1.19 or later (`kubeVersion:
  ">=1.19.0-0"`, for the `networking.k8s.io/v1` Ingress); it was tested on kind v0.33.0 (Kubernetes
  v1.37.0) with Traefik.
- **Helm 4.** Helm 3 still works, but its security fixes end on 2027-02-10.
- **An Ingress controller, and its IngressClass** (`kubectl get ingressclass`). ingress-nginx, which earlier
  versions of this guide installed, was retired in March 2026 and receives no more fixes; use a maintained
  controller, for example Traefik, HAProxy Ingress, the F5 NGINX Ingress Controller, Contour, or your cloud
  provider's.
- **A default StorageClass** for the database volume (20 GiB, ReadWriteOnce), or set
  `postgres.persistence.storageClass`.

`make check-dependencies` installs Helm 4 and kubectl when they are missing.

## Configure

Copy `charts/values.yaml` and change at least:

- **The passwords and keys.** `POSTGRES_PASSWORD` and `POSTGRES_ADMIN_PASSWORD` appear under `postgres`,
  `irisapp`, `irisworker` and `irisaiworker` - give each the same value in all four. `IRIS_SECRET_KEY` and
  `IRIS_SECURITY_PASSWORD_SALT` appear under the three app sections, also the same in each. `IRIS_ADM_PASSWORD`
  (under `irisapp`) is the first administrator's password.
- **`ingress.hosts[0].host`** and **`ingress.tls[0].hosts`**: your hostname.
- **`ingress.className`**: your controller's IngressClass. Leave it empty to use the cluster's default class
  (Kubernetes fills it in when the Ingress is created).
- **`ingress.tls[0].secretName`**: a TLS Secret for that hostname in the release's namespace (`kubectl create
  secret tls ...`). Remove `tls` if your controller provides the certificate itself.

### Settings that depend on your controller

The chart sets nothing controller-specific; put such settings in `ingress.annotations` (values are quoted for
you).

- **Uploads.** Timeline imports and datastore files can be hundreds of megabytes. A controller that limits the
  request body needs that limit raised for this Ingress - the F5 NGINX Ingress Controller, for example, with
  `nginx.org/client-max-body-size: "0"` (no limit). Traefik sets no limit by default.
- **Long requests.** A synchronous AI request can take up to ten minutes; raise the controller's read timeout for
  the app's responses where it has one (F5 NGINX: `nginx.org/proxy-read-timeout: "600s"`).
- **HTTP to HTTPS.** Redirecting plain HTTP is a controller setting (an entry-point or annotation option), not
  part of the chart.

## Install

From a clone of [zach115th/iris-ng](https://github.com/zach115th/iris-ng):

```bash
helm install iris deploy/kubernetes/charts -n iris --create-namespace -f my-values.yaml
```

or from the chart attached to a release (`iris-web-<chart version>.tgz` on the release page):

```bash
helm install iris iris-web-1.14.0.tgz -n iris --create-namespace -f my-values.yaml
```

The app applies its database migrations when it starts; the first start takes a few minutes. Then point your
hostname at the controller's address (`kubectl get ingress -n iris`) and sign in as the administrator.

## Upgrade

```bash
helm upgrade iris deploy/kubernetes/charts -n iris -f my-values.yaml
```

Back the database up first (`kubectl exec -n iris deploy/postgres -- pg_dump -U postgres -Fc iris_db >
iris.dump`): a migration is one-way. RabbitMQ keeps no volume, so an upgrade that changes its image restarts it with empty queues - run the
upgrade when no background task is waiting.

## Uninstall

```bash
helm uninstall iris -n iris
```

This deletes the database volume's claim with the release (and, with the usual `Delete` reclaim policy, the data);
back up first.
