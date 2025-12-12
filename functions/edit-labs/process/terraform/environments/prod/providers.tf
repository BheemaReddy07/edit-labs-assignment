terraform {
  backend "s3" {
    bucket = "bucketforterraform-23"
    # Key is now environment-specific
    key    = "terraform/state/prod/terraform.tfstate" 
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region
}