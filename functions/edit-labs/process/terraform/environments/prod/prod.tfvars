environment             = "prod"
aws_region              = "us-east-1"

# --- Dynamic Service Names ---
editlabs_table_name     = "edit-labs" 
recc_table_name         = "recommendations"
ecr_repository_name     = "my-app-repo-prod"
ecs_cluster_name        = "edit-labs-cluster-v2-prod"
ecs_task_family         = "edit-labs-task-family-prod"
container_name          = "edit-labs-container-prod"

# --- VPC & Networking (REQUIRED) ---
vpc_cidr                = "10.0.0.0/16"
public_subnet_cidr      = "10.0.1.0/24"
private_subnet_cidr     = "10.0.2.0/24"
availability_zone       = "us-east-1a"
