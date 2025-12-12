# The root module must declare every variable it accepts from the .tfvars file.
variable "environment" {}
variable "aws_region" {}
variable "editlabs_table_name" {}
variable "recc_table_name" {}
variable "ecr_repository_name" {}
variable "ecs_cluster_name" {}
variable "ecs_task_family" {}
variable "container_name" {}
variable "vpc_cidr" {}
variable "public_subnet_cidr" {}
variable "private_subnet_cidr" {}
variable "availability_zone" {}