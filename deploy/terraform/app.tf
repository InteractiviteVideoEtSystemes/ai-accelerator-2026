# ---------------------------------------------------------------------------
# Application (frontend + temporal-worker + ops-api) via the local charts/app.
#
# Image overrides and resolved namespaces/URLs are injected here so the shipped
# chart and its values-dev.yaml placeholders are never edited in place.
# ---------------------------------------------------------------------------

locals {
  acr_login_server = azurerm_container_registry.this.login_server

  # In-cluster Supabase Kong endpoint (service-role traffic from the worker).
  supabase_internal_url = "http://supabase-supabase-kong.${var.supabase_namespace}.svc.cluster.local"

  # Browser-facing Supabase URL; falls back to the internal one until DNS exists.
  supabase_browser_url = var.supabase_public_url != "" ? var.supabase_public_url : local.supabase_internal_url

  # Temporal frontend service created by the temporal Helm release.
  temporal_address = "temporal-frontend.${var.temporal_namespace}.svc.cluster.local:7233"
}

# Optionally build + push the app images into the ACR before the release.
# Uses `az acr build` so no local Docker daemon push is required.
resource "null_resource" "build_frontend_image" {
  count = var.enable_app && var.build_and_push_images ? 1 : 0

  triggers = {
    tag      = var.image_tag
    registry = local.acr_login_server
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = "az acr build --registry ${azurerm_container_registry.this.name} --image ${var.frontend_image_repository}:${var.image_tag} ./frontend"
  }
}

resource "null_resource" "build_worker_image" {
  count = var.enable_app && var.build_and_push_images ? 1 : 0

  triggers = {
    tag      = var.image_tag
    registry = local.acr_login_server
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = "az acr build --registry ${azurerm_container_registry.this.name} --image ${var.worker_image_repository}:${var.image_tag} ./temporal"
  }
}

resource "helm_release" "app" {
  count = var.enable_app ? 1 : 0

  name      = "rental-app"
  namespace = kubernetes_namespace.app.metadata[0].name
  chart     = "${path.module}/../../charts/app"

  values = [yamlencode({
    imageRegistry = local.acr_login_server

    frontend = {
      replicaCount = 1
      image = {
        repository = var.frontend_image_repository
        tag        = var.image_tag
        pullPolicy = "Always"
      }
      service = {
        type = "LoadBalancer"
        port = 80
      }
      ingress = {
        enabled = false
      }
      resources = {
        requests = { cpu = "100m", memory = "512Mi" }
        limits   = { cpu = "1", memory = "1Gi" }
      }
      env = {
        supabaseUrl = local.supabase_browser_url
        apiUrl      = "${local.supabase_browser_url}/functions/v1"
      }
      secrets = {
        supabaseAnonKey = {
          secretName = local.frontend_secret_name
          key        = "VITE_SUPABASE_ANON_KEY"
        }
      }
    }

    temporalWorker = {
      replicaCount = 1
      image = {
        repository = var.worker_image_repository
        tag        = var.image_tag
        pullPolicy = "Always"
      }
      temporal = {
        address   = local.temporal_address
        namespace = "default"
        taskQueue = "${var.app_namespace}-main"
      }
      supabase = {
        url = local.supabase_internal_url
      }
      secrets = {
        supabaseServiceRoleKey = {
          secretName = local.worker_secret_name
          key        = "SUPABASE_SERVICE_ROLE_KEY"
        }
      }
    }

    opsApi = {
      replicaCount = 1
      image = {
        repository = var.worker_image_repository
        tag        = var.image_tag
        pullPolicy = "Always"
      }
      temporal = {
        address   = local.temporal_address
        namespace = "default"
      }
      supabase = {
        url = local.supabase_internal_url
      }
      secrets = {
        supabaseServiceRoleKey = {
          secretName = local.worker_secret_name
          key        = "SUPABASE_SERVICE_ROLE_KEY"
        }
      }
    }
  })]

  timeout         = 600
  wait            = true
  atomic          = false
  cleanup_on_fail = true

  depends_on = [
    kubernetes_secret.frontend,
    kubernetes_secret.temporal_worker,
    helm_release.temporal,
    helm_release.supabase,
    null_resource.build_frontend_image,
    null_resource.build_worker_image,
  ]
}
