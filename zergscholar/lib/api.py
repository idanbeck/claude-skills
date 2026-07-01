"""HTTP client for the zergscholar REST surface.

Stdlib-only (urllib) so the skill works in any Python 3 environment
without an install step. The API only needs JSON GET / POST / PATCH /
DELETE plus one base64-PDF upload, so the boilerplate is bounded.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib import request, error
from urllib.parse import quote
from urllib.parse import urlencode


class ApiError(Exception):
    def __init__(self, status: int, message: str, body: Any = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.body = body


@dataclass
class Account:
    base_url: str
    token: str
    default_organization_id: str | None = None


class ZergScholarApi:
    def __init__(self, account: Account):
        self.base_url = account.base_url.rstrip("/")
        self.token = account.token
        self.default_org = account.default_organization_id

    # ── plumbing ─────────────────────────────────────────────────

    def _request(self, method: str, path: str, *, json_body: Any = None,
                 query: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode({k: v for k, v in query.items() if v is not None})}"

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "zergscholar-skill/0.1",
        }
        data = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body).encode("utf-8")

        req = request.Request(url, data=data, headers=headers, method=method)
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                with request.urlopen(req, timeout=120) as resp:
                    raw = resp.read()
                    if not raw:
                        return None
                    return json.loads(raw.decode("utf-8"))
            except error.HTTPError as e:
                body_raw = e.read().decode("utf-8", errors="replace")
                try:
                    body = json.loads(body_raw)
                    msg = body.get("statusMessage") or body.get("message") or body_raw
                except Exception:
                    body = body_raw
                    msg = body_raw[:300]
                # Retry only on transient server-side conditions.
                if e.code in (502, 503, 504) and attempt < 4:
                    time.sleep(1.5 * (attempt + 1))
                    last_exc = e
                    continue
                raise ApiError(e.code, msg, body) from None
            except (error.URLError, TimeoutError, OSError) as e:
                # DNS / connection refused / SSL handshake / etc — back off
                # and try again. All endpoints the skill calls are idempotent
                # on the server (PK conflicts + content dedup).
                if attempt < 4:
                    time.sleep(1.5 * (attempt + 1))
                    last_exc = e
                    continue
                raise ApiError(0, f"Network error after retries: {e}", None) from None
        raise ApiError(0, f"Exhausted retries: {last_exc}", None)

    # ── workspace + identity ─────────────────────────────────────

    def whoami(self) -> dict:
        # /api/auth/me returns the user; we also fetch /api/orgs to
        # enumerate workspaces the token can reach.
        me = self._request("GET", "/api/auth/me")
        orgs = self._request("GET", "/api/orgs")
        return {"user": me, "organizations": orgs.get("organizations", [])}

    def list_orgs(self) -> list[dict]:
        return self._request("GET", "/api/orgs").get("organizations", [])

    # ── papers ───────────────────────────────────────────────────

    def list_papers(self, org_id: str, *, search: str | None = None,
                    limit: int = 200, offset: int = 0) -> list[dict]:
        return self._request(
            "GET", "/api/papers",
            query={"organizationId": org_id, "search": search, "limit": limit, "offset": offset}
        ).get("papers", [])

    def count_papers(self, org_id: str) -> int:
        """Cheap count via the same endpoint — server returns a `total`
        alongside the page. Avoids paging when the caller only needs
        the workspace size."""
        resp = self._request(
            "GET", "/api/papers",
            query={"organizationId": org_id, "limit": 1}
        )
        return int(resp.get("total", 0))

    def get_paper(self, paper_id: str) -> dict:
        return self._request("GET", f"/api/papers/{paper_id}").get("paper", {})

    def add_paper(self, *, title: str, authors: list[str] | None = None,
                  year: int | None = None, abstract: str | None = None,
                  doi: str | None = None, arxiv_id: str | None = None,
                  journal: str | None = None, url: str | None = None,
                  tags: list[str] | None = None, body_content: str | None = None) -> dict:
        # Postgres TEXT columns reject NUL bytes (0x00) — Notion-imported
        # vault notes occasionally carry stray ones from PDF extraction.
        # Sanitize once at the boundary so callers don't have to.
        def _clean(s):
            return s.replace("\x00", "") if isinstance(s, str) else s
        body = {"title": _clean(title)}
        if authors: body["authors"] = [_clean(a) for a in authors]
        if year is not None: body["year"] = year
        if abstract: body["abstract"] = _clean(abstract)
        if doi: body["doi"] = _clean(doi)
        if arxiv_id: body["arxivId"] = _clean(arxiv_id)
        if journal: body["journal"] = _clean(journal)
        if url: body["url"] = _clean(url)
        if tags: body["tags"] = [_clean(t) for t in tags]
        if body_content: body["body"] = _clean(body_content)
        return self._request("POST", "/api/external/add-paper", json_body=body).get("paper", {})

    def enrich_paper(self, *, paper_id: str, tags: list[str] | None = None,
                     body_content: str | None = None, authors: list[str] | None = None,
                     abstract: str | None = None) -> dict:
        def _clean(s):
            return s.replace("\x00", "") if isinstance(s, str) else s
        body: dict = {"paperId": paper_id}
        if tags: body["tags"] = [_clean(t) for t in tags]
        if body_content: body["body"] = _clean(body_content)
        if authors: body["authors"] = [_clean(a) for a in authors]
        if abstract: body["abstract"] = _clean(abstract)
        return self._request("POST", "/api/external/enrich-paper", json_body=body)

    def upload_pdf(self, paper_id: str, pdf_path: str) -> dict:
        filename = os.path.basename(pdf_path)
        with open(pdf_path, "rb") as f:
            return self.upload_pdf_bytes(paper_id, filename, f.read())

    def upload_pdf_bytes(self, paper_id: str, filename: str, data: bytes) -> dict:
        # Binary path — query params + raw application/pdf body.
        # Avoids the 35% base64 inflation that was OOM-ing Fly's edge.
        url = f"{self.base_url}/api/external/upload-pdf?paperId={quote(paper_id, safe='')}&filename={quote(filename, safe='')}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/pdf",
            "Accept": "application/json",
            "User-Agent": "zergscholar-skill/0.1",
        }
        req = request.Request(url, data=data, headers=headers, method="POST")
        last_exc = None
        for attempt in range(5):
            try:
                with request.urlopen(req, timeout=180) as resp:
                    raw = resp.read()
                    return json.loads(raw.decode("utf-8")) if raw else {}
            except error.HTTPError as e:
                if e.code in (502, 503, 504) and attempt < 4:
                    time.sleep(2.0 * (attempt + 1))
                    last_exc = e
                    continue
                body = e.read().decode("utf-8", errors="replace")
                raise ApiError(e.code, body[:300] or str(e), None) from None
            except (error.URLError, TimeoutError, OSError) as e:
                if attempt < 4:
                    time.sleep(2.0 * (attempt + 1))
                    last_exc = e
                    continue
                raise ApiError(0, f"Network error after retries: {e}", None) from None
        raise ApiError(0, f"Exhausted retries: {last_exc}", None)

    def extract_paper_text(self, paper_id: str, *, force: bool = False) -> dict:
        path = f"/api/papers/{paper_id}/extract-text"
        if force:
            path += "?force=1"
        return self._request("POST", path)

    def find_paper(self, *, doi: str | None = None, arxiv_id: str | None = None) -> dict | None:
        if not doi and not arxiv_id:
            return None
        return self._request(
            "GET", "/api/external/find-paper",
            query={"doi": doi, "arxivId": arxiv_id}
        ).get("paper")

    # ── knowledge ────────────────────────────────────────────────

    def add_knowledge(self, *, paper_id: str, entry_type: str, content: str,
                      confidence: float | None = None) -> dict:
        body = {"paperId": paper_id, "entryType": entry_type, "content": content}
        if confidence is not None: body["confidence"] = confidence
        return self._request("POST", "/api/external/add-knowledge", json_body=body).get("entry", {})

    def list_knowledge(self, org_id: str, paper_id: str | None = None) -> list[dict]:
        return self._request(
            "GET", "/api/knowledge",
            query={"organizationId": org_id, "paperId": paper_id}
        ).get("entries", [])

    # ── annotations ──────────────────────────────────────────────

    def add_annotation(self, *, paper_id: str, content: str,
                       page_number: int | None = None, highlight_text: str | None = None) -> dict:
        body: dict = {"content": content}
        if page_number is not None: body["pageNumber"] = page_number
        if highlight_text: body["highlightText"] = highlight_text
        return self._request(
            "POST", f"/api/papers/{paper_id}/annotations", json_body=body
        ).get("annotation", {})

    # ── documents ────────────────────────────────────────────────

    def list_documents(self, org_id: str) -> list[dict]:
        return self._request(
            "GET", "/api/documents", query={"organizationId": org_id}
        ).get("documents", [])

    def get_document(self, doc_id: str) -> dict:
        return self._request("GET", f"/api/documents/{doc_id}").get("document", {})

    def create_document(self, *, org_id: str, title: str,
                        format: str = "markdown", content: str = "",
                        template: str | None = None) -> dict:
        body: dict = {
            "organizationId": org_id,
            "title": title,
            "format": format,
            "content": content,
        }
        if template: body["template"] = template
        return self._request("POST", "/api/documents", json_body=body).get("document", {})

    def update_document(self, doc_id: str, *, title: str | None = None,
                        content: str | None = None, status: str | None = None) -> dict:
        body: dict = {}
        if title is not None: body["title"] = title
        if content is not None: body["content"] = content
        if status is not None: body["status"] = status
        return self._request("PATCH", f"/api/documents/{doc_id}", json_body=body).get("document", {})
