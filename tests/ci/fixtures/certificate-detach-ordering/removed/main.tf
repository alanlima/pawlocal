resource "terraform_data" "service" { input = { custom_domain = null } }
output "service_id" { value = terraform_data.service.id }
output "custom_domain" { value = terraform_data.service.output.custom_domain }
