# ---------------------------------------------------------------------------
# Temporal server (in-cluster) via the official temporalio Helm chart.
#
# Installs Temporal with its own bundled Cassandra/Postgres per the chart
# defaults. The app's values reference temporal-frontend.<ns>.svc.cluster.local:7233.
# For a lightweight dev install we disable the heavy observability add-ons.
# ---------------------------------------------------------------------------

resource "helm_release" "temporal" {
  count = var.enable_temporal ? 1 : 0

  name       = "temporal"
  namespace  = kubernetes_namespace.temporal[0].metadata[0].name
  repository = "https://go.temporal.io/helm-charts"
  chart      = "temporal"
  version    = "0.50.0"

  # Keep the dev footprint small: single replicas, no Elasticsearch/Grafana.
  values = [yamlencode({
    server = {
      replicaCount = 1
    }
    cassandra = {
      config = {
        cluster_size = 1
      }
    }
    elasticsearch = {
      enabled = false
    }
    prometheus = {
      enabled = false
    }
    grafana = {
      enabled = false
    }
    # Temporal Web UI (handy for dev).
    web = {
      enabled = true
    }
  })]

  # The chart provisions multiple workloads; give it room.
  timeout         = 900
  wait            = true
  atomic          = false
  cleanup_on_fail = true
}
