#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <tag>"
    exit 1
fi

tag=$1
image="docker.io/xadamz23/hungry-hippos:$tag"

cd "$(dirname "$0")/.."

if [[ -n "$(git status --porcelain)" ]]; then
    echo "[ERROR] working tree has uncommitted changes; commit them so the image matches the tag"
    exit 1
fi

# tag release
echo "[INFO] tagging release ($tag)"
git tag -a "$tag" -m "Release version $tag"
git push origin "$tag"

# build & push docker image
echo "[INFO] building docker image"
docker buildx build --platform linux/amd64 -t "$image" --load .

echo "[INFO] pushing docker image"
docker push "$image"

# ssh to host and update app
echo "[INFO] ssh'ing to docker-public vm"
ssh -o BatchMode=yes root@docker-public.stizzle.org "/home/dockerapps/hungry-hippos/update-app.sh $tag"
