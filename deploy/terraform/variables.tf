# ---------------------------------------------------------------------------
# Input variables
# ---------------------------------------------------------------------------

# --- Azure subscription / identity --------------------------------------------------
variable "subscription_id" {
  description = "Azure subscription ID. Leave empty to use the az-login default."
  type        = string
  default     = ""
}

variable "tenant_id" {
  description = "Azure tenant ID. Leave empty to use the az-login default."
  type        = string
  default     = ""
}

# --- Naming / location --------------------------------------------------------------
variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "francecentral"
}

variable "prefix" {
  description = "Short name prefix used to build resource names."
  type        = string
  default     = "aiaccel"
}

variable "environment" {
  description = "Environment short name (dev/test/prod). Only dev is in scope."
  type        = string
  default     = "dev"
}

variable "resource_group_name" {
  description = "Resource group name. If empty, derived from prefix/environment."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to all Azure resources."
  type        = map(string)
  default = {
    project     = "ai-accelerator-2026"
    environment = "dev"
    managed_by  = "terraform"
  }
}

# --- AKS ----------------------------------------------------------------------------
variable "kubernetes_version" {
  description = "AKS Kubernetes version. Empty = let Azure pick the default."
  type        = string
  default     = ""
}

variable "aks_node_count" {
  description = "Number of nodes in the default AKS node pool."
  type        = number
  default     = 2
}

variable "aks_node_vm_size" {
  description = "VM size for the default AKS node pool."
  type        = string
  default     = "Standard_D2s_v5"
}

variable "aks_enable_auto_scaling" {
  description = "Enable cluster autoscaler on the default node pool."
  type        = bool
  default     = false
}

variable "aks_min_node_count" {
  description = "Minimum nodes when autoscaling is enabled."
  type        = number
  default     = 1
}

variable "aks_max_node_count" {
  description = "Maximum nodes when autoscaling is enabled."
  type        = number
  default     = 3
}

# --- ACR ----------------------------------------------------------------------------
variable "acr_sku" {
  description = "Azure Container Registry SKU (Basic/Standard/Premium)."
  type        = string
  default     = "Basic"
}

# --- Kubernetes namespaces ----------------------------------------------------------
variable "app_namespace" {
  description = "Namespace for the application (frontend, worker, ops-api)."
  type        = string
  default     = "aiaccel-dev"
}

variable "supabase_namespace" {
  description = "Namespace for the in-cluster Supabase release."
  type        = string
  default     = "supabase"
}

variable "temporal_namespace" {
  description = "Namespace for the in-cluster Temporal release."
  type        = string
  default     = "temporal"
}

# --- Feature toggles ----------------------------------------------------------------
# These let you stage the rollout: stand up the platform first, push images,
# then enable the in-cluster Helm releases.
variable "enable_temporal" {
  description = "Install the Temporal Helm release."
  type        = bool
  default     = true
}

variable "enable_supabase" {
  description = "Install the Supabase Helm release."
  type        = bool
  default     = true
}

variable "enable_app" {
  description = "Install the application Helm release (requires images in ACR)."
  type        = bool
  default     = false
}

variable "build_and_push_images" {
  description = "If true, run `az acr build` to build+push the app images before the app release. Requires az CLI + Docker context."
  type        = bool
  default     = false
}

# --- Application image config -------------------------------------------------------
variable "frontend_image_repository" {
  description = "Frontend image repository name within the ACR (without registry)."
  type        = string
  default     = "frontend"
}

variable "worker_image_repository" {
  description = "Temporal worker / ops-api image repository name within the ACR."
  type        = string
  default     = "temporal-worker"
}

variable "image_tag" {
  description = "Image tag to deploy for the app components."
  type        = string
  default     = "dev-latest"
}

# --- Supabase secret overrides ------------------------------------------------------
# Leave empty to have Terraform generate them (jwt_secret randomly, and the
# anon/service JWTs via scripts/gen-supabase-jwt.py signed with that secret).
variable "supabase_jwt_secret" {
  description = "Supabase JWT signing secret. Empty = generate a random 40-char secret."
  type        = string
  default     = ""
  sensitive   = true
}

variable "supabase_anon_key" {
  description = "Supabase anon API key (JWT). Empty = derive from the JWT secret."
  type        = string
  default     = ""
  sensitive   = true
}

variable "supabase_service_role_key" {
  description = "Supabase service_role API key (JWT). Empty = derive from the JWT secret."
  type        = string
  default     = ""
  sensitive   = true
}

# --- Public hostnames (optional, for display/values only) ---------------------------
variable "supabase_public_url" {
  description = "Public URL the browser uses to reach Supabase (https). Optional until DNS is set up."
  type        = string
  default     = ""
}
