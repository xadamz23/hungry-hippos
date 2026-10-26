#!/usr/bin/env bash
# Build the amd64 image and push it to Docker Hub.
#   ./build-push.sh            build + push :<git sha> and :latest
#   ./build-push.sh --dry-run  build into the local docker image store only, then print its architecture
set -euo pipefail

IMAGE="${IMAGE:-xadamz23/hungry-hippos}"
PLATFORM="linux/amd64"
cd "$(dirname "$0")"

SHA="$(git rev-parse --short HEAD)"
if [[ -n "$(git status --porcelain)" ]]; then
  SHA="${SHA}-dirty"
  echo "warning: working tree has uncommitted changes; tagging ${SHA}" >&2
fi

# Cross-building amd64 from an arm64 machine needs a buildx builder with QEMU/binfmt support.
if ! docker buildx inspect hh-builder >/dev/null 2>&1; then
  docker buildx create --name hh-builder --driver docker-container --use >/dev/null
else
  docker buildx use hh-builder
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  docker buildx build --platform "$PLATFORM" -t "$IMAGE:$SHA" -t "$IMAGE:latest" --load .
  echo "built $IMAGE:$SHA for $(docker image inspect -f '{{.Os}}/{{.Architecture}}' "$IMAGE:$SHA")"
else
  docker buildx build --platform "$PLATFORM" -t "$IMAGE:$SHA" -t "$IMAGE:latest" --push .
  echo "pushed $IMAGE:$SHA and $IMAGE:latest ($PLATFORM)"
fi
