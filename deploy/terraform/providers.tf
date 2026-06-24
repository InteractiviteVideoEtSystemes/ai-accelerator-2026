# ---------------------------------------------------------------------------
# Provider configuration
#
# azurerm     -> provisions the Azure platform (RG, ACR, AKS, Log Analytics).
# kubernetes  -> manages namespaces + secrets INSIDE the AKS cluster.
# helm        -> installs Temporal, Supabase and the app chart INSIDE the cluster.
#
# The kubernetes/helm providers are wired to the kubeconfig that the AKS module
# outputs, so a single `terraform apply` first builds the cluster and then talks
# to it. The credentials come from azurerm_kubernetes_cluster.this.kube_config.
# ---------------------------------------------------------------------------

provider "azurerm" {
  features {}

  # subscription_id / tenant_id are taken from the environment (az login) or can
  # be set explicitly here / via variables if you manage multiple subscriptions.
  subscription_id = var.subscription_id != "" ? var.subscription_id : null
  tenant_id       = var.tenant_id != "" ? var.tenant_id : null
}

provider "kubernetes" {
  host                   = azurerm_kubernetes_cluster.this.kube_config.0.host
  client_certificate     = base64decode(azurerm_kubernetes_cluster.this.kube_config.0.client_certificate)
  client_key             = base64decode(azurerm_kubernetes_cluster.this.kube_config.0.client_key)
  cluster_ca_certificate = base64decode(azurerm_kubernetes_cluster.this.kube_config.0.cluster_ca_certificate)
}

provider "helm" {
  kubernetes {
    host                   = azurerm_kubernetes_cluster.this.kube_config.0.host
    client_certificate     = base64decode(azurerm_kubernetes_cluster.this.kube_config.0.client_certificate)
    client_key             = base64decode(azurerm_kubernetes_cluster.this.kube_config.0.client_key)
    cluster_ca_certificate = base64decode(azurerm_kubernetes_cluster.this.kube_config.0.cluster_ca_certificate)
  }
}
