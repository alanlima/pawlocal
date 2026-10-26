# Built-in provider only: exercise Terraform's real dependency graph without AWS.
run "original" {
  command   = apply
  state_key = "original"
  module { source = "./attached" }
}
run "unsafe_direct_removal" {
  command   = apply
  state_key = "original"
  module { source = "./removed" }
}
run "partial" {
  command   = apply
  state_key = "partial"
  module { source = "./attached" }
}
run "retain_and_detach" {
  command   = apply
  state_key = "partial"
  module { source = "./retained" }
  assert {
    condition     = output.service_id == run.partial.service_id && output.certificate_id == run.partial.certificate_id && output.custom_domain == null
    error_message = "Pre-detach must preserve both identities and remove the service association."
  }
}
run "delete_unused_certificate" {
  command   = apply
  state_key = "partial"
  module { source = "./removed" }
  assert {
    condition     = output.service_id == run.partial.service_id && output.custom_domain == null
    error_message = "Final cleanup must keep the already detached service identity."
  }
}
