#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

CUR=$(tr -d '[:space:]' < VERSION)
if [[ -z "$CUR" ]]; then
  echo "VERSION empty" >&2
  exit 1
fi

IFS=. read -r MA MI PA <<< "${CUR}"
MA=${MA:-0}
MI=${MI:-0}
PA=${PA:-0}
case "${BUMP:-patch}" in
  major) MA=$((MA + 1)); MI=0; PA=0 ;;
  minor) MI=$((MI + 1)); PA=0 ;;
  patch|*) PA=$((PA + 1)) ;;
esac
VER="${MA}.${MI}.${PA}"
printf '%s\n' "$VER" > VERSION

if [[ -f docker-compose.synology.yml ]]; then
  sed -i.bak -E \
    -e "s|^([[:space:]]*image:[[:space:]]*mt-pt:)[^[:space:]]+|\\1${VER}|" \
    -e "s|^([[:space:]]*-[[:space:]]*APP_VERSION=).*|\\1${VER}|" \
    docker-compose.synology.yml
  rm -f docker-compose.synology.yml.bak
fi

if [[ -f README.md ]]; then
  sed -i.bak -E \
    -e "s|(badge/version-)[0-9.]+(-blue)|\\1${VER}\\2|" \
    -e "s|mt-pt-[0-9.]+-amd64\\.tar\\.gz|mt-pt-${VER}-amd64.tar.gz|g" \
    README.md
  rm -f README.md.bak
fi

IMG="mt-pt:${VER}"
OUT="dist/mt-pt-${VER}-amd64.tar.gz"

mkdir -p dist
echo "build ${IMG} (was ${CUR})"
docker buildx build \
  --platform linux/amd64 \
  --build-arg APP_VERSION="${VER}" \
  -t "${IMG}" \
  -t mt-pt:latest \
  --load \
  .

echo "save ${OUT}"
docker save "${IMG}" | gzip -1 > "${OUT}"
gzip -t "${OUT}"
ln -sfn "mt-pt-${VER}-amd64.tar.gz" dist/mt-pt-latest-amd64.tar.gz
ls -lh "${OUT}" dist/mt-pt-latest-amd64.tar.gz
echo "OK version=${VER}"
