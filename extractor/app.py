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
import os
import re
from collections import Counter
from html import unescape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, Field

# Ensure trafilatura is available
try:
    import trafilatura  # type: ignore
    _TRAFILATURA_AVAILABLE = True
except Exception:
    _TRAFILATURA_AVAILABLE = False

# SEO helpers (these imports will raise if mandatory summarizers are missing)
try:
    from .seo_description import extract_meta_description, generate_description, _normalize_whitespace, _clamp
    # also import module for calling helpers if needed
    from . import seo_description as seo_desc_mod
except Exception as e:
    # Make error explicit so startup fails fast with a helpful message.
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("extract_api_rest")
    logger.critical("Failed to import seo_description module or mandatory summarization libraries: %s", e)
    raise

# Configuration defaults
MAX_HTML_LENGTH = 1_000_000        # characters
EXTRACTION_TIMEOUT = 15           # seconds
MIN_EXTRACTED_CHARS = 50
# SEO description config
SEO_DESC_MODE = os.getenv("SEO_DESC_MODE", "c").lower()         # 'a' | 'b' | 'c'
SEO_DESC_MAX_CHARS = int(os.getenv("SEO_DESC_MAX_CHARS", "160"))

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
    seo_description: Optional[str] = None
    keywords: Optional[list[str]] = None
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
    # Fail fast if trafilatura isn't available.
    missing = []
    if not _TRAFILATURA_AVAILABLE:
        missing.append("trafilatura")
    # If mandatory summarizers are missing, the import above would already have failed;
    # this is an extra check to be explicit in logs if somehow flags are not set.
    if not getattr(seo_desc_mod, "_SUMY_AVAILABLE", False):
        missing.append("sumy")
    if not getattr(seo_desc_mod, "_TRANSFORMERS_AVAILABLE", False):
        missing.append("transformers")

    if missing:
        logger.critical("Required dependencies missing: %s", ", ".join(missing))
        logger.critical("Install them and restart the service. Example: pip install sumy transformers sentencepiece torch")
        raise RuntimeError(f"Missing required packages: {', '.join(missing)}")

    logger.info("All required dependencies present; extractor ready.")


# --- Keywords helpers (no heavy deps) ---
_STOPWORDS = {
    "the","and","for","with","from","that","this","your","you","are","was","were","will","shall","have","has",
    "into","our","out","over","under","their","there","here","about","after","before","more","most","other",
    "than","then","also","can","use","using","used","via","by","on","in","to","of","a","an","as","at","it",
    "is","be","or","not","we","us","they","he","she","his","her","them","its"
}

def _kw_parse_list(s: str) -> list[str]:
    s = (s or "").strip()
    if not s:
        return []
    # split on common separators
    parts = re.split(r"[,\|\n;\t•]+", s)
    out = []
    for p in parts:
        p = re.sub(r"[^\w\s\-]", " ", p)
        p = re.sub(r"[-_]+", " ", p).strip().lower()
        if 2 <= len(p) <= 100 and p not in ("keyword","keywords","tag","tags"):
            out.append(p)
    # de-dup preserving order
    seen = set()
    uniq = []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq

def _kw_from_meta(html: str) -> list[str]:
    kws = []
    for meta in re.findall(r"<meta\b[^>]*>", html or "", flags=re.I):
        attrs = dict(re.findall(r'(\w[\w:-]*)\s*=\s*["\']([^"\']+)["\']', meta, flags=re.I))
        for key in ("name","property","itemprop"):
            val = (attrs.get(key) or "").lower()
            if "keyword" in val:  # matches keywords, news_keywords, itemprop=keywords
                content = attrs.get("content") or ""
                kws.extend(_kw_parse_list(content))
                break
    return kws[:20]

def _kw_from_jsonld(html: str) -> list[str]:
    import json
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or "", flags=re.I|re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                for k, v in item.items():
                    if "keyword" in str(k).lower():
                        if isinstance(v, str):
                            out.extend(_kw_parse_list(v))
                        elif isinstance(v, list):
                            for e in v:
                                if isinstance(e, str):
                                    out.append(e.strip().lower())
                                elif isinstance(e, dict) and "name" in e:
                                    out.append(str(e["name"]).strip().lower())
    # clean + cap
    return _kw_parse_list(", ".join(out))[:20]

def _kw_from_title_headers(html: str) -> list[str]:
    parts = []
    t = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.I|re.S)
    if t:
        parts.append(re.sub(r"\s+", " ", t.group(1)).strip())
    for h in ("h1","h2","h3"):
        parts += [re.sub(r"\s+", " ", m).strip()
                  for m in re.findall(rf"<{h}[^>]*>(.*?)</{h}>", html or "", flags=re.I|re.S)]
    text = " ".join(p for p in parts if p)
    words = [w.lower() for w in re.split(r"\W+", text) if len(w) > 2 and w.lower() not in _STOPWORDS]
    return list(dict.fromkeys(words))[:10]

def _kw_from_text(text: str) -> list[str]:
    words = [w.lower() for w in re.split(r"\W+", text or "") if len(w) > 3 and w.lower() not in _STOPWORDS]
    if not words:
        return []
    freq = Counter(words)
    return [w for w, c in freq.most_common(12) if c >= 2][:12]

def _kw_from_url(url: str) -> list[str]:
    try:
        p = urlparse(url or "")
        parts = [seg for seg in (p.path or "").split("/") if seg]
        out = []
        for seg in parts:
            seg = re.sub(r"[^\w\s\-]", " ", seg)
            seg = re.sub(r"[-_]+", " ", seg).strip().lower()
            out += [w for w in seg.split() if len(w) > 3 and w not in _STOPWORDS]
        return list(dict.fromkeys(out))[:5]
    except Exception:
        return []

def _extract_keywords(html: str, url: str, text_content: str, trafi: Dict[str, Any]) -> tuple[list[str], Dict[str, Any]]:
    # Primary: meta/JSON-LD
    meta_kws = _kw_from_meta(html)
    if meta_kws:
        return meta_kws, {"method": "primary", "source": "meta", "count": len(meta_kws)}
    jsonld_kws = _kw_from_jsonld(html)
    if jsonld_kws:
        return jsonld_kws, {"method": "primary", "source": "jsonld", "count": len(jsonld_kws)}
    # Fallbacks: trafilatura tags/categories
    trafi_kws = []
    for k in ("tags","categories"):
        v = trafi.get(k)
        if isinstance(v, list):
            trafi_kws += [str(x).strip().lower() for x in v if str(x).strip()]
    trafi_kws = list(dict.fromkeys(trafi_kws))[:20]
    if trafi_kws:
        return trafi_kws, {"method": "fallback", "source": "trafilatura", "count": len(trafi_kws)}
    # Title/headers
    th = _kw_from_title_headers(html)
    if th:
        return th, {"method": "fallback", "source": "title_headers", "count": len(th)}
    # Content frequency
    tf = _kw_from_text(text_content)
    if tf:
        return tf, {"method": "fallback", "source": "content_freq", "count": len(tf)}
    # URL path
    uk = _kw_from_url(url)
    if uk:
        return uk, {"method": "fallback", "source": "url_path", "count": len(uk)}
    return [], {"method": "none", "source": "none", "count": 0}
# --- end keywords helpers ---


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

    # --- SEO description selection (preferred order) ---
    # 1) trafilatura's description (preferred)
    # 2) HTML meta description (og:, twitter:, name=description)
    # 3) generated description (transformers/sumy/simple)
    seo_desc_source = None
    seo_desc_val = None

    # 1) trafilatura-provided description
    trafi_desc_raw = (data.get("description") or "").strip()
    if trafi_desc_raw:
        try:
            # normalize/unescape and clamp using helpers from seo_description module
            norm = _normalize_whitespace(unescape(st := trafi_desc_raw))
            seo_desc_val = _clamp(norm, SEO_DESC_MAX_CHARS)
            seo_desc_source = "trafilatura"
        except Exception:
            # Fallback simple clamp
            cand = unescape(strafi := trafi_desc_raw)
            if len(cand) > SEO_DESC_MAX_CHARS:
                seo_desc_val = cand[:SEO_DESC_MAX_CHARS].rstrip() + "…"
            else:
                seo_desc_val = cand
            seo_desc_source = "trafilatura"

    # 2) HTML meta description
    if not seo_desc_val:
        md = extract_meta_description(html, max_chars=SEO_DESC_MAX_CHARS)
        if md:
            seo_desc_val = md
            seo_desc_source = "meta"

    # 3) generated fallback
    if not seo_desc_val:
        seo_desc_val, gen_src = generate_description(text_content, mode=SEO_DESC_MODE, max_chars=SEO_DESC_MAX_CHARS)
        seo_desc_source = gen_src

    seo_desc = seo_desc_val or None

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
    # Attach SEO description provenance
    if seo_desc:
        extraction_metadata["seo_description"] = {
            "source": seo_desc_source,
            "length": len(seo_desc),
            "max_chars": SEO_DESC_MAX_CHARS,
            "mode": SEO_DESC_MODE,
        }

    timestamp_ms = int(time.time() * 1000)
    document_id = _doc_id_for(payload.company_id, str(payload.url))

    # NEW: keywords
    keywords, kw_meta = _extract_keywords(html, str(payload.url), text_content, data)
    if keywords:
        extraction_metadata["keywords"] = kw_meta

    response_doc = {
        "document_id": document_id,
        "url": str(payload.url),
        "company_id": payload.company_id or str(payload.url),
        "title": title or None,
        "content": text_content,
        "seo_description": seo_desc or None,
        "keywords": keywords or None,
        "metadata": payload.metadata or {},
        "extraction_metadata": extraction_metadata,
        "timestamp": timestamp_ms,
    }

    return JSONResponse(status_code=200, content=response_doc)


if __name__ == "__main__":
    import uvicorn
    import os
    # Run with: python app.py
    uvicorn.run("extractor.app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
