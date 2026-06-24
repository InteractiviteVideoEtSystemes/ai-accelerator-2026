# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "resource_group_name" {
  description = "Name of the resource group."
  value       = azurerm_resource_group.this.name
}

output "aks_cluster_name" {
  description = "AKS cluster name."
  value       = azurerm_kubernetes_cluster.this.name
}

output "acr_login_server" {
  description = "ACR login server (use as the image registry prefix)."
  value       = azurerm_container_registry.this.login_server
}

output "acr_name" {
  description = "ACR name (for `az acr build --registry`)."
  value       = azurerm_container_registry.this.name
}

output "get_credentials_command" {
  description = "Command to merge the AKS kubeconfig into your local kubectl."
  value       = "az aks get-credentials --resource-group ${azurerm_resource_group.this.name} --name ${azurerm_kubernetes_cluster.this.name}"
}

output "kube_config_raw" {
  description = "Raw kubeconfig for the AKS cluster."
  value       = azurerm_kubernetes_cluster.this.kube_config_raw
  sensitive   = true
}

output "supabase_internal_url" {
  description = "In-cluster Supabase Kong endpoint used by the worker."
  value       = local.supabase_internal_url
}

output "frontend_service_hint" {
  description = "How to find the frontend LoadBalancer public IP once the app is deployed."
  value       = "kubectl get svc -n ${var.app_namespace} -l app.kubernetes.io/component=frontend -o wide"
}
