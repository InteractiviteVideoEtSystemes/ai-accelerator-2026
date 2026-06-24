# ADR-0001: Provision Azure infrastructure with Terraform (local state)

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** @bastien-martin
**Technical Story:** Session task — "deploy the required azure resources using terraform"

## Context

The stack runs locally via `make up` (Supabase CLI + Temporal + worker + frontend),
but there was no infrastructure-as-code path to stand it up on Azure. We needed a
repeatable, reviewable way to create the Azure platform (Resource Group, container
registry, Kubernetes cluster) and bootstrap the in-cluster components. The existing
`charts/app` Helm chart and `.github/workflows/deploy-*.yml` already assume an
AKS + ACR target, but the cluster, registry and namespaces were never provisioned
(`az aks list` and `az acr list` returned empty). We are starting with a single
nonprod/dev environment and want low ceremony to begin.

## Decision

We use **Terraform** (providers `azurerm`, `kubernetes`, `helm`, `random`, `null`)
to provision the Azure platform and bootstrap the cluster, with **local state**,
targeting a single **nonprod/dev** environment in **France Central**. The code
lives in `deploy/terraform/`.

## Consequences

### Positive
- Reproducible, version-controlled, reviewable infrastructure.
- One tool spans Azure resources and in-cluster Helm/Kubernetes objects.
- Feature toggles (`enable_temporal`, `enable_supabase`, `enable_app`,
  `build_and_push_images`) allow a staged rollout.

### Negative
- Local state is not shared/locked — risk of drift or conflict across machines;
  the state file contains secrets and must be handled securely.
- Mixing Azure + Kubernetes + Helm providers in one root couples cluster creation
  and in-cluster releases in a single apply graph.

### Neutral
- Remote state (Azure Storage) can be adopted later by adding a backend block.
- The existing GitHub Actions deploy workflows remain the app-deployment path;
  Terraform provides the platform + initial bootstrap.

## Options Considered

### Option 1: Terraform (chosen)
- **Pros:** widely known, rich Azure + Kubernetes + Helm provider ecosystem, one
  workflow for platform and in-cluster bootstrap.
- **Cons:** extra tool/state to manage; provider-coupling in a single root module.

### Option 2: Bicep / ARM templates
- **Pros:** native Azure, no extra state backend, first-class Azure support.
- **Cons:** weak/no story for in-cluster Helm + Kubernetes objects; would need a
  second tool for the cluster bootstrap.

### Option 3: Manual `az` CLI / scripts
- **Pros:** zero new tooling.
- **Cons:** not reproducible or reviewable; error-prone; no desired-state drift detection.

## Quality & Security (Non-Negotiable)

- **No secrets committed.** `terraform.tfvars`, `*.tfstate`, and kubeconfig are
  gitignored; the state file (which contains secrets) is never pushed. Secret
  values are injected at apply time, never hard-coded in `.tf` files.
- **Least-privilege identities.** Kubelet pulls from ACR via an `AcrPull` managed
  identity; no broad credentials embedded in the cluster or workflows.
- **Reviewable, reproducible changes only.** Every infra change goes through
  Terraform (`fmt` + `validate` clean) — no out-of-band `az` mutations.
- **Additive/staged rollout.** Feature toggles gate optional components so changes
  stay incremental and reversible.

## Related Decisions

- ADR-0002 (AKS deployment topology with in-cluster Supabase & Temporal).

## Notes

State backend chosen as **local** for this nonprod/dev start; `terraform.tfvars`,
`*.tfstate`, and any kubeconfig are gitignored. No `terraform apply` has been run
against Azure yet — the configuration was validated offline (`fmt`, `init
-backend=false`, `validate`).
