data "aws_availability_zones" "runner" {
  state = "available"
}

data "aws_ami" "nat_instance" {
  count       = var.enable_codebuild_runner ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-*-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

resource "aws_codestarconnections_connection" "github_runner" {
  name          = "pawlocal-codebuild-runner"
  provider_type = "GitHub"
}

resource "aws_codebuild_source_credential" "github_runner" {
  count       = var.enable_codebuild_runner ? 1 : 0
  auth_type   = "CODECONNECTIONS"
  server_type = "GITHUB"
  token       = aws_codestarconnections_connection.github_runner.arn
}

resource "aws_vpc" "codebuild_runner" {
  count                = var.enable_codebuild_runner ? 1 : 0
  cidr_block           = "10.90.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "pawlocal-codebuild-runner" }
}

resource "aws_internet_gateway" "codebuild_runner" {
  count  = var.enable_codebuild_runner ? 1 : 0
  vpc_id = aws_vpc.codebuild_runner[0].id
  tags   = { Name = "pawlocal-codebuild-runner" }
}

resource "aws_subnet" "runner_public" {
  count                   = var.enable_codebuild_runner ? 1 : 0
  vpc_id                  = aws_vpc.codebuild_runner[0].id
  availability_zone       = data.aws_availability_zones.runner.names[0]
  cidr_block              = "10.90.0.0/24"
  map_public_ip_on_launch = true
  tags                    = { Name = "pawlocal-codebuild-runner-public" }
}

resource "aws_subnet" "runner_private" {
  count             = var.enable_codebuild_runner ? 1 : 0
  vpc_id            = aws_vpc.codebuild_runner[0].id
  availability_zone = data.aws_availability_zones.runner.names[0]
  cidr_block        = "10.90.1.0/24"
  tags              = { Name = "pawlocal-codebuild-runner-private" }
}

resource "aws_route_table" "runner_public" {
  count  = var.enable_codebuild_runner ? 1 : 0
  vpc_id = aws_vpc.codebuild_runner[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.codebuild_runner[0].id
  }
  tags = { Name = "pawlocal-codebuild-runner-public" }
}

resource "aws_route_table_association" "runner_public" {
  count          = var.enable_codebuild_runner ? 1 : 0
  subnet_id      = aws_subnet.runner_public[0].id
  route_table_id = aws_route_table.runner_public[0].id
}

resource "aws_security_group" "nat_instance" {
  count       = var.enable_codebuild_runner ? 1 : 0
  name        = "pawlocal-codebuild-nat"
  description = "NAT instance for private CodeBuild runner egress."
  vpc_id      = aws_vpc.codebuild_runner[0].id

  ingress {
    description = "Forward runner traffic from the private subnet."
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = [aws_subnet.runner_private[0].cidr_block]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "codebuild_runner" {
  count       = var.enable_codebuild_runner ? 1 : 0
  name        = "pawlocal-codebuild-runner"
  description = "No inbound access; outbound traffic goes through the fixed-egress NAT instance."
  vpc_id      = aws_vpc.codebuild_runner[0].id

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "codebuild_nat" {
  count                       = var.enable_codebuild_runner ? 1 : 0
  ami                         = data.aws_ami.nat_instance[0].id
  instance_type               = "t4g.nano"
  subnet_id                   = aws_subnet.runner_public[0].id
  vpc_security_group_ids      = [aws_security_group.nat_instance[0].id]
  associate_public_ip_address = false
  source_dest_check           = false
  root_block_device {
    volume_size           = 8
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  user_data                   = <<-USERDATA
    #!/bin/bash
    set -euxo pipefail
    for attempt in {1..60}; do
      if dnf --setopt=retries=1 --setopt=timeout=10 install -y iptables-services; then
        break
      fi
      sleep 10
    done
    command -v iptables
    sysctl -w net.ipv4.ip_forward=1
    echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/99-pawlocal-nat.conf
    iptables -t nat -A POSTROUTING -o ens5 -j MASQUERADE
    service iptables save
    systemctl enable --now iptables
  USERDATA
  user_data_replace_on_change = true
  depends_on                  = [aws_route_table_association.runner_public]
  tags = {
    Name      = "pawlocal-codebuild-nat"
    Component = "deployment-runner-egress"
  }
}

resource "aws_eip" "codebuild_runner" {
  count  = var.enable_codebuild_runner ? 1 : 0
  domain = "vpc"
  tags   = { Name = "pawlocal-codebuild-runner-egress" }
}

resource "aws_eip_association" "codebuild_runner" {
  count         = var.enable_codebuild_runner ? 1 : 0
  allocation_id = aws_eip.codebuild_runner[0].id
  instance_id   = aws_instance.codebuild_nat[0].id
}

resource "aws_route_table" "runner_private" {
  count  = var.enable_codebuild_runner ? 1 : 0
  vpc_id = aws_vpc.codebuild_runner[0].id
  route {
    cidr_block           = "0.0.0.0/0"
    network_interface_id = aws_instance.codebuild_nat[0].primary_network_interface_id
  }
  tags = { Name = "pawlocal-codebuild-runner-private" }
}

resource "aws_route_table_association" "runner_private" {
  count          = var.enable_codebuild_runner ? 1 : 0
  subnet_id      = aws_subnet.runner_private[0].id
  route_table_id = aws_route_table.runner_private[0].id
}

data "aws_iam_policy_document" "codebuild_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:codebuild:${var.aws_region}:${data.aws_caller_identity.current.account_id}:project/pawlocal-deploy-runner"]
    }
  }
}

resource "aws_iam_role" "codebuild_runner" {
  count              = var.enable_codebuild_runner ? 1 : 0
  name               = "pawlocal-codebuild-deploy-runner"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
  description        = "CodeBuild runner execution role limited to logs, VPC attachment, and the GitHub App connection."
}

data "aws_iam_policy_document" "codebuild_runner" {
  statement {
    sid       = "WriteBuildLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:*:log-group:/aws/codebuild/pawlocal-deploy-runner:*"]
  }

  statement {
    sid     = "CreateRunnerNetworkInterface"
    effect  = "Allow"
    actions = ["ec2:CreateNetworkInterface"]
    resources = [
      "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:network-interface/*",
      aws_subnet.runner_private[0].arn,
      aws_security_group.codebuild_runner[0].arn,
    ]
  }

  statement {
    sid       = "ShareRunnerNetworkInterfaceWithCodeBuild"
    effect    = "Allow"
    actions   = ["ec2:CreateNetworkInterfacePermission"]
    resources = ["arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:network-interface/*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:AuthorizedService"
      values   = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "ec2:Subnet"
      values   = [aws_subnet.runner_private[0].arn]
    }
  }

  statement {
    sid       = "DeleteRunnerNetworkInterfaces"
    effect    = "Allow"
    actions   = ["ec2:DeleteNetworkInterface"]
    resources = ["arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:network-interface/*"]
    condition {
      test     = "ArnEquals"
      variable = "ec2:Vpc"
      values   = [aws_vpc.codebuild_runner[0].arn]
    }
  }

  statement {
    sid    = "DescribeVpcNetworkConfiguration"
    effect = "Allow"
    actions = [
      "ec2:DescribeDhcpOptions",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeRouteTables",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs"
    ]
    resources = ["*"]
  }

  statement {
    sid       = "UseGithubConnection"
    effect    = "Allow"
    actions   = ["codeconnections:GetConnection", "codeconnections:GetConnectionToken", "codeconnections:UseConnection"]
    resources = [aws_codestarconnections_connection.github_runner.arn]
  }
}

resource "aws_iam_role_policy" "codebuild_runner" {
  count  = var.enable_codebuild_runner ? 1 : 0
  name   = "pawlocal-codebuild-deploy-runner"
  role   = aws_iam_role.codebuild_runner[0].id
  policy = data.aws_iam_policy_document.codebuild_runner.json
}

resource "aws_codebuild_project" "github_runner" {
  count                  = var.enable_codebuild_runner ? 1 : 0
  name                   = "pawlocal-deploy-runner"
  description            = "Ephemeral GitHub Actions runner for protected PawLocal deployment jobs."
  service_role           = aws_iam_role.codebuild_runner[0].arn
  build_timeout          = 60
  concurrent_build_limit = 1
  queued_timeout         = 30

  artifacts { type = "NO_ARTIFACTS" }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
  }

  source {
    type                = "GITHUB"
    location            = "https://github.com/${var.github_repository}.git"
    git_clone_depth     = 1
    report_build_status = false
    auth {
      type     = "CODECONNECTIONS"
      resource = aws_codestarconnections_connection.github_runner.arn
    }
  }

  vpc_config {
    vpc_id             = aws_vpc.codebuild_runner[0].id
    subnets            = [aws_subnet.runner_private[0].id]
    security_group_ids = [aws_security_group.codebuild_runner[0].id]
  }

  logs_config {
    cloudwatch_logs {
      status = "ENABLED"
    }
  }

  depends_on = [aws_codebuild_source_credential.github_runner, aws_iam_role_policy.codebuild_runner]
  tags       = { Name = "pawlocal-deploy-runner" }
}

resource "aws_codebuild_webhook" "github_runner" {
  count        = var.enable_codebuild_runner ? 1 : 0
  project_name = aws_codebuild_project.github_runner[0].name
  build_type   = "BUILD"

  filter_group {
    filter {
      type    = "EVENT"
      pattern = "WORKFLOW_JOB_QUEUED"
    }
  }
}
