#!/bin/bash

# CertMate Docker Build Script
# This script builds and optionally pushes the CertMate Docker image

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="certmate"
DOCKER_REGISTRY=""  # Set to your DockerHub username or registry URL
VERSION="latest"

# Parse command line arguments
PUSH=false
TAG_VERSION=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--push)
            PUSH=true
            shift
            ;;
        -r|--registry)
            DOCKER_REGISTRY="$2"
            shift 2
            ;;
        -v|--version)
            TAG_VERSION="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  -p, --push              Push image to registry after building"
            echo "  -r, --registry USER     DockerHub username or registry URL"
            echo "  -v, --version VERSION   Tag version (default: latest)"
            echo "  -h, --help              Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option $1"
            exit 1
            ;;
    esac
done

# Set image tag
if [ -n "$TAG_VERSION" ]; then
    VERSION="$TAG_VERSION"
fi

# Build full image name
if [ -n "$DOCKER_REGISTRY" ]; then
    FULL_IMAGE_NAME="${DOCKER_REGISTRY}/${IMAGE_NAME}:${VERSION}"
    LATEST_IMAGE_NAME="${DOCKER_REGISTRY}/${IMAGE_NAME}:latest"
else
    FULL_IMAGE_NAME="${IMAGE_NAME}:${VERSION}"
    LATEST_IMAGE_NAME="${IMAGE_NAME}:latest"
fi

echo -e "${YELLOW}Building CertMate Docker Image${NC}"
echo "Image name: $FULL_IMAGE_NAME"

# Verify .dockerignore exists
if [ ! -f ".dockerignore" ]; then
    echo -e "${RED}Error: .dockerignore file not found!${NC}"
    echo "This file is required to exclude sensitive files from the Docker image."
    exit 1
fi

# Verify .env is excluded
if grep -q "^\.env$" .dockerignore; then
    echo -e "${GREEN}✓ .env files are properly excluded${NC}"
else
    echo -e "${RED}Warning: .env files may not be excluded from Docker image${NC}"
fi

# Check if .env exists and warn about it
if [ -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env file exists in build context${NC}"
    echo "Ensure it's listed in .dockerignore to prevent inclusion in image"
fi

# Build the Docker image
echo -e "${YELLOW}Building Docker image...${NC}"
docker build -t "$FULL_IMAGE_NAME" .

# Tag as latest if not already latest
if [ "$VERSION" != "latest" ] && [ -n "$DOCKER_REGISTRY" ]; then
    docker tag "$FULL_IMAGE_NAME" "$LATEST_IMAGE_NAME"
    echo -e "${GREEN}✓ Tagged as latest: $LATEST_IMAGE_NAME${NC}"
fi

echo -e "${GREEN}✓ Successfully built: $FULL_IMAGE_NAME${NC}"

# Verify no secrets in image
echo -e "${YELLOW}Verifying no secrets in image...${NC}"
SECRET_CHECK=$(docker run --rm "$FULL_IMAGE_NAME" find / -name "*.env" 2>/dev/null || true)
if [ -z "$SECRET_CHECK" ]; then
    echo -e "${GREEN}✓ No .env files found in image${NC}"
else
    echo -e "${RED}Warning: Found .env files in image:${NC}"
    echo "$SECRET_CHECK"
fi

# Check image size
IMAGE_SIZE=$(docker images "$FULL_IMAGE_NAME" --format "table {{.Size}}" | tail -n +2)
echo "Image size: $IMAGE_SIZE"

# Push if requested
if [ "$PUSH" = true ]; then
    if [ -z "$DOCKER_REGISTRY" ]; then
        echo -e "${RED}Error: Cannot push without registry (-r option)${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}Pushing to registry...${NC}"
    
    # Check if logged in to Docker Hub
    if ! docker info | grep -q "Username:"; then
        echo -e "${YELLOW}Not logged in to Docker registry. Please login:${NC}"
        docker login
    fi
    
    docker push "$FULL_IMAGE_NAME"
    echo -e "${GREEN}✓ Pushed: $FULL_IMAGE_NAME${NC}"
    
    if [ "$VERSION" != "latest" ]; then
        docker push "$LATEST_IMAGE_NAME"
        echo -e "${GREEN}✓ Pushed: $LATEST_IMAGE_NAME${NC}"
    fi
fi

echo -e "${GREEN}Build completed successfully!${NC}"
echo ""
echo "To run the container:"
echo "docker run -d --name certmate --env-file .env -p 8000:8000 -v certmate_data:/app/data $FULL_IMAGE_NAME"
echo ""
echo "To test locally:"
echo "docker run --rm --env-file .env -p 8000:8000 $FULL_IMAGE_NAME"
