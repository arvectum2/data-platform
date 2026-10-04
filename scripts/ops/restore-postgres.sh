#!/bin/bash
set -euo pipefail

CONTAINER="${ARVECTUM_DATA_POSTGRES_CONTAINER:-arvectum-postgres}"
BACKUP=""
TARGET_DB=""
REPLACE=0
ALLOW_PRODUCTION=0

usage() {
  echo "Usage: $0 --backup FILE --target-db DB [--container NAME] [--replace] [--allow-production-target]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --container)
      CONTAINER="${2:-}"; shift 2 ;;
    --backup)
      BACKUP="${2:-}"; shift 2 ;;
    --target-db)
      TARGET_DB="${2:-}"; shift 2 ;;
    --replace)
      REPLACE=1; shift ;;
    --allow-production-target)
      ALLOW_PRODUCTION=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      usage; exit 2 ;;
  esac
done

if [ -z "$BACKUP" ] || [ -z "$TARGET_DB" ]; then
  usage
  exit 2
fi
if ! [[ "$TARGET_DB" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "target database name contains unsupported characters" >&2
  exit 2
fi
if [ ! -f "$BACKUP" ]; then
  echo "backup file not found: $BACKUP" >&2
  exit 1
fi
if [ "$TARGET_DB" = "arvectum_data" ] && [ "$ALLOW_PRODUCTION" -ne 1 ]; then
  echo "refusing to restore over production database arvectum_data without --allow-production-target" >&2
  exit 1
fi

DOCKER="${DOCKER_BIN:-/opt/homebrew/bin/docker}"
if [ ! -x "$DOCKER" ]; then
  DOCKER="$(command -v docker || true)"
fi
if [ -z "$DOCKER" ]; then
  echo "docker CLI not found" >&2
  exit 1
fi

PGUSER="$("$DOCKER" inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_USER=//p')"
PGROOTDB="$("$DOCKER" inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_DB=//p')"
if [ -z "$PGUSER" ] || [ -z "$PGROOTDB" ]; then
  echo "PostgreSQL container identity is unavailable" >&2
  exit 1
fi

SHA_FILE="${BACKUP}.sha256"
MANIFEST="${BACKUP}.manifest.json"
if [ ! -f "$SHA_FILE" ] || [ ! -f "$MANIFEST" ]; then
  echo "backup checksum or manifest is missing" >&2
  exit 1
fi

EXPECTED_SHA="$(tr -d '[:space:]' < "$SHA_FILE")"
ACTUAL_SHA="$(shasum -a 256 "$BACKUP" | awk '{print $1}')"
if [ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]; then
  echo "backup checksum mismatch" >&2
  exit 1
fi

SOURCE_DB="$(jq -r '.database // empty' "$MANIFEST")"
if [ "$TARGET_DB" = "$SOURCE_DB" ] && [ "$ALLOW_PRODUCTION" -ne 1 ]; then
  echo "refusing to restore over source database without --allow-production-target" >&2
  exit 1
fi

EXISTS="$("$DOCKER" exec "$CONTAINER" psql -U "$PGUSER" -d "$PGROOTDB" -Atqc "SELECT 1 FROM pg_database WHERE datname = '${TARGET_DB//\'/\'\'}'" || true)"
if [ "$EXISTS" = "1" ]; then
  if [ "$REPLACE" -ne 1 ]; then
    echo "target database already exists; use --replace: $TARGET_DB" >&2
    exit 1
  fi
  "$DOCKER" exec "$CONTAINER" psql -U "$PGUSER" -d "$PGROOTDB" -v ON_ERROR_STOP=1 -c     "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$TARGET_DB' AND pid <> pg_backend_pid();" >/dev/null
  "$DOCKER" exec "$CONTAINER" dropdb -U "$PGUSER" "$TARGET_DB"
fi

"$DOCKER" exec "$CONTAINER" createdb -U "$PGUSER" -O "$PGUSER" "$TARGET_DB"
if ! cat "$BACKUP" | "$DOCKER" exec -i "$CONTAINER" pg_restore   -U "$PGUSER"   -d "$TARGET_DB"   --no-owner   --no-acl   --exit-on-error; then
  "$DOCKER" exec "$CONTAINER" dropdb -U "$PGUSER" "$TARGET_DB" >/dev/null 2>&1 || true
  echo "restore failed; target database removed" >&2
  exit 1
fi

COUNTS="$("$DOCKER" exec "$CONTAINER" psql -U "$PGUSER" -d "$TARGET_DB" -AtF ',' -c   "SELECT
     (SELECT count(*) FROM dp_collections),
     (SELECT count(*) FROM dp_resources),
     (SELECT count(*) FROM dp_documents),
     (SELECT count(*) FROM dp_chunks),
     (SELECT count(*) FROM dp_chunk_embeddings),
     (SELECT count(*) FROM dp_pipeline_runs);")"

echo "RESTORED_DB=$TARGET_DB"
echo "SHA256=$ACTUAL_SHA"
echo "COUNTS=$COUNTS"
