#!/bin/bash

function fail() {
    echo $1
    exit 1
}

# Check if NCLOUD_CONTAINER_REGISTRY_URL is already set
if [ -z "$NCLOUD_CONTAINER_REGISTRY_URL" ]; then
    # If not set, source the .env file
    if [ -f .env ]; then
        echo "Sourcing .env file..."
        source .env
    else
        fail ".env file not found."
    fi
fi

export PROJECT_DIR=../..

export SERVICE_PREFIX=engine
export SERVICE_NAME=roouty-dynamic-engine
export TAG=latest

export GIT_VERSION=$(git describe --tags || git rev-parse --short HEAD)

echo "build image $SERVICE_NAME:$TAG-$GIT_VERSION"

# build image
docker build \
 -q --build-arg GIT_VERSION=$GIT_VERSION \
 -t $SERVICE_NAME:$TAG $PROJECT_DIR || fail "Build Failed"

echo "tag image $SERVICE_NAME:$TAG $NCLOUD_CONTAINER_REGISTRY_URL/$SERVICE_PREFIX/$SERVICE_NAME:$TAG"

# tag image
docker tag $SERVICE_NAME:$TAG $NCLOUD_CONTAINER_REGISTRY_URL/$SERVICE_PREFIX/$SERVICE_NAME:$TAG || fail "Tagging Failed"

echo "push image $NCLOUD_CONTAINER_REGISTRY_URL/$SERVICE_PREFIX/$SERVICE_NAME:$TAG"

# push image
docker push -q $NCLOUD_CONTAINER_REGISTRY_URL/$SERVICE_PREFIX/$SERVICE_NAME:$TAG || fail "Push Failed"