#!/bin/bash

# AWS SSO Credentials Updater for Docker Compose
# This script exports current AWS SSO credentials and updates Docker environment

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}[INFO] Updating AWS SSO credentials for Docker...${NC}"

# Get the AWS profile from environment or use default
AWS_PROFILE_NAME="${AWS_PROFILE:-default}"

echo -e "${YELLOW}[INFO] Using AWS Profile: ${AWS_PROFILE_NAME}${NC}"

# Check if AWS CLI is available
if ! command -v aws &> /dev/null; then
    echo -e "${RED}[ERROR] AWS CLI is not installed${NC}"
    exit 1
fi

# Check if the profile exists and has valid credentials
if ! aws sts get-caller-identity --profile "$AWS_PROFILE_NAME" &> /dev/null; then
    echo -e "${RED}[ERROR] AWS profile '$AWS_PROFILE_NAME' not found or credentials expired${NC}"
    echo -e "${YELLOW}[INFO] Please run: aws sso login --profile $AWS_PROFILE_NAME${NC}"
    exit 1
fi

echo -e "${GREEN}[OK] AWS Profile is valid${NC}"

# Export credentials
echo -e "${YELLOW}[INFO] Exporting current AWS SSO credentials...${NC}"

# Get credentials using env format
CREDENTIALS=$(aws configure export-credentials --profile "$AWS_PROFILE_NAME" --format env)

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Failed to export credentials${NC}"
    exit 1
fi

# Parse the env output
ACCESS_KEY=$(echo "$CREDENTIALS" | grep "^export AWS_ACCESS_KEY_ID=" | cut -d'=' -f2)
SECRET_KEY=$(echo "$CREDENTIALS" | grep "^export AWS_SECRET_ACCESS_KEY=" | cut -d'=' -f2)
SESSION_TOKEN=$(echo "$CREDENTIALS" | grep "^export AWS_SESSION_TOKEN=" | cut -d'=' -f2)
EXPIRATION=$(echo "$CREDENTIALS" | grep "^export AWS_CREDENTIAL_EXPIRATION=" | cut -d'=' -f2)

# Create a temporary environment file for Docker
cat > .env.aws-sso << EOF
# AWS SSO Credentials (Auto-generated on $(date))
# Profile: $AWS_PROFILE_NAME
# Expires: $EXPIRATION

AWS_ACCESS_KEY_ID=$ACCESS_KEY
AWS_SECRET_ACCESS_KEY=$SECRET_KEY
AWS_SESSION_TOKEN=$SESSION_TOKEN
AWS_PROFILE=$AWS_PROFILE_NAME
AWS_REGION=${AWS_REGION:-us-east-1}
EOF

echo -e "${GREEN}[OK] AWS credentials exported to .env.aws-sso${NC}"
echo -e "${YELLOW}[INFO] Credentials expire at: $EXPIRATION${NC}"
echo -e "${GREEN}[INFO] Restart local services after sourcing .env.aws-sso${NC}"
