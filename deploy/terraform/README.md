# Terraform — Azure (AKS) deployment for the stack

Provisions the Azure platform **and** the in-cluster components needed to run the
project stack on a single nonprod/dev environment in **France Central**:

| Layer | Resources |
|-------|-----------|
| Azure platform | Resource Group, Azure Container Registry (ACR), AKS cluster (+ `AcrPull` role), Log Analytics |
| Kubernetes bootstrap | Namespaces (`aiaccel-dev`, `supabase`, `temporal`), Supabase secrets |
| In-cluster apps (Helm) | Temporal server, Supabase, and the local `charts/app` (frontend + temporal-worker + ops-api) |

> ⚠️ **Cost & safety**: applying this creates real, billable Azure resources
> (AKS nodes, ACR, a public LoadBalancer IP, Log Analytics). Nothing here runs
> automatically — you must run `terraform apply` yourself. Tear everything down
> with `terraform destroy` when finished.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/downloads) ≥ 1.5
- Azure CLI (`az login` completed; the right subscription selected)
- `kubectl` (to inspect the cluster afterwards)
- Python 3 on PATH (used to derive the Supabase anon/service JWT keys)
- For `build_and_push_images = true`: a Docker build context reachable by `az acr build`

## Files

| File | Purpose |
|------|---------|
| `versions.tf` | Provider + Terraform version constraints (local state) |
| `providers.tf` | azurerm + kubernetes/helm wired to the AKS kubeconfig |
| `variables.tf` | All inputs (region, sizing, toggles, image config, secret overrides) |
| `main.tf` | Resource Group + Log Analytics + derived names |
| `acr.tf` | Azure Container Registry |
| `aks.tf` | AKS cluster + `AcrPull` role assignment |
| `namespaces.tf` | App / Supabase / Temporal namespaces |
| `secrets.tf` | Generated credentials + Kubernetes secrets |
| `temporal.tf` | Temporal Helm release |
| `supabase.tf` | Supabase Helm release |
| `app.tf` | Local `charts/app` Helm release (+ optional `az acr build`) |
| `outputs.tf` | ACR login server, kubeconfig, helpful commands |
| `scripts/gen-supabase-jwt.py` | Derives anon/service JWTs from the JWT secret |

## Usage

```bash
cd deploy/terraform

# 1. Configure
cp terraform.tfvars.example terraform.tfvars
#   edit terraform.tfvars as needed

# 2. Initialise providers
terraform init

# 3. Review the plan (no changes applied)
terraform plan

# 4. Stage 1 — platform + Temporal + Supabase (app disabled by default)
terraform apply

# 5. Build & push the app images into the ACR
#    (either set build_and_push_images = true, or do it manually:)
ACR=$(terraform output -raw acr_name)
az acr build --registry "$ACR" --image frontend:dev-latest ../../frontend
az acr build --registry "$ACR" --image temporal-worker:dev-latest ../../temporal

# 6. Stage 2 — enable the application release
terraform apply -var "enable_app=true"

# 7. Get the frontend public IP
kubectl get svc -n aiaccel-dev -o wide
```

### Connect kubectl to the new cluster

```bash
$(terraform output -raw get_credentials_command)
```

## Recommended rollout (avoids the image chicken-and-egg)

The `app` chart pulls `frontend` / `temporal-worker` from the ACR, which is empty
until images are pushed. Therefore:

1. First `apply` with `enable_app = false` (default) — stands up platform +
   Temporal + Supabase.
2. Build & push images (step 5 above, or `build_and_push_images = true`).
3. `apply` again with `enable_app = true`.

## Toggles

| Variable | Default | Effect |
|----------|---------|--------|
| `enable_temporal` | `true` | Install Temporal Helm release |
| `enable_supabase` | `true` | Install Supabase Helm release |
| `enable_app` | `false` | Install the application Helm release |
| `build_and_push_images` | `false` | Run `az acr build` for the app images during apply |

## Secrets handling

- The Supabase **JWT secret**, **Postgres password** and **dashboard password**
  are generated with `random_password`.
- The **anon** and **service_role** keys are HS256 JWTs derived from the JWT
  secret via `scripts/gen-supabase-jwt.py` (stdlib only). You can override any of
  them through the `supabase_*` variables.
- `terraform.tfvars`, `*.tfstate` and any kubeconfig are **gitignored**. The state
  file contains secrets — store it securely (or move to a remote encrypted backend).

## Teardown

```bash
terraform destroy
```

## Notes / things to verify before a real apply

- **Helm chart versions** for Temporal (`temporalio/temporal`) and Supabase
  (`supabase-community`) are pinned but their values schema evolves — review them
  against the pinned version before the first apply.
- The Supabase community chart is the heaviest moving part; for production you
  may prefer managed Supabase or a managed Postgres instead of the in-cluster DB.
- This config targets a single **nonprod/dev** environment with **local** state,
  per the approved plan. test/prod and remote state are intentionally out of scope.
