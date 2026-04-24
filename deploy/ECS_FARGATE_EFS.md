# ECS Fargate + EFS Deployment

This backend is a good fit for `ECS Fargate + EFS`:

- ECS Fargate runs the Flask container
- EFS persists `chroma_db`
- ALB exposes the backend over HTTP/HTTPS
- Amplify points to the ALB or backend domain via `VITE_API_BASE_URL`

## 1. Build and push the image

Create an ECR repository named `cis-backend`, then:

```bash
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com
docker build -t cis-backend .
docker tag cis-backend:latest <account-id>.dkr.ecr.<region>.amazonaws.com/cis-backend:latest
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/cis-backend:latest
```

## 2. Create persistent storage

- Create an EFS file system
- Create mount targets in the private subnets used by Fargate
- Create an EFS access point, for example `/cis-data`

The task mounts EFS at `/mnt/data`, and the app writes Chroma files to:

```env
CHROMA_PATH=/mnt/data/chroma_db
```

## 3. Create IAM roles

- `ecsTaskExecutionRole` for pulling images and writing logs
- `cisBackendTaskRole` for Bedrock and other app permissions

Attach Bedrock permissions to the task role, for example `bedrock:InvokeModel`.

## 4. Register the task definition

Use [ecs-task-definition.json](./ecs-task-definition.json) and replace:

- `<account-id>`
- `<region>`
- `fs-xxxxxxxx`
- `fsap-xxxxxxxx`
- Secrets Manager ARN values

Then register it:

```bash
aws ecs register-task-definition --cli-input-json file://deploy/ecs-task-definition.json
```

## 5. Create the ECS service

Recommended:

- Launch type: `FARGATE`
- Desired count: `1` to start
- Subnets: private subnets
- Security group: allow inbound `5000` from the ALB security group

## 6. Create an Application Load Balancer

- ALB in public subnets
- Listener on `80` or `443`
- Target group protocol: HTTP
- Health check path:

```text
/api/health
```

The container listens on port `5000`.

## 7. Security groups

- `alb-sg`: allow inbound `80/443` from the internet
- `ecs-task-sg`: allow inbound `5000` from `alb-sg`
- `efs-sg`: allow inbound `2049` from `ecs-task-sg`

## 8. Amplify frontend configuration

Set:

```env
VITE_API_BASE_URL=https://<your-alb-or-domain>
```

Then redeploy Amplify.

## 9. Persisted data behavior

Because `CHROMA_PATH` points to EFS, indexed benchmark data survives task restarts and deployments.

## Notes

- Store sensitive values in Secrets Manager or Parameter Store instead of plain environment variables where possible.
- If you scale beyond one task, EFS can still be shared, but verify ChromaDB concurrency behavior for your workload.
- Start with one backend task until the persistence and ingestion flow is stable.
