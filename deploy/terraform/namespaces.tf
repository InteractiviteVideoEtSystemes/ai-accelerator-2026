# ---------------------------------------------------------------------------
# Kubernetes namespaces
# ---------------------------------------------------------------------------

resource "kubernetes_namespace" "app" {
  metadata {
    name = var.app_namespace
    labels = {
      "app.kubernetes.io/part-of"    = var.prefix
      "app.factory/environment"      = var.environment
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
}

resource "kubernetes_namespace" "supabase" {
  count = var.enable_supabase ? 1 : 0

  metadata {
    name = var.supabase_namespace
    labels = {
      "app.kubernetes.io/part-of"    = var.prefix
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
}

resource "kubernetes_namespace" "temporal" {
  count = var.enable_temporal ? 1 : 0

  metadata {
    name = var.temporal_namespace
    labels = {
      "app.kubernetes.io/part-of"    = var.prefix
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
}
