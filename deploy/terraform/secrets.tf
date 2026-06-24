# ---------------------------------------------------------------------------
# Generated credentials + Kubernetes secrets
#
# Secrets are generated here (or taken from variables) and pushed into the
# cluster. They are NEVER written to the repo; terraform.tfvars and *.tfstate
# are gitignored. Treat the state file as sensitive.
# ---------------------------------------------------------------------------

resource "random_password" "jwt_secret" {
  length  = 40
  special = false
}

resource "random_password" "postgres_password" {
  length  = 24
  special = false
}

resource "random_password" "dashboard_password" {
  length  = 20
  special = false
}

locals {
  jwt_secret = var.supabase_jwt_secret != "" ? var.supabase_jwt_secret : random_password.jwt_secret.result
}

# Derive anon/service_role JWTs from the JWT secret unless explicitly provided.
data "external" "supabase_keys" {
  count   = (var.supabase_anon_key == "" || var.supabase_service_role_key == "") ? 1 : 0
  program = ["python", "${path.module}/scripts/gen-supabase-jwt.py"]

  query = {
    jwt_secret = local.jwt_secret
  }
}

locals {
  supabase_anon_key = var.supabase_anon_key != "" ? var.supabase_anon_key : (
    length(data.external.supabase_keys) > 0 ? data.external.supabase_keys[0].result.anon_key : ""
  )
  supabase_service_role_key = var.supabase_service_role_key != "" ? var.supabase_service_role_key : (
    length(data.external.supabase_keys) > 0 ? data.external.supabase_keys[0].result.service_role_key : ""
  )

  frontend_secret_name = "frontend-secrets-${var.app_namespace}"
  worker_secret_name   = "temporal-worker-secrets-${var.app_namespace}"
}

# Anon key consumed by the frontend pod (matches values-dev.yaml secretKeyRef).
resource "kubernetes_secret" "frontend" {
  metadata {
    name      = local.frontend_secret_name
    namespace = kubernetes_namespace.app.metadata[0].name
  }

  data = {
    VITE_SUPABASE_ANON_KEY = local.supabase_anon_key
  }

  type = "Opaque"
}

# Service-role key consumed by the temporal-worker and ops-api pods.
resource "kubernetes_secret" "temporal_worker" {
  metadata {
    name      = local.worker_secret_name
    namespace = kubernetes_namespace.app.metadata[0].name
  }

  data = {
    SUPABASE_SERVICE_ROLE_KEY = local.supabase_service_role_key
  }

  type = "Opaque"
}
