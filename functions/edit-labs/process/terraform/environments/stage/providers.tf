terraform {
  backend "s3" {
    bucket = "bucketforterraform-bheema-23-stage"
    # Key is now environment-specific
    key    = "terraform/state/stage/terraform.tfstate" 
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region
}