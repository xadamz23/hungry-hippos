#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <tag>"
    exit 1
fi

tag=$1
image="docker.io/xadamz23/hungry-hippos:$tag"

cd "${APP_DIR:-/home/dockerapps/hungry-hippos}"

running=$(docker ps --filter 'name=^hungry-hippos$' --format '{{.Image}}')
# docker ps drops the docker.io/ prefix
if [[ "docker.io/${running#docker.io/}" == "$image" ]]; then
    echo "[INFO] app is already running the latest version ($tag)"
    exit 0
fi

if ! docker network inspect cf-tunnel >/dev/null 2>&1; then
    echo "[ERROR] docker network cf-tunnel does not exist; run: docker network create cf-tunnel"
    exit 1
fi

if [[ ! -f .env ]]; then
    echo "[ERROR] $(pwd)/.env is missing; it needs at least POSTGRES_PASSWORD"
    exit 1
fi

echo "[INFO] updating tag in compose file to $tag"

cat <<EOF > docker-compose.yaml
# Written by update-app.sh, which deploy-hungry-hippos-from-arm64.sh runs with the
# release tag. Don't edit by hand: the next deploy overwrites it.
# Secrets and settings come from .env next to this file.

name: hungry-hippos

services:
  hungry-hippos:
    image: $image
    platform: linux/amd64
    container_name: hungry-hippos
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://\${POSTGRES_USER:-hh}:\${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}@db:5432/\${POSTGRES_DB:-hungry_hippos}
    # No published ports: cloudflared reaches it at http://hungry-hippos:8000 over cf-tunnel.
    networks:
      - default
      - cf-tunnel
    depends_on:
      db:
        condition: service_healthy
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  db:
    image: postgres:17
    container_name: hungry-hippos-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: \${POSTGRES_USER:-hh}
      POSTGRES_PASSWORD: \${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
      POSTGRES_DB: \${POSTGRES_DB:-hungry_hippos}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \$\${POSTGRES_USER} -d \$\${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  pgdata:

networks:
  cf-tunnel:
    external: true
EOF

# Only the app container changes between releases, so db keeps running.
echo "[INFO] starting the new version"
docker compose up -d --remove-orphans
