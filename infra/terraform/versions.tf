terraform {
  required_version = ">= 1.10.0"

  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
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
    tags = local.common_tags
  }
}

# CloudFront only accepts viewer certificates from ACM in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = local.common_tags
  }
}

provider "aws" {
  alias  = "fullstack"
  region = var.aws_region

  default_tags {
    tags = {
      costcenter  = "personal"
      environment = "mvp"
      managedby   = "terraform"
      project     = "pawlocal"
      component   = "fullstack-mvp"
      workload    = "application"
    }
  }
}
