terraform {
  required_version = "= 1.14.3"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
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

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      project     = var.project_name
      environment = "production"
      managedby   = "terraform"
    }
  }
}
