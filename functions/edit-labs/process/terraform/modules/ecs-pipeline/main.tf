# --- Data Source (Ensure this is at the top of main.tf) ---
data "aws_caller_identity" "current" {}

# --- VPC & Networking (Using Default VPC) ---
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# -----------------------------------------------------------------
# 0. Networking Requirements: Security Groups and VPC Endpoints (Option 2 Fix)
# -----------------------------------------------------------------

# Security Group for Fargate Tasks (The task is attached to this SG)
resource "aws_security_group" "ecs_fargate_sg" {
  name        = "${var.project_name}-${var.environment}-fargate-sg"
  description = "Security group for ECS Fargate tasks to allow egress"
  vpc_id      = data.aws_vpc.default.id

  # Allow all outbound traffic (needed to reach ECR/SSM/S3/CloudWatch via VPC Endpoints)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-fargate-sg"
  }
}




# --- ECR (from ecr.tf) ---
resource "aws_ecr_repository" "my_repository" {
  name                 = var.ecr_repository_name 
  image_tag_mutability = "MUTABLE"

  lifecycle {
    prevent_destroy = true 
  }
}

# -----------------------------------------------------------------
# 1. TASK EXECUTION ROLE (for ECS Agent)
# -----------------------------------------------------------------
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "${var.project_name}-${var.environment}-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# -----------------------------------------------------------------
# 2. TASK ROLE (for Your Application)
# -----------------------------------------------------------------
resource "aws_iam_role" "ecs_task_role" {
  name = "${var.project_name}-${var.environment}-task-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

# --- S3 Policy ---
resource "aws_iam_policy" "s3_read_policy" {
  name        = "${var.project_name}-${var.environment}-s3-read-policy"
  description = "Allows reading raw videos from S3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:GetObject"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:s3:::*/*" 
      }
    ]
  })
}

# --- DynamoDB Policy - USES VARIABLES FOR TABLE NAMES ---
resource "aws_iam_policy" "dynamodb_policy" {
  name        = "${var.project_name}-${var.environment}-dynamodb-policy"
  description = "Allows read/write to tables defined by variables"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [ 
          "dynamodb:GetItem", 
          "dynamodb:UpdateItem", 
          "dynamodb:PutItem", 
          "dynamodb:Query" 
        ]
        Effect = "Allow"
        Resource = [
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.editlabs_table_name}",
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.recc_table_name}"
        ]
      }
    ]
  })
}

# Attach S3 policy to the task role (Ensures policy is bound)
resource "aws_iam_role_policy_attachment" "task_s3_policy" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.s3_read_policy.arn
}

# Attach DynamoDB policy to the task role (Ensures policy is bound)
resource "aws_iam_role_policy_attachment" "task_dynamodb_policy" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.dynamodb_policy.arn
}

# --- ECS & Logging (from ecs.tf) ---
resource "aws_ecs_cluster" "my_cluster" {
  name = var.ecs_cluster_name
}

resource "aws_cloudwatch_log_group" "ecs_logs" {
  name              = "/ecs/${var.ecs_task_family}-${var.environment}"
  retention_in_days = 30
}

# ECS Task Definition - NOW USES VARIABLES FOR ENVIRONMENT
resource "aws_ecs_task_definition" "my_task" {
  family                   = var.ecs_task_family
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"

  execution_role_arn = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn      = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = var.container_name
    image     = "${aws_ecr_repository.my_repository.repository_url}:latest"
    essential = true

    environment = [
      { name = "PAYLOAD_JSON", value = "{}" },
      { name = "EDITLABS_TABLE_NAME", value = var.editlabs_table_name },
      { name = "RECC_TABLE_NAME", value = var.recc_table_name },
      { name = "SERVICE_NAME", value = "process-raw-video-${var.environment}" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"       = aws_cloudwatch_log_group.ecs_logs.name
        "awslogs-region"      = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

# -----------------------------------------------------------------
# --- SSM Parameters (The Bridge to SAM) ---
# -----------------------------------------------------------------

resource "aws_ssm_parameter" "ecs_cluster_arn" {
  name  = "/${var.project_name}/${var.environment}/ecs/cluster-arn"
  type  = "String"
  value = aws_ecs_cluster.my_cluster.arn
}

resource "aws_ssm_parameter" "ecs_task_definition_arn" {
  name  = "/${var.project_name}/${var.environment}/ecs/task-definition-arn"
  type  = "String"
  value = aws_ecs_task_definition.my_task.arn
}

resource "aws_ssm_parameter" "ecs_container_name" {
  name  = "/${var.project_name}/${var.environment}/ecs/container-name"
  type  = "String"
  value = var.container_name
}

resource "aws_ssm_parameter" "ecs_subnets" {
  name  = "/${var.project_name}/${var.environment}/ecs/subnets"
  type  = "String"
  value = join(",", data.aws_subnets.default.ids) # Using default public subnets
}

resource "aws_ssm_parameter" "ecs_security_groups" {
  name  = "/${var.project_name}/${var.environment}/ecs/security-groups"
  type  = "String"
  # Uses the ID of the dedicated Fargate Security Group
  value = aws_security_group.ecs_fargate_sg.id
}

resource "aws_ssm_parameter" "ecs_execution_role_arn" {
  name  = "/${var.project_name}/${var.environment}/ecs/execution-role-arn"
  type  = "String"
  value = aws_iam_role.ecs_task_execution_role.arn
}

resource "aws_ssm_parameter" "ecs_task_role_arn" {
  name  = "/${var.project_name}/${var.environment}/ecs/task-role-arn"
  type  = "String"
  value = aws_iam_role.ecs_task_role.arn
}