variable "environment" {
  type        = string
  description = "The deployment environment (dev, stage, prod, etc.)."
}

variable "aws_region" {
  type        = string
  description = "The AWS region."
}

# --- Naming ---
variable "project_name" {
  type        = string
  default     = "edit-labs"
}

# --- ECR ---
variable "ecr_repository_name" {
  type        = string
  description = "The name of the ECR repository."
}

# --- ECS ---
variable "ecs_cluster_name" {
  type        = string
  description = "The name of the ECS cluster."
}
variable "ecs_task_family" {
  type        = string
  description = "The family name of the ECS task definition."
}
variable "container_name" {
  type        = string
  description = "The name of the container in the ECS task definition."
}

# --- DynamoDB Table Names (Dynamic per environment) ---
variable "editlabs_table_name" {
  type        = string
  description = "The name of the Edit Labs DynamoDB table."
}

variable "recc_table_name" {
  type        = string
  description = "The name of the recommendations DynamoDB table."
}

# --- VPC & Networking ---
variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}
variable "public_subnet_cidr" {
  type    = string
  default = "10.0.1.0/24"
}
variable "private_subnet_cidr" {
  type    = string
  default = "10.0.2.0/24"
}
variable "availability_zone" {
  type    = string
  default = "us-east-1a"
}