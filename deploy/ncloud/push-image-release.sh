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
export TAG=release

export GIT_VERSION=$(git describe --tags || git rev-parse --short HEAD)

for T in $TAG $GIT_VERSION
do
    echo "build image $SERVICE_NAME:$T-$GIT_VERSION"

    # build image
    docker build \
     -q --build-arg GIT_VERSION=$GIT_VERSION \
     -t $SERVICE_NAME:$T $PROJECT_DIR || fail "Build Failed"

    echo "tag image $SERVICE_NAME:$T $NCLOUD_CONTAINER_REGISTRY_URL/$SERVICE_PREFIX/$SERVICE_NAME:$T"

    # tag image
    docker tag $SERVICE_NAME:$T $NCLOUD_CONTAINER_REGISTRY_URL/$SERVICE_PREFIX/$SERVICE_NAME:$T || fail "Tagging Failed"

    echo "push image $NCLOUD_CONTAINER_REGISTRY_URL/$SERVICE_PREFIX/$SERVICE_NAME:$T"

    # push image
    docker push -q $NCLOUD_CONTAINER_REGISTRY_URL/$SERVICE_PREFIX/$SERVICE_NAME:$T || fail "Push Failed"
done
