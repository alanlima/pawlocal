terraform {
  required_version = "= 1.14.3"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "= 2.8.1"
    }
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
      configuration_aliases = [
        aws.cognito_deployment,
      ]
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    time = {
      source  = "hashicorp/time"
      version = "= 0.13.1"
    }
  }
}
