# The root module reads the values from stage.tfvars automatically 
# and exposes them as `var.variable_name`.

# Call the core infrastructure module
module "ecs_pipeline" {
  source = "../../modules/ecs-pipeline"

  environment           = var.environment
  aws_region            = var.aws_region
  
  # ECS/ECR names
  ecr_repository_name   = var.ecr_repository_name
  ecs_cluster_name      = var.ecs_cluster_name
  ecs_task_family       = var.ecs_task_family
  container_name        = var.container_name

  # Environment-specific table names
  editlabs_table_name   = var.editlabs_table_name
  recc_table_name       = var.recc_table_name
  
  # VPC settings
  vpc_cidr              = var.vpc_cidr
  public_subnet_cidr    = var.public_subnet_cidr
  private_subnet_cidr   = var.private_subnet_cidr
  availability_zone     = var.availability_zone
}