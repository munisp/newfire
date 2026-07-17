#!/usr/bin/env bash
# Seed real grounding content into a company's Qdrant collection.
# Reads a text file, chunks it, embeds with nomic-embed-text, upserts to Qdrant.
#
# Usage:
#   ./seed_company_content.sh <company_id> <source_file> [--chunk-size N] [--start-id N]
#
# Examples:
#   ./seed_company_content.sh 7 /tmp/sherifah_marketing_facts.md
#   ./seed_company_content.sh 7 /tmp/pricing.md --chunk-size 600 --start-id 100
#
# Env requires: QDRANT_URL, QDRANT_API_KEY, OLLAMA_URL (defaults aim at DGX Tailscale).

set -euo pipefail

: "${QDRANT_URL:=http://100.88.112.5:6333}"
: "${QDRANT_API_KEY:?QDRANT_API_KEY required}"
: "${OLLAMA_URL:=http://100.88.112.5:11434}"
: "${EMBED_MODEL:=nomic-embed-text}"

COMPANY_ID="${1:?company_id required (positional 1)}"
SOURCE_FILE="${2:?source file required (positional 2)}"
shift 2

# Validate company_id is a positive integer
if ! [[ "$COMPANY_ID" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: company_id must be a positive integer, got: $COMPANY_ID" >&2
    exit 1
fi

CHUNK_SIZE=800
START_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --chunk-size) CHUNK_SIZE="$2"; shift 2 ;;
    --start-id)   START_ID="$2";   shift 2 ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
done

[[ -r "$SOURCE_FILE" ]] || { echo "cannot read $SOURCE_FILE" >&2; exit 2; }

# SECURITY FIX: Use quoted parameter to prevent SQL injection
# Use -v to pass the variable safely instead of string interpolation
COLL=$(docker exec newfire-db psql -U newfire -d newfire -tAc \
    "SELECT qdrant_collection FROM companies WHERE id = :company_id" \
    --variable="company_id=$COMPANY_ID" < /dev/null)
[[ -n "$COLL" ]] || { echo "company $COMPANY_ID has no qdrant_collection; " \
    "run backfill_collections.sh first" >&2; exit 3; }

echo "[seed] company $COMPANY_ID -> collection $COLL"
echo "[seed] source: $SOURCE_FILE"
echo "[seed] chunk size: $CHUNK_SIZE"

# Ensure Qdrant collection exists (create with correct schema if missing)
PROBE=$(curl -sS -o /dev/null -w '%{http_code}' "$QDRANT_URL/collections/$COLL" \
    -H "api-key: $QDRANT_API_KEY")
if [[ "$PROBE" == "404" ]]; then
  echo "[seed] collection $COLL not found, creating (768-dim cosine)"
  curl -sS -X PUT "$QDRANT_URL/collections/$COLL" -H "api-key: $QDRANT_API_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"vectors":{"size":768,"distance":"Cosine"}}' > /dev/null
fi

# Derive starting id if not provided
if [[ -z "$START_ID" ]]; then
  START_ID=$(curl -sS "$QDRANT_URL/collections/$COLL" \
    -H "api-key: $QDRANT_API_KEY" | \
    python3 -c 'import sys,json; d=json.load(sys.stdin); ' \
    'print(int(d.get("result",{}).get("points_count",0))+100)')
fi
echo "[seed] starting id: $START_ID"

# Chunk the file
CHUNKS=$(python3 <<PY
import sys, re
content = open("$SOURCE_FILE", encoding="utf-8").read()
chunks = []
cur = []
cur_len = 0
max_len = $CHUNK_SIZE
# Prefer splitting on blank lines (paragraphs), fall back to single newlines
paragraphs = [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]
for p in paragraphs:
    if cur_len + len(p) + 2 <= max_len:
        cur.append(p); cur_len += len(p) + 2
    else:
        if cur: chunks.append('\n\n'.join(cur))
        cur = [p]; cur_len = len(p)
if cur: chunks.append('\n\n'.join(cur))
for c in chunks:
    print("---CHUNK---")
    print(c)
PY
)

# Iterate chunks, embed, upsert one at a time
idx=$START_ID
count=0
while IFS= read -r line; do
  if [[ "$line" == "---CHUNK---" ]]; then
    if [[ -n "" ]]; then
      count=$((count+1))
      vec=$(curl -sS "$OLLAMA_URL/api/embeddings" \
        -H 'Content-Type: application/json' \
        -d "$(python3 -c \
          'import json,sys;print(json.dumps({"model":sys.argv[1],"prompt":sys.argv[2]}))' \
          "$EMBED_MODEL" "$chunk_buf")" | \
        python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin)["embedding"]))')
      payload=$(python3 -c \
        'import json,sys;print(json.dumps({"text":sys.argv[1],"source_file":sys.argv[2],'"'"'kind'"'"': '"'"'owner_supplied'"'"',"'"'chunk_index'"'"':int(sys.argv[3]),"'"'needs_review'"'"':False}))' \
        "$chunk_buf" "$(basename "$SOURCE_FILE")" "$count")
      body=$(python3 -c \
        'import json,sys;vec=json.loads(sys.argv[1]);payload=json.loads(sys.argv[2]);idx=int(sys.argv[3]);'"'"'print(json.dumps({"points":[{"id":idx,"vector":vec,"payload":payload}]}))'"'"' \
        "$vec" "$payload" "$idx")
      curl -sS -X PUT "$QDRANT_URL/collections/$COLL/points?wait=true" \
        -H "api-key: $QDRANT_API_KEY" \
        -H 'Content-Type: application/json' \
        -d "$body" > /dev/null
      echo "  chunk $count (id=$idx, ${#chunk_buf} chars)"
      idx=$((idx+1))
    fi
    chunk_buf=""
  else
    if [[ -n "" ]]; then chunk_buf+=$'\n'; fi
    chunk_buf+="$line"
  fi
done <<< "$CHUNKS"
# flush last
if [[ -n "" ]]; then
  count=$((count+1))
  vec=$(curl -sS "$OLLAMA_URL/api/embeddings" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c \
      'import json,sys;print(json.dumps({"model":sys.argv[1],"prompt":sys.argv[2]}))' \
      "$EMBED_MODEL" "$chunk_buf")" | \
    python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin)["embedding"]))')
  payload=$(python3 -c \
    'import json,sys;print(json.dumps({"text":sys.argv[1],"source_file":sys.argv[2],'"'"'kind'"'"': '"'"'owner_supplied'"'"',"'"'chunk_index'"'"':int(sys.argv[3]),"'"'needs_review'"'"':False}))' \
    "$chunk_buf" "$(basename "$SOURCE_FILE")" "$count")
  body=$(python3 -c \
    'import json,sys;vec=json.loads(sys.argv[1]);payload=json.loads(sys.argv[2]);idx=int(sys.argv[3]);'"'"'print(json.dumps({"points":[{"id":idx,"vector":vec,"payload":payload}]}))'"'"' \
    "$vec" "$payload" "$idx")
  curl -sS -X PUT "$QDRANT_URL/collections/$COLL/points?wait=true" \
    -H "api-key: $QDRANT_API_KEY" \
    -H 'Content-Type: application/json' \
    -d "$body" > /dev/null
  echo "  chunk $count (id=$idx, ${#chunk_buf} chars)"
fi

echo ""
echo "[seed] DONE: seeded $count chunks"