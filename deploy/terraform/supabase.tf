# ---------------------------------------------------------------------------
# Supabase (in-cluster) via the community Helm chart.
#
# The chart bundles Postgres, Kong (API gateway), GoTrue (auth), PostgREST,
# Realtime, Storage and Studio. The worker reaches it through the internal Kong
# service: http://supabase-supabase-kong.<supabase_namespace>.svc.cluster.local
# (matches charts/app/values-dev.yaml).
#
# NOTE: the community chart's structure/values evolve; pin and review the chart
# version and its values schema before the first real apply.
# ---------------------------------------------------------------------------

resource "helm_release" "supabase" {
  count = var.enable_supabase ? 1 : 0

  name       = "supabase"
  namespace  = kubernetes_namespace.supabase[0].metadata[0].name
  repository = "https://supabase-community.github.io/supabase-kubernetes"
  chart      = "supabase"
  version    = "0.1.3"

  values = [yamlencode({
    secret = {
      jwt = {
        anonKey    = local.supabase_anon_key
        serviceKey = local.supabase_service_role_key
        secret     = local.jwt_secret
      }
      db = {
        password = random_password.postgres_password.result
      }
      dashboard = {
        username = "supabase"
        password = random_password.dashboard_password.result
      }
    }
    db = {
      enabled = true
    }
    studio = {
      enabled = true
    }
    # Kong is the API gateway the worker/frontend talk to.
    kong = {
      enabled = true
    }
  })]

  timeout         = 900
  wait            = false
  atomic          = false
  cleanup_on_fail = true
}
