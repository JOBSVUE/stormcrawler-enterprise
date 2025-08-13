"""
extract_api_rest.py

Simple FastAPI REST service that accepts raw HTML (JSON POST) and returns extracted JSON ready for indexing.
No Redis/Kafka — synchronous HTTP request/response only.

Usage:
  POST /extract
  Body (application/json):
    {
      "url": "https://example.com/article",
      "html_content": "<html>...</html>",
      "company_id": "acme",            # optional
      "metadata": { ... },            # optional
      "fetch_metadata": { ... }       # optional
    }

Responses:
  200 -> JSON document ready for indexing (includes `document_id`)
  204 -> No content extracted (too short / extraction failed)
  400 -> Bad request
  500 -> Internal error
"""

import json
import logging
import hashlib
import time
import concurrent.futures
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urlunparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, Field

# Ensure trafilatura is available
try:
    import trafilatura  # type: ignore
    _TRAFILATURA_AVAILABLE = True
except Exception:
    _TRAFILATURA_AVAILABLE = False

# Configuration defaults
MAX_HTML_LENGTH = 1_000_000        # characters
EXTRACTION_TIMEOUT = 15           # seconds
MIN_EXTRACTED_CHARS = 50

logger = logging.getLogger("extract_api_rest")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="HTML Extractor API", version="1.0")

# Healthcheck endpoint
@app.get("/health")
async def health():
    return {"status": "ok"}


class ExtractRequest(BaseModel):
    url: HttpUrl
    html_content: str = Field(..., min_length=1)
    company_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    fetch_metadata: Optional[Dict[str, Any]] = None


class ExtractResponse(BaseModel):
    document_id: str
    url: HttpUrl
    company_id: Optional[str] = None
    title: Optional[str] = None
    content: str
    metadata: Optional[Dict[str, Any]] = None
    extraction_metadata: Dict[str, Any]
    timestamp: int


def _normalize_url(url: str) -> str:
    """Normalize URL for id generation (lowercase scheme/host, strip fragment, default port removal)."""
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if scheme == "http" and netloc.endswith(":80"):
            netloc = netloc[:-3]
        if scheme == "https" and netloc.endswith(":443"):
            netloc = netloc[:-4]
        normalized = urlunparse((scheme, netloc, parsed.path or "/", parsed.params, parsed.query, ""))
        return normalized
    except Exception:
        return url


def _doc_id_for(company_id: Optional[str], url: str) -> str:
    """Create deterministic bounded-length id using SHA1(company_id|normalized_url)."""
    normalized = _normalize_url(url)
    key = f"{company_id or ''}|{normalized}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _run_trafilatura_extract(html_content: str, url: str) -> Optional[Dict[str, Any]]:
    """
    Call trafilatura.extract with JSON output and parse it.
    Returns dict on success, None otherwise.
    """
    try:
        # output_format="json" returns a JSON string with metadata
        result = trafilatura.extract(
            html_content,
            url=url,
            output_format="json",
            with_metadata=True,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
        if not result:
            return None
        # parse JSON string to python dict
        return json.loads(result)
    except Exception:
        logger.exception("Trafilatura extraction failed")
        return None


@app.on_event("startup")
def startup_event():
    if not _TRAFILATURA_AVAILABLE:
        logger.error("Trafilatura is required but not available. Install trafilatura.")
        # Do not raise here — allow container to start but endpoint will fail with 500 if used.
    else:
        logger.info("Trafilatura is available; extractor ready.")


@app.post("/extract", response_model=ExtractResponse, responses={204: {"description": "No content extracted"}})
async def extract_endpoint(payload: ExtractRequest):
    """
    Extract content from provided raw HTML and return JSON-ready document.
    """
    if not _TRAFILATURA_AVAILABLE:
        raise HTTPException(status_code=500, detail="Trafilatura not installed on server")

    html = payload.html_content or ""
    if not html:
        raise HTTPException(status_code=400, detail="html_content must be provided and non-empty")

    # Optional: short-circuit if caller told us the content-type is not HTML/XML
    ctype = None
    if payload.fetch_metadata:
        ctype = payload.fetch_metadata.get("content_type") or payload.fetch_metadata.get("Content-Type")
    if ctype and ("html" not in ctype.lower() and "xml" not in ctype.lower()):
        logger.info("Non-HTML content-type %s for %s; returning 204", ctype, payload.url)
        return JSONResponse(status_code=204, content=None)

    # Quick heuristic: reject if doesn't look like HTML
    if "<" not in html:
        logger.info("html_content doesn't look like HTML for %s; returning 204", payload.url)
        return JSONResponse(status_code=204, content=None)

    if len(html) > MAX_HTML_LENGTH:
        # Defensive: avoid feeding extremely large inputs
        raise HTTPException(status_code=400, detail=f"html_content exceeds maximum allowed length of {MAX_HTML_LENGTH}")

    # Offload extraction to thread to allow timeout
    future = _executor.submit(_run_trafilatura_extract, html, str(payload.url))
    try:
        data = future.result(timeout=EXTRACTION_TIMEOUT)
    except concurrent.futures.TimeoutError:
        logger.exception("Extraction timed out")
        raise HTTPException(status_code=500, detail="Extraction timed out")
    except Exception:
        logger.exception("Extraction execution failed")
        raise HTTPException(status_code=500, detail="Extraction failed")

    if not data:
        # No data returned by trafilatura (could be too short or parsing issue)
        return JSONResponse(status_code=204, content=None)

    text_content = (data.get("text") or "").strip()
    if not text_content or len(text_content) < MIN_EXTRACTED_CHARS:
        # Too short to be useful
        logger.info("Extracted text is empty or too short")
        return JSONResponse(status_code=204, content=None)

    # Title fallback: trafilatura -> fetch_metadata -> empty
    title = (data.get("title") or "").strip()
    if not title and payload.fetch_metadata:
        title = (payload.fetch_metadata.get("title") or "").strip()

    extraction_metadata = {
        "method": "trafilatura",
        "trafilatura": {
            "author": data.get("author"),
            "date": data.get("date"),
            "language": data.get("language"),
            "url": data.get("url"),
            "sitename": data.get("sitename"),
            "description": data.get("description"),
            "categories": data.get("categories"),
            "tags": data.get("tags"),
        },
        "fetch_metadata": payload.fetch_metadata or {},
        "extraction_time": time.time(),
        "word_count": len(text_content.split()),
        "character_count": len(text_content),
        "received_html_chars": len(html),
    }

    timestamp_ms = int(time.time() * 1000)
    document_id = _doc_id_for(payload.company_id, str(payload.url))

    response_doc = {
        "document_id": document_id,
        "url": str(payload.url),
        "company_id": payload.company_id,
        "title": title or None,
        "content": text_content,
        "metadata": payload.metadata or {},
        "extraction_metadata": extraction_metadata,
        "timestamp": timestamp_ms,
    }

    return JSONResponse(status_code=200, content=response_doc)


if __name__ == "__main__":
    import uvicorn
    import os
    # Run with: python app.py
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
