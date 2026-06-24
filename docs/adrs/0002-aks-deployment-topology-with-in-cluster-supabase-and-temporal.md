# ADR-0002: Deploy on AKS with in-cluster Supabase and Temporal

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** @bastien-martin
**Technical Story:** Session task — Terraform infra for the stack

## Context

The application has three stateless components (frontend, temporal-worker,
ops-api) plus two backing platforms it depends on (Supabase for Postgres/Storage/
Auth/API, and a Temporal server for workflow orchestration). The shipped
`charts/app` chart, its `values-dev.yaml`, and the `deploy-*.yml` workflows already
encode an AKS target that reaches Supabase via an in-cluster Kong service
(`supabase-supabase-kong.<ns>.svc.cluster.local`) and Temporal via
`temporal-frontend.<ns>.svc.cluster.local:7233`. We needed to confirm and record
the runtime topology the Terraform provisions.

## Decision

We deploy to **Azure Kubernetes Service (AKS)**, pulling images from **Azure
Container Registry (ACR)** via the cluster's kubelet managed identity (`AcrPull`),
and we run **Supabase** and the **Temporal server** **in-cluster** (via their Helm
charts) in dedicated namespaces, alongside the app namespace.

## Consequences

### Positive
- Single cluster hosts app + its dependencies; in-cluster service DNS matches the
  values already used by `charts/app`.
- ACR + AcrPull avoids managing image pull secrets.
- Mirrors the local docker-compose topology, easing dev→cluster parity.

### Negative
- Running Supabase (incl. Postgres) and Temporal in-cluster makes the cluster
  stateful and raises operational burden (backups, upgrades, storage) versus
  managed services.
- The community Supabase Helm chart is a heavy, fast-moving dependency.

### Neutral
- A future ADR may move Supabase/Temporal to managed offerings (managed Postgres,
  Temporal Cloud) without changing the app components.

## Options Considered

### Option 1: AKS with in-cluster Supabase & Temporal (chosen)
- **Pros:** matches existing chart/values; one platform; dev/prod parity.
- **Cons:** stateful cluster; operational responsibility for the data plane.

### Option 2: AKS for app, managed Postgres + Temporal Cloud
- **Pros:** offloads stateful/ops concerns; production-grade durability.
- **Cons:** more Azure/SaaS cost and setup; diverges from the current values now.

### Option 3: Azure Container Apps / App Service (no Kubernetes)
- **Pros:** less cluster ops.
- **Cons:** throws away the existing Helm chart and workflow investment.

## Quality & Security (Non-Negotiable)

- **Private data plane.** Supabase/Temporal run in dedicated namespaces; backing
  stores are not publicly exposed. Inter-service traffic uses in-cluster DNS.
- **No image pull secrets / no embedded creds.** Images are pulled via the kubelet
  `AcrPull` managed identity (least privilege).
- **Secrets via Kubernetes secrets only.** App/worker secrets (incl.
  `AZURE_CLAUDE_API_KEY`, Supabase keys) come from K8s secrets — never baked into
  images, chart values in git, or logs.
- **Stateful components require backups/upgrade discipline** before any production
  use — an explicit operational gate, not optional.

## Related Decisions

- ADR-0001 (Terraform as the provisioning tool).

## Notes

Single **nonprod/dev** environment in France Central for now. The chart's
`values-dev.yaml` placeholders are injected by Terraform at release time rather
than edited in the shipped chart.
