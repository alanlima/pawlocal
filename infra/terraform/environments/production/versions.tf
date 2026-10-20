terraform {
  required_version = ">= 1.10.0, < 2.0.0"
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
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      project     = "pawlocal"
      environment = "production"
      managedby   = "terraform"
    }
  }
}
