# ---------------------------------------------------------------------------
# Core platform: Resource Group + Log Analytics workspace
# ---------------------------------------------------------------------------

locals {
  # Derived names. ACR names must be globally unique and alphanumeric only.
  name_suffix         = "${var.prefix}-${var.environment}"
  resource_group_name = var.resource_group_name != "" ? var.resource_group_name : "rg-${local.name_suffix}-frc-001"
  aks_name            = "aks-${local.name_suffix}-frc-001"
  acr_name            = lower(replace("acr${var.prefix}${var.environment}frc", "/[^a-z0-9]/", ""))
  log_analytics_name  = "log-${local.name_suffix}-frc-001"
}

resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = var.location
  tags     = var.tags
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = local.log_analytics_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}
