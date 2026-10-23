resource "aws_security_group" "service_sg" {
  name        = "streamlineops-service-sg"
  description = "Security group for StreamlineOps application services"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "HTTPS from load balancer"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
    description = "HTTP health checks from load balancer"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "streamlineops-service-sg"
    Environment = "production"
  }
}

resource "aws_security_group" "alb_sg" {
  name        = "streamlineops-alb-sg"
  description = "Security group for application load balancer"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow outbound to services"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [module.vpc.vpc_cidr_block]
  }

  tags = {
    Name        = "streamlineops-alb-sg"
    Environment = "production"
  }
}

resource "aws_security_group" "database_sg" {
  name        = "streamlineops-database-sg"
  description = "Security group for database instances"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "PostgreSQL from services only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.service_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "streamlineops-database-sg"
    Environment = "production"
  }
}
