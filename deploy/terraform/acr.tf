# ---------------------------------------------------------------------------
# Azure Container Registry
# Holds the frontend and temporal-worker images that the app chart pulls.
# AKS pulls via its kubelet managed identity (AcrPull role, see aks.tf) so no
# imagePullSecret is strictly required when using that identity.
# ---------------------------------------------------------------------------

resource "azurerm_container_registry" "this" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = var.acr_sku
  admin_enabled       = false
  tags                = var.tags
}
