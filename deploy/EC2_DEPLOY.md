# EC2 Backend Deployment

This project can run on a single Ubuntu EC2 instance with `gunicorn` behind `nginx`.

## 1. Launch the server

- Create an Ubuntu EC2 instance.
- Open inbound ports:
  - `22` for SSH
  - `80` for HTTP
  - `443` for HTTPS if you later add TLS
- Attach an IAM role if you want to use instance-role Bedrock credentials instead of keys in `.env`.

## 2. Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

## 3. Copy the project

```bash
cd /home/ubuntu
git clone <your-repo-url> cis
cd cis
```

## 4. Configure environment

Create `/home/ubuntu/cis/.env` with your production values:

```env
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=
BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
BEDROCK_BASE_MODEL_ID=amazon.nova-lite-v1:0
BEDROCK_INFERENCE_PROFILE_ID=apac.amazon.nova-lite-v1:0
OPENAI_API_KEY=...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

## 5. Install Python dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Build the frontend

If Amplify is serving the frontend, set `VITE_API_BASE_URL` there and skip this step.

If EC2 should also serve the frontend:

```bash
cd /home/ubuntu/cis/frontend
npm ci
npm run build
```

## 7. Install and start the backend service

```bash
sudo cp /home/ubuntu/cis/deploy/cis-backend.service /etc/systemd/system/cis-backend.service
sudo systemctl daemon-reload
sudo systemctl enable cis-backend
sudo systemctl start cis-backend
sudo systemctl status cis-backend
```

## 8. Configure nginx

```bash
sudo cp /home/ubuntu/cis/deploy/nginx-cis.conf /etc/nginx/sites-available/cis
sudo ln -s /etc/nginx/sites-available/cis /etc/nginx/sites-enabled/cis
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

## 9. Verify the API

```bash
curl http://<ec2-public-ip>/api/health
curl "http://<ec2-public-ip>/api/controls?os_type=linux"
```

## 10. Point Amplify to the EC2 backend

In Amplify environment variables, set:

```env
VITE_API_BASE_URL=http://<ec2-public-ip>
```

If you attach a domain such as `https://api.example.com`, use that instead.

## Notes

- `chroma_db/` must persist on the instance if you rely on uploaded benchmark data.
- For production, add HTTPS with a domain and `certbot`.
- If you use an EC2 IAM role for Bedrock, you can omit `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.
