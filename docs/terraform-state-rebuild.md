# Terraform state deployment limitation

The repository has a legacy Terraform state that combines development and production resources, while the current deployment workflows expect independent development, production, and identity states. This release does not provide a destructive recovery workflow or a state migration procedure.

Do not run the independent environment deployment workflows against the existing combined state. The combined state cannot be assumed to split safely, and this PR does not authorize its destruction or migration. Deployment remains blocked until the owner approves a separate state reconciliation approach and that work is implemented and reviewed.

The normal development and production workflows continue to create sanitized plans, transfer the exact plan privately, require GitHub Environment approval after plan review, and apply only that saved plan. Those safeguards do not resolve the legacy-state ownership conflict.
