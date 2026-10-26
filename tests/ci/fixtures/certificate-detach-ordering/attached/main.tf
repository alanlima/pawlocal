resource "terraform_data" "certificate" { input = "existing-certificate" }
output "certificate_id" { value = terraform_data.certificate.id }
resource "terraform_data" "service" { input = { custom_domain = terraform_data.certificate.output } }
output "service_id" { value = terraform_data.service.id }
output "custom_domain" { value = terraform_data.service.output.custom_domain }
