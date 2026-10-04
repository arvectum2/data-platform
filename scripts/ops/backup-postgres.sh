#!/bin/bash
set -euo pipefail

CONTAINER="${ARVECTUM_DATA_POSTGRES_CONTAINER:-arvectum-postgres}"
DATABASE="${ARVECTUM_DATA_POSTGRES_DB:-arvectum_data}"
OUTPUT_DIR="${ARVECTUM_DATA_BACKUP_DIR:-./backups}"

usage() {
  echo "Usage: $0 [--container NAME] [--database DB] [--output-dir DIR]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --container)
      CONTAINER="${2:-}"; shift 2 ;;
    --database)
      DATABASE="${2:-}"; shift 2 ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      usage; exit 2 ;;
  esac
done

if [ -z "$CONTAINER" ] || [ -z "$DATABASE" ] || [ -z "$OUTPUT_DIR" ]; then
  usage
  exit 2
fi

DOCKER="${DOCKER_BIN:-/opt/homebrew/bin/docker}"
if [ ! -x "$DOCKER" ]; then
  DOCKER="$(command -v docker || true)"
fi
if [ -z "$DOCKER" ]; then
  echo "docker CLI not found" >&2
  exit 1
fi

if ! "$DOCKER" inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "PostgreSQL container not found: $CONTAINER" >&2
  exit 1
fi

PGUSER="$("$DOCKER" inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_USER=//p')"
if [ -z "$PGUSER" ]; then
  echo "POSTGRES_USER is unavailable in container metadata" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
chmod 700 "$OUTPUT_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="data-platform-${DATABASE}-${STAMP}"
DUMP="$OUTPUT_DIR/${BASE}.dump"
TMP="${DUMP}.partial"
SHA_FILE="${DUMP}.sha256"
MANIFEST="${DUMP}.manifest.json"

cleanup() {
  rm -f "$TMP"
}
trap cleanup EXIT

"$DOCKER" exec "$CONTAINER" pg_dump   -U "$PGUSER"   -d "$DATABASE"   -Fc   --no-owner   --no-acl   > "$TMP"

if [ ! -s "$TMP" ]; then
  echo "backup is empty" >&2
  exit 1
fi

mv "$TMP" "$DUMP"
chmod 600 "$DUMP"

SHA="$(shasum -a 256 "$DUMP" | awk '{print $1}')"
printf '%s\n' "$SHA" > "$SHA_FILE"
chmod 600 "$SHA_FILE"

BYTES="$(stat -f '%z' "$DUMP")"
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

jq -n   --arg backup_file "$(basename "$DUMP")"   --arg database "$DATABASE"   --arg container "$CONTAINER"   --arg created_at "$CREATED_AT"   --arg sha256 "$SHA"   --argjson bytes "$BYTES"   '{
    backup_file: $backup_file,
    database: $database,
    container: $container,
    created_at: $created_at,
    sha256: $sha256,
    bytes: $bytes,
    format: "postgres-custom"
  }' > "$MANIFEST"
chmod 600 "$MANIFEST"

echo "BACKUP=$DUMP"
echo "SHA256=$SHA"
echo "BYTES=$BYTES"
echo "MANIFEST=$MANIFEST"
