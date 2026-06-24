# ---------------------------------------------------------------------------
# AKS cluster + AcrPull role assignment
# ---------------------------------------------------------------------------

resource "azurerm_kubernetes_cluster" "this" {
  name                = local.aks_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  dns_prefix          = local.aks_name
  kubernetes_version  = var.kubernetes_version != "" ? var.kubernetes_version : null
  tags                = var.tags

  default_node_pool {
    name                 = "system"
    vm_size              = var.aks_node_vm_size
    node_count           = var.aks_enable_auto_scaling ? null : var.aks_node_count
    enable_auto_scaling  = var.aks_enable_auto_scaling
    min_count            = var.aks_enable_auto_scaling ? var.aks_min_node_count : null
    max_count            = var.aks_enable_auto_scaling ? var.aks_max_node_count : null
    orchestrator_version = var.kubernetes_version != "" ? var.kubernetes_version : null
    type                 = "VirtualMachineScaleSets"
  }

  # System-assigned managed identity for the cluster control plane.
  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin    = "azure"
    load_balancer_sku = "standard"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  }
}

# Allow the cluster's kubelet identity to pull images from the ACR.
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                            = azurerm_container_registry.this.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.this.kubelet_identity.0.object_id
  skip_service_principal_aad_check = true
}
