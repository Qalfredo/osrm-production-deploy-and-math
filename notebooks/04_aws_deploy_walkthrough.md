# OSRM AWS Deployment Walkthrough

Minimal single-instance deployment of [OSRM (Project-OSRM)](https://github.com/Project-OSRM/osrm-backend) on AWS using the AWS CLI. No Terraform, no ECS, no load balancer — just one EC2 instance running Docker.

> **Design philosophy**: the cheapest setup that actually works. Venezuela's CH graph fits in ~3 GB RAM, so a `t3.medium` (4 GB, $0.042/hr on-demand) is the minimum viable instance.

---

## Architecture

```
Internet
    │
    ▼
EC2 t3.medium (Ubuntu 22.04)
    ├── Docker
    │     └── ghcr.io/project-osrm/osrm-backend
    ├── /home/ubuntu/osrm-data/   ← EBS volume (20 GB)
    │     ├── venezuela-latest.osrm.*
    │     └── (preprocessed CH graph)
    └── :5000  ← OSRM HTTP API
```

**Estimated monthly cost**: ~$31/month (t3.medium on-demand + 20 GB EBS).
**With a spot instance**: ~$13/month (but interruptible).

---

## Prerequisites

- AWS CLI installed and configured: `aws configure`
- An existing EC2 key pair (or create one in this guide)
- Default VPC in your region (all new AWS accounts have one)

Check your CLI is working:

```bash
aws sts get-caller-identity
```

Set your target region once:

```bash
export AWS_REGION=us-east-1   # change to your preferred region
```

---

## Step 1 — Create a key pair

Skip this step if you already have one.

```bash
aws ec2 create-key-pair \
  --region "$AWS_REGION" \
  --key-name osrm-key \
  --query 'KeyMaterial' \
  --output text > ~/.ssh/osrm-key.pem

chmod 400 ~/.ssh/osrm-key.pem
echo "Key saved to ~/.ssh/osrm-key.pem"
```

---

## Step 2 — Create a security group

OSRM only needs two ports open: SSH for administration and 5000 for the API. Replace `YOUR_IP` with your actual IP (run `curl ifconfig.me` to get it). Restricting port 5000 to your IP avoids exposing the API to the public internet.

```bash
# Get your default VPC ID
VPC_ID=$(aws ec2 describe-vpcs \
  --region "$AWS_REGION" \
  --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' \
  --output text)

echo "Default VPC: $VPC_ID"

# Create security group
SG_ID=$(aws ec2 create-security-group \
  --region "$AWS_REGION" \
  --group-name osrm-sg \
  --description "OSRM routing server" \
  --vpc-id "$VPC_ID" \
  --query 'GroupId' \
  --output text)

echo "Security group: $SG_ID"

# SSH from anywhere (tighten this if desired)
aws ec2 authorize-security-group-ingress \
  --region "$AWS_REGION" \
  --group-id "$SG_ID" \
  --protocol tcp --port 22 --cidr 0.0.0.0/0

# OSRM API — restrict to your IP
YOUR_IP=$(curl -s ifconfig.me)
aws ec2 authorize-security-group-ingress \
  --region "$AWS_REGION" \
  --group-id "$SG_ID" \
  --protocol tcp --port 5000 --cidr "${YOUR_IP}/32"

echo "Port 5000 open for: $YOUR_IP"
```

---

## Step 3 — Launch EC2 instance

Find the latest Ubuntu 22.04 LTS AMI for your region, then launch a `t3.medium`:

```bash
# Get latest Ubuntu 22.04 LTS AMI
AMI_ID=$(aws ec2 describe-images \
  --region "$AWS_REGION" \
  --owners 099720109477 \
  --filters \
    Name=name,Values='ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*' \
    Name=state,Values=available \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
  --output text)

echo "Ubuntu 22.04 AMI: $AMI_ID"

# Launch instance
INSTANCE_ID=$(aws ec2 run-instances \
  --region "$AWS_REGION" \
  --image-id "$AMI_ID" \
  --instance-type t3.medium \
  --key-name osrm-key \
  --security-group-ids "$SG_ID" \
  --block-device-mappings '[{
    "DeviceName": "/dev/sda1",
    "Ebs": {
      "VolumeSize": 20,
      "VolumeType": "gp3",
      "DeleteOnTermination": true
    }
  }]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=osrm-server}]' \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "Instance launched: $INSTANCE_ID"

# Wait for it to be running
echo "Waiting for instance to reach running state..."
aws ec2 wait instance-running \
  --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID"

echo "Instance is running."
```

---

## Step 4 — Get the public IP

```bash
PUBLIC_IP=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

echo "Public IP: $PUBLIC_IP"
echo "SSH: ssh -i ~/.ssh/osrm-key.pem ubuntu@$PUBLIC_IP"
```

Wait ~30 seconds for SSH to become available before connecting.

---

## Step 5 — Install Docker on the instance

```bash
ssh -i ~/.ssh/osrm-key.pem ubuntu@"$PUBLIC_IP" << 'EOF'
  # Update and install Docker
  sudo apt-get update -q
  sudo apt-get install -y -q docker.io

  # Start Docker and add ubuntu user to the docker group
  sudo systemctl enable --now docker
  sudo usermod -aG docker ubuntu

  echo "Docker version: $(docker --version)"
EOF

echo "Docker installed. Reconnecting to pick up group membership..."
```

---

## Step 6 — Download and preprocess OSM data on the instance

The preprocessing runs on the instance to avoid transferring multi-GB files. The `osrm-contract` step takes 20–60 minutes.

```bash
ssh -i ~/.ssh/osrm-key.pem ubuntu@"$PUBLIC_IP" << 'REMOTE'
  set -euo pipefail
  mkdir -p ~/osrm-data
  cd ~/osrm-data

  OSRM_IMAGE="ghcr.io/project-osrm/osrm-backend:latest"
  PBF="venezuela-latest.osm.pbf"
  URL="https://download.geofabrik.de/south-america/venezuela-latest.osm.pbf"

  echo "[1/3] Downloading Venezuela OSM extract..."
  curl -L --progress-bar -o "$PBF" "$URL"

  echo "[2/3] Running osrm-extract..."
  docker run --rm \
    -v ~/osrm-data:/data \
    "$OSRM_IMAGE" \
    osrm-extract -p /opt/car.lua /data/$PBF

  echo "[3/3] Running osrm-contract (CH)..."
  echo "      This takes 20–60 minutes."
  START=$(date +%s)
  docker run --rm \
    -v ~/osrm-data:/data \
    "$OSRM_IMAGE" \
    osrm-contract /data/venezuela-latest.osrm
  END=$(date +%s)
  echo "      Completed in $(( (END - START) / 60 )) minutes."
REMOTE
```

---

## Step 7 — Start OSRM

```bash
ssh -i ~/.ssh/osrm-key.pem ubuntu@"$PUBLIC_IP" << 'REMOTE'
  docker run -d \
    --name osrm \
    --restart unless-stopped \
    -p 5000:5000 \
    -v ~/osrm-data:/data \
    ghcr.io/project-osrm/osrm-backend:latest \
    osrm-routed --algorithm ch /data/venezuela-latest.osrm

  echo "OSRM container started."
  docker ps
REMOTE
```

---

## Step 8 — Test the deployment

From your local machine:

```bash
# Nearest road to Caracas Plaza Bolivar
curl "http://${PUBLIC_IP}:5000/nearest/v1/driving/-66.9036,10.4806"

# Caracas → Valencia route
curl "http://${PUBLIC_IP}:5000/route/v1/driving/-66.9036,10.4806;-67.9936,10.1620?overview=false"
```

From Python (point the client to the EC2 IP):

```python
from client import OSRMClient

client = OSRMClient(f"http://{PUBLIC_IP}:5000")
distances, durations = client.distance_matrix([
    (10.4806, -66.9036),  # Caracas
    (10.1620, -67.9936),  # Valencia
    (10.2469, -67.5958),  # Maracay
])
print((distances / 1000).round(1))  # km
```

---

## Cost estimate

| Resource | Type | Unit cost | Monthly |
|---|---|---|---|
| EC2 | t3.medium on-demand | $0.0416/hr | ~$30 |
| EBS | gp3 20 GB | $0.08/GB-mo | ~$2 |
| Data transfer | Out to internet | $0.09/GB (first 10TB) | ~$1 |
| **Total** | | | **~$33/month** |

**Spot instance alternative**: replace `t3.medium` with `--instance-market-options '{"MarketType":"spot"}'` for ~60–70% savings (~$13/month). Spot instances can be interrupted with 2 minutes notice — acceptable if you have a fallback or can tolerate brief downtime.

---

## Cleanup

To avoid ongoing charges when not in use:

```bash
# Stop the instance (storage cost continues but compute stops)
aws ec2 stop-instances --region "$AWS_REGION" --instance-ids "$INSTANCE_ID"

# Or terminate completely (deletes storage too)
aws ec2 terminate-instances --region "$AWS_REGION" --instance-ids "$INSTANCE_ID"

# Delete security group (after instance is terminated)
aws ec2 delete-security-group --region "$AWS_REGION" --group-id "$SG_ID"
```

---

## Keeping data across restarts

The instance stores data on the root EBS volume (`/dev/sda1`), which persists across stop/start cycles. If you terminate the instance, the data is lost (because `DeleteOnTermination: true`).

To survive termination: create a separate EBS volume, attach it, and mount `/home/ubuntu/osrm-data` to it with a persistent mount in `/etc/fstab`. This adds ~$1.60/month but makes the preprocessed data permanent.

---

## Updating OSM data

```bash
ssh -i ~/.ssh/osrm-key.pem ubuntu@"$PUBLIC_IP" << 'REMOTE'
  cd ~/osrm-data

  # Stop OSRM
  docker stop osrm && docker rm osrm

  # Remove old data
  rm -f venezuela-latest.osm.pbf venezuela-latest.osrm*

  # Re-download and preprocess
  curl -L --progress-bar -o venezuela-latest.osm.pbf \
    https://download.geofabrik.de/south-america/venezuela-latest.osm.pbf

  OSRM_IMAGE="ghcr.io/project-osrm/osrm-backend:latest"
  docker run --rm -v ~/osrm-data:/data $OSRM_IMAGE osrm-extract -p /opt/car.lua /data/venezuela-latest.osm.pbf
  docker run --rm -v ~/osrm-data:/data $OSRM_IMAGE osrm-contract /data/venezuela-latest.osrm

  # Restart
  docker run -d --name osrm --restart unless-stopped \
    -p 5000:5000 -v ~/osrm-data:/data \
    $OSRM_IMAGE osrm-routed --algorithm ch /data/venezuela-latest.osrm
REMOTE
```
