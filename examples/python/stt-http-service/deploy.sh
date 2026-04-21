#!/usr/bin/env bash
# Build the Moonshine STT Docker image and optionally start it with docker compose.
# Before each start: docker compose down (removes this project's containers + network).
# Usage: ./deploy.sh [--build-only] [--no-cache] [-t TAG] [-p PORT] [--push]
# Env: IMAGE_NAME (default moonshine-stt), IMAGE_TAG (default latest), STT_HOST_PORT

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IMAGE_NAME="${IMAGE_NAME:-moonshine-stt}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
BUILD_ONLY=false
NO_CACHE=()
DO_PUSH=false

# True if something accepts TCP connections on 127.0.0.1:port (same check Docker bind uses for published ports).
tcp_port_in_use() {
  local port="$1"
  local bash_check=(bash -c "true >/dev/tcp/127.0.0.1/${port}")
  if command -v timeout >/dev/null 2>&1; then
    timeout 1 "${bash_check[@]}" 2>/dev/null
  else
    "${bash_check[@]}" 2>/dev/null
  fi
}

# If STT_HOST_PORT is unset, prefer 8080 then common alternates. If set, require it free.
pick_stt_host_port() {
  if [[ -n "${STT_HOST_PORT:-}" ]]; then
    if tcp_port_in_use "${STT_HOST_PORT}"; then
      echo "STT_HOST_PORT=${STT_HOST_PORT} is already in use on this host." >&2
      echo "Free that port or run: STT_HOST_PORT=<free-port> $0 ..." >&2
      exit 1
    fi
    export STT_HOST_PORT
    return
  fi
  local p
  for p in 8080 18080 18081 8081 9080 9888; do
    if ! tcp_port_in_use "$p"; then
      export STT_HOST_PORT="$p"
      if [[ "$p" != "8080" ]]; then
        echo "==> Host port 8080 is busy; using STT_HOST_PORT=${STT_HOST_PORT}" >&2
      fi
      return
    fi
  done
  echo "No free port found in fallback list. Set STT_HOST_PORT explicitly." >&2
  exit 1
}

usage() {
  cat <<'EOF'
Build the Moonshine STT Docker image and optionally start docker compose.

Options:
  -h, --help        Show help
  -b, --build-only  Only run docker build; do not start compose
  -t, --tag TAG     Image tag (default: latest). Image: $IMAGE_NAME:TAG
  -p, --port PORT   Host port published to the container (default: 8080, or next free if busy)
  --no-cache        docker build --no-cache
  --push            docker push $IMAGE_NAME:$TAG after build

Environment:
  IMAGE_NAME      Image repository name (default: moonshine-stt)
  IMAGE_TAG       Overridden by -t (default: latest)
  STT_HOST_PORT   Host port for compose (same as -p; must be free if set)

Each run runs  docker compose down  first (containers + default network for this
project). Named volumes (model cache) are kept unless you remove them manually.

Examples:
  ./deploy.sh
  ./deploy.sh -p 18080
  IMAGE_NAME=registry.example.com/moonshine-stt ./deploy.sh -t v1 --push
  ./deploy.sh -b --no-cache
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    -b | --build-only)
      BUILD_ONLY=true
      shift
      ;;
    -t | --tag)
      IMAGE_TAG="${2:?tag required}"
      shift 2
      ;;
    -p | --port)
      STT_HOST_PORT="${2:?port required}"
      shift 2
      ;;
    --no-cache)
      NO_CACHE=(--no-cache)
      shift
      ;;
    --push)
      DO_PUSH=true
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

echo "==> docker build ${FULL_IMAGE}"
docker build "${NO_CACHE[@]}" -t "${FULL_IMAGE}" .

if [[ "${DO_PUSH}" == true ]]; then
  echo "==> docker push ${FULL_IMAGE}"
  docker push "${FULL_IMAGE}"
fi

if [[ "${BUILD_ONLY}" == true ]]; then
  echo "==> Done (build only)."
  exit 0
fi

export STT_IMAGE="${FULL_IMAGE}"

echo "==> docker compose down (remove existing Moonshine STT containers and project network)"
docker compose down --remove-orphans --timeout 10

pick_stt_host_port

echo "==> docker compose up -d --build (host :${STT_HOST_PORT} -> container :8080)"
if ! docker compose up -d --build; then
  echo "" >&2
  echo "Tip: set an explicit port: ./deploy.sh -p 18080" >&2
  exit 1
fi

echo "==> Service STT_IMAGE=${STT_IMAGE}  STT_HOST_PORT=${STT_HOST_PORT}"
echo "    Health: curl -s http://127.0.0.1:${STT_HOST_PORT}/health"
