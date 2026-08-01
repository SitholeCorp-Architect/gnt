"""Dump the real OpenAPI schema for apps/docs' API Reference page.

Production deliberately disables the /openapi.json HTTP route (see main.py's
_docs_enabled) -- a real, intentional security decision, not a gap. But the
FastAPI `app` object's own `.openapi()` method is unrelated to that route: it
builds the schema from the registered routers regardless of whether anything
ever serves it over HTTP. Importing gnt.main and calling that method directly
gets the real spec without touching the disabled route or the app's own
runtime (lifespan/DB/Redis never start, since this only imports the module
and calls a plain method).

Settings() needs every required field to construct at all (see config.py),
same throwaway-value problem CI's `api` job already solved for pytest -- this
reuses those exact placeholder values rather than inventing a second set.
Nothing here calls encrypt/decrypt or opens a real connection, so none of it
needs to be a real secret or a reachable database.

Usage: uv run python scripts/generate_openapi.py
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://gnt_app:ci-placeholder@localhost:15432/gnt")
os.environ.setdefault("REDIS_URL", "redis://localhost:16379/0")
os.environ.setdefault("GROQ_API_KEY", "ci-placeholder")
os.environ.setdefault("CONTRIBUTOR_HASH_SECRET", "ci-placeholder")
os.environ.setdefault("SLACK_CLIENT_ID", "ci-placeholder")
os.environ.setdefault("SLACK_CLIENT_SECRET", "ci-placeholder")
os.environ.setdefault("SLACK_SIGNING_SECRET", "ci-placeholder")
os.environ.setdefault("SLACK_STATE_SECRET", "ci-placeholder")
os.environ.setdefault("SLACK_TOKEN_ENCRYPTION_KEY", "u6EciGcx1D4ly_Cvod7ajEkc4lPF57Xu9aOgODJ1Jjc=")
os.environ.setdefault("GITHUB_PAT_ENCRYPTION_KEY", "tJRAPluXs7Vgx7-CxIWUI6J03AP0DWVvaYmcz_c6qt0=")
os.environ.setdefault("ZENDESK_TOKEN_ENCRYPTION_KEY", "qPTJl1eogW1bR3gz9_AvTEcqPD14y1bXdq8z5X_UODI=")
os.environ.setdefault("INTERCOM_TOKEN_ENCRYPTION_KEY", "_lPYp-UWnt2btBxLMF_rDqPFcfO3zLOS_prT14v1eUw=")
os.environ.setdefault("NOTION_CLIENT_ID", "ci-placeholder")
os.environ.setdefault("NOTION_CLIENT_SECRET", "ci-placeholder")
os.environ.setdefault("NOTION_STATE_SECRET", "ci-placeholder")
os.environ.setdefault("NOTION_TOKEN_ENCRYPTION_KEY", "TAJsD8bP40HHRvLeyD7S5lE2KdRDm7Gs-0vxhb4fQmE=")
os.environ.setdefault("LINEAR_CLIENT_ID", "ci-placeholder")
os.environ.setdefault("LINEAR_STATE_SECRET", "ci-placeholder")
os.environ.setdefault("LINEAR_TOKEN_ENCRYPTION_KEY", "dj-_tSp0hjH0yitMF8BzBJsaemM3WULNsFKbokOwHBo=")
os.environ.setdefault("STORE_INTERNAL_API_SECRET", "ci-placeholder")
os.environ.setdefault("APPROVAL_SIGNING_SECRET", "ci-placeholder")

from pathlib import Path

import yaml

from gnt.main import app

OUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "apis" / "openapi.yaml"

schema = app.openapi()
# FastAPI's own schema has no `servers` entry unless the app is constructed
# with one (main.py deliberately isn't -- it's not needed for the app to
# serve requests, only for a docs site's "try it" panel to know which host
# to call). Added here, in the docs-facing dump, not upstream.
schema["servers"] = [{"url": "https://api.gntai.dev", "description": "Production"}]

OUT_PATH.write_text(yaml.dump(schema, sort_keys=False, allow_unicode=True))
print(f"wrote {len(schema.get('paths', {}))} paths to {OUT_PATH}")
