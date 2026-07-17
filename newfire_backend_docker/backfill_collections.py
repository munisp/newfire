#!/usr/bin/env python3
"""Backfill qdrant_collection for legacy companies, create Qdrant collections,
and seed identity chunks from onboarding data so grounding fires.

Run on Minisforum host (has DB on 5433, Ollama via Tailscale, Qdrant on DGX).

Safe to re-run. Idempotent per company: skips already-seeded collections.

Usage:
  python3 backfill_collections.py             # all NULL-collection companies
  python3 backfill_collections.py --force     # re-seed even if collection exists

Environment variables required:
  DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
  QDRANT_URL, QDRANT_API_KEY
  OLLAMA_URL (optional)
  EMBED_MODEL (optional)
"""
import os
import sys
import json
import urllib.request
import urllib.error

# All secrets must be provided via environment variables - no defaults
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = int(os.environ.get("DB_PORT", "5433"))
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME")

QDRANT_URL = os.environ.get("QDRANT_URL")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://100.88.112.5:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

if not all([DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, QDRANT_URL, QDRANT_API_KEY]):
    print("ERROR: Missing required environment variables:")
    if not DB_HOST: print("  - DB_HOST")
    if not DB_USER: print("  - DB_USER")
    if not DB_PASSWORD: print("  - DB_PASSWORD")
    if not DB_NAME: print("  - DB_NAME")
    if not QDRANT_URL: print("  - QDRANT_URL")
    if not QDRANT_API_KEY: print("  - QDRANT_API_KEY")
    sys.exit(1)

VECTOR_SIZE = 768
FORCE = "--force" in sys.argv


def pg_connect():
    import psycopg2
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, dbname=DB_NAME
    )


def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def qdrant(method, path, body=None):
    return http(method, f"{QDRANT_URL}{path}", body=body,
                headers={"api-key": QDRANT_API_KEY})


def embed(text):
    s, d = http("POST", f"{OLLAMA_URL}/api/embeddings",
                body={"model": EMBED_MODEL, "prompt": text})
    if s != 200:
        raise RuntimeError(f"embed {s}: {d}")
    return d["embedding"]


def ensure_collection(name):
    s, d = qdrant("GET", f"/collections/{name}")
    if s == 200:
        return False
    if s == 404:
        s2, d2 = qdrant("PUT", f"/collections/{name}",
                        {"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}})
        if s2 not in (200, 202):
            raise RuntimeError(f"create {name}: {s2} {d2}")
        return True
    raise RuntimeError(f"probe {name}: {s} {d}")


def build_identity_chunks(company, agents):
    """Return a list of (text, payload) tuples grounded in onboarding data only."""
    cname = company["name"]
    cdesc = company["description"] or ""
    chunks = []
    if cdesc:
        chunks.append((
            f"{cname} is {cdesc}".strip(),
            {"source_file": "onboarding", "kind": "company_overview",
             "needs_review": True},
        ))
    chunks.append((
        f"The company {cname} has {len(agents)} AI agent(s) staffed "
        "to handle client work.",
        {"source_file": "onboarding", "kind": "team_size",
         "needs_review": True},
    ))
    for a in agents:
        role = a.get("role") or ""
        desc = a.get("description") or ""
        text = f"Agent '{a['name']}' works at {cname}. " \
               f"Role: {role}. Scope: {desc}".strip()
        chunks.append((
            text,
            {"source_file": "onboarding", "kind": "agent_identity",
             "agent_id": a["agent_id"], "needs_review": True},
        ))
    return chunks


def main():
    conn = pg_connect()
    cur = conn.cursor()

    cur.execute("""
        UPDATE companies SET qdrant_collection = 'company_' || id
        WHERE qdrant_collection IS NULL
    """)
    backfilled = cur.rowcount
    conn.commit()
    print(f"[db] backfilled {backfilled} rows")

    cur.execute("SELECT id, name, description, qdrant_collection "
                "FROM companies ORDER BY id")
    companies = [
        {"id": r[0], "name": r[1], "description": r[2],
         "collection": r[3]}
        for r in cur.fetchall()
    ]

    for comp in companies:
        coll = comp["collection"]
        cur.execute(
            "SELECT agent_id, name, role, description FROM agents "
            "WHERE company_id = %s ORDER BY id",
            (comp["id"],),
        )
        agents = [
            {"agent_id": r[0], "name": r[1], "role": r[2],
             "description": r[3]}
            for r in cur.fetchall()
        ]
        print(f"\n== company {comp['id']}: {comp['name']} "
              f"({len(agents)} agents) -> {coll} ==")
        created = ensure_collection(coll)
        print(f"  collection {'created' if created else 'existed'}")

        if not FORCE:
            s, d = qdrant("GET", f"/collections/{coll}")
            if isinstance(d, dict) and \
               d.get("result", {}).get("points_count", 0) > 0:
                print(f"  skip: already has {d['result']['points_count']} "
                      "points (use --force to re-seed)")
                continue

        chunks = build_identity_chunks(comp, agents)
        points = []
        for i, (text, payload) in enumerate(chunks, start=1):
            vec = embed(text)
            payload["text"] = text
            payload["chunk_index"] = i
            points.append({"id": i, "vector": vec, "payload": payload})

        s, d = qdrant("PUT",
                      f"/collections/{coll}/points?wait=true",
                      {"points": points})
        if s not in (200, 202):
            print(f"  FAIL upsert: {s} {d}")
            continue
        print(f"  seeded {len(points)} identity chunks")

    conn.close()
    print("\nDONE")


if __name__ == "__main__":
    main()