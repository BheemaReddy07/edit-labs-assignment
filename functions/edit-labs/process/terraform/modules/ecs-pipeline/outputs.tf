
output "ecs_cluster_arn" {
  description = "The ARN of the ECS Cluster"
  value       = aws_ecs_cluster.my_cluster.arn
}

output "task_definition_arn" {
  description = "ARN of the task definition"
  value       = aws_ecs_task_definition.my_task.arn
}

output "private_subnets" {
  description = "List of subnets (using Default VPC subnets)"
  value       = data.aws_subnets.default.ids
}

output "ssm_cluster_arn_path" {
  description = "SSM Parameter path for ECS Cluster ARN"
  value       = aws_ssm_parameter.ecs_cluster_arn.name
}