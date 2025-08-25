"""
extract_api_rest.py

FastAPI REST service that accepts raw HTML (JSON POST) and returns extracted JSON ready for indexing.
"""

import json
import logging
import hashlib
import time
import concurrent.futures
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, urlunparse
import os
import re
from html import unescape

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, Field

# ---- Mandatory dependencies (fail fast if missing) ----
try:
    import trafilatura  # type: ignore
except Exception as e:
    raise ImportError("trafilatura is required. Install with: pip install trafilatura") from e

# SEO helpers — these imports will fail if required summarizers / parsers are missing
try:
    from .seo_description import (
        extract_meta_description,
        generate_description,
        _normalize_whitespace,
        _clamp,
        generate_keywords_with_hf,
    )
    from . import seo_description as seo_desc_mod
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("extract_api_rest")
    logger.critical("Failed to import seo_description or mandatory summarization libraries: %s", e)
    raise

# langdetect (mandatory for language detection fallback)
try:
    from langdetect import detect_langs  # type: ignore
except Exception as e:
    raise ImportError("langdetect is required. Install with: pip install langdetect") from e

# BeautifulSoup is already enforced in seo_description.py; import for HTML lang parsing
from bs4 import BeautifulSoup  # type: ignore

# Configuration defaults
MAX_HTML_LENGTH = 1_000_000        # characters
EXTRACTION_TIMEOUT = 15           # seconds
MIN_EXTRACTED_CHARS = 50
SEO_DESC_MODE = os.getenv("SEO_DESC_MODE", "c").lower()
SEO_DESC_MAX_CHARS = int(os.getenv("SEO_DESC_MAX_CHARS", "160"))

# Keywords/LLM config
MIN_KEYWORDS_BEFORE_LLM = int(os.getenv("MIN_KEYWORDS_BEFORE_LLM", "3"))
MAX_KEYWORDS_FROM_LLM = int(os.getenv("MAX_KEYWORDS_FROM_LLM", "12"))
KEYWORD_MODEL_ENV = os.getenv("KEYWORD_MODEL", "google/flan-t5-large")

# Language detection config
LANG_DETECT_PROB_THRESHOLD = float(os.getenv("LANG_DETECT_PROB_THRESHOLD", "0.20"))
MAX_LANGUAGES = int(os.getenv("MAX_LANGUAGES", "4"))

logger = logging.getLogger("extract_api_rest")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="HTML Extractor API", version="1.0")

# Healthcheck
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
    keywords: Optional[List[str]] = None
    languages: Optional[List[str]] = None
    contact_us: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    extraction_metadata: Dict[str, Any]
    timestamp: int


def _normalize_url(url: str) -> str:
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
    normalized = _normalize_url(url)
    key = f"{company_id or ''}|{normalized}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _run_trafilatura_extract(html_content: str, url: str) -> Optional[Dict[str, Any]]:
    try:
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
        return json.loads(result)
    except Exception:
        logger.exception("Trafilatura extraction failed")
        return None


@app.on_event("startup")
def startup_event():
    # The strict imports above will have failed if mandatory packages are missing.
    # Log a successful readiness note.
    logger.info("Extractor starting; required dependencies verified at import time.")


# --- Keywords helpers (no heavy deps) ---
_STOPWORDS = {
    "the","and","for","with","from","that","this","your","you","are","was","were","will","shall","have","has",
    "into","our","out","over","under","their","there","here","about","after","before","more","most","other",
    "than","then","also","can","use","using","used","via","by","on","in","to","of","a","an","as","at","it",
    "is","be","or","not","we","us","they","he","she","his","her","them","its"
}


def _kw_parse_list(s: str) -> List[str]:
    s = (s or "").strip()
    if not s:
        return []
    parts = re.split(r"[,\|\n;\t•]+", s)
    out = []
    for p in parts:
        p = re.sub(r"[^\w\s\-]", " ", p)
        p = re.sub(r"[-_]+", " ", p).strip().lower()
        if 2 <= len(p) <= 100 and p not in ("keyword","keywords","tag","tags"):
            out.append(p)
    seen = set()
    uniq = []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def _kw_from_meta(html: str) -> List[str]:
    kws = []
    for meta in re.findall(r"<meta\b[^>]*>", html or "", flags=re.I):
        attrs = dict(re.findall(r'(\w[\w:-]*)\s*=\s*["\']([^"\']+)["\']', meta, flags=re.I))
        for key in ("name", "property", "itemprop"):
            val = (attrs.get(key) or "").lower()
            if "keyword" in val:
                content = attrs.get("content") or ""
                kws.extend(_kw_parse_list(content))
                break
    return kws[:20]


def _kw_from_jsonld(html: str) -> List[str]:
    import json
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or "", flags=re.I | re.S):
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
    return _kw_parse_list(", ".join(out))[:20]


# ---------------- Simplified keyword extraction (per spec) ----------------
def _extract_keywords(html: str, url: str, text_content: str, trafi: Dict[str, Any]) -> tuple[List[str], Dict[str, Any]]:
    """
    Keyword extraction priority (exactly per spec):
      1) Meta keywords (_kw_from_meta)
      2) JSON-LD keywords (_kw_from_jsonld)
      3) LLM-based extraction (generate_keywords_with_hf) as a best-effort fallback
    No other fallback chains are used here.
    """
    # 1) Meta keywords
    meta_kws = _kw_from_meta(html)
    if meta_kws:
        return meta_kws, {"method": "primary", "source": "meta", "count": len(meta_kws)}

    # 2) JSON-LD keywords
    jsonld_kws = _kw_from_jsonld(html)
    if jsonld_kws:
        return jsonld_kws, {"method": "primary", "source": "jsonld", "count": len(jsonld_kws)}

    # 3) LLM-based extraction (best-effort)
    try:
        ctx = text_content[:6000]
        llm_kws = generate_keywords_with_hf(ctx, max_keywords=MAX_KEYWORDS_FROM_LLM)
        if llm_kws:
            return llm_kws, {"method": "llm", "source": KEYWORD_MODEL_ENV, "count": len(llm_kws)}
    except Exception:
        logger.exception("LLM keyword generation failed")

    # None found
    return [], {"method": "none", "source": "none", "count": 0}


# ---------------- Language extraction / detection ----------------
def _normalize_lang_code(code: str) -> Optional[str]:
    if not code:
        return None
    code = str(code).strip().lower()
    code = code.replace("_", "-")
    primary = code.split("-")[0]
    if not primary or not primary.isalpha() or len(primary) < 2:
        return None
    return primary[:2].lower().capitalize()


def _extract_languages_from_jsonld(html: str) -> List[str]:
    import json
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or "", flags=re.I | re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                for k, v in item.items():
                    if str(k).lower() in ("inlanguage", "language", "inLanguage"):
                        if isinstance(v, str):
                            out.append(v)
                        elif isinstance(v, list):
                            for e in v:
                                if isinstance(e, str):
                                    out.append(e)
    norm = []
    for c in out:
        n = _normalize_lang_code(c)
        if n and n not in norm:
            norm.append(n)
    return norm


def _extract_languages(html: str, text_content: str, trafi: Dict[str, Any]) -> tuple[List[str], Dict[str, Any]]:
    langs: List[str] = []
    source_details = {}

    # 1) trafilatura-provided language
    trafi_lang = trafi.get("language")
    if isinstance(trafi_lang, str) and trafi_lang.strip():
        n = _normalize_lang_code(trafi_lang)
        if n:
            langs.append(n)
            source_details["trafilatura"] = str(trafi_lang)

    # 2) HTML lang attribute and meta tags (BeautifulSoup required)
    try:
        soup = BeautifulSoup(html or "", "lxml")
        html_tag = soup.find("html")
        if html_tag:
            lang_attr = (html_tag.get("lang") or "").strip()
            n = _normalize_lang_code(lang_attr)
            if n and n not in langs:
                langs.append(n)
                source_details["html_lang"] = lang_attr

        og = soup.find("meta", attrs={"property": "og:locale"})
        if og and og.get("content"):
            n = _normalize_lang_code(og.get("content"))
            if n and n not in langs:
                langs.append(n)
                source_details["og:locale"] = og.get("content")

        tw = soup.find("meta", attrs={"name": "twitter:language"})
        if tw and tw.get("content"):
            n = _normalize_lang_code(tw.get("content"))
            if n and n not in langs:
                langs.append(n)
                source_details["twitter:language"] = tw.get("content")
    except Exception:
        pass

    # 3) JSON-LD
    try:
        jld = _extract_languages_from_jsonld(html)
        for n in jld:
            if n not in langs:
                langs.append(n)
        if jld:
            source_details["jsonld"] = jld
    except Exception:
        pass

    if langs:
        return langs[:MAX_LANGUAGES], {"method": "extracted", "source_details": source_details, "count": len(langs)}

    # 4) Fallback: langdetect
    detected: List[str] = []
    try:
        candidates = []
        if text_content:
            candidates.append(text_content[:20000])
            paras = [p for p in text_content.split("\n") if p.strip()][:3]
            candidates += paras
        probs = {}
        for c in candidates:
            try:
                langs_probs = detect_langs(c)
            except Exception:
                continue
            for lp in langs_probs:
                code = lp.lang
                prob = lp.prob
                if code and prob:
                    probs[code] = max(probs.get(code, 0.0), prob)
        ordered = sorted(probs.items(), key=lambda x: -x[1])
        for code, p in ordered:
            if p >= LANG_DETECT_PROB_THRESHOLD:
                n = _normalize_lang_code(code)
                if n and n not in detected:
                    detected.append(n)
            if len(detected) >= MAX_LANGUAGES:
                break
    except Exception:
        detected = []

    if detected:
        return detected, {"method": "detected", "source_details": {"probs": dict(ordered[:MAX_LANGUAGES])}, "count": len(detected)}

    return [], {"method": "none", "source_details": {}, "count": 0}


# -------------------- Contact info extraction --------------------
def _extract_contact_info(html: str, text: str) -> Optional[Dict[str, Any]]:
    """
    Extract contact info from the HTML blob and visible text.
    Returns a dict with keys like emails, phones, faxes, social_media (maps to platform->[links]).
    Returns None if nothing found.
    """
    contact_info: Dict[str, Any] = {}
    emails = set(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", html))
    if emails:
        contact_info["emails"] = sorted(emails)

    # Phone-like sequences (simple heuristics)
    phone_candidates = set(re.findall(r"(?:\+?\d[\d\-\s().]{6,}\d)", html))
    phones = []
    for p in phone_candidates:
        normalized = re.sub(r"[^\d+]", "", p)
        # crude length check
        if len(re.sub(r"[^\d]", "", normalized)) >= 7:
            phones.append(normalized)
    if phones:
        contact_info["phones"] = sorted(set(phones))

    # Fax heuristics (look for the word 'fax' nearby)
    fax_matches = []
    for match in re.finditer(r"(fax[:\s]*)([\+\d][\d\-\s().]{6,}\d)", html, flags=re.I):
        raw = match.group(2)
        normalized = re.sub(r"[^\d+]", "", raw)
        if len(re.sub(r"[^\d]", "", normalized)) >= 7:
            fax_matches.append(normalized)
    if fax_matches:
        contact_info["faxes"] = sorted(set(fax_matches))

    # Social media link extraction (common platforms)
    social_patterns = {
        "facebook": r"https?://(?:www\.)?facebook\.com/[^\s\"'>]+",
        "twitter": r"https?://(?:www\.)?twitter\.com/[^\s\"'>]+",
        "instagram": r"https?://(?:www\.)?instagram\.com/[^\s\"'>]+",
        "linkedin": r"https?://(?:www\.)?linkedin\.com/[^\s\"'>]+",
        "youtube": r"https?://(?:www\.)?youtube\.com/[^\s\"'>]+",
        "telegram": r"https?://(?:t\.me|telegram\.me)/[^\s\"'>]+",
        "whatsapp": r"https?://wa\.me/[^\s\"'>]+",
    }
    social_found: Dict[str, List[str]] = {}
    for platform, patt in social_patterns.items():
        matches = re.findall(patt, html, flags=re.I)
        if matches:
            social_found[platform] = sorted(set(matches))
    if social_found:
        contact_info["social_media"] = social_found

    return contact_info if contact_info else None


# -------------------- Main extract endpoint --------------------
@app.post("/extract", response_model=ExtractResponse, responses={204: {"description": "No content extracted"}})
async def extract_endpoint(payload: ExtractRequest):
    if not payload or not payload.html_content:
        raise HTTPException(status_code=400, detail="html_content must be provided and non-empty")

    html = payload.html_content or ""
    if "<" not in html:
        logger.info("html_content doesn't look like HTML for %s; returning 204", payload.url)
        return JSONResponse(status_code=204, content=None)

    if len(html) > MAX_HTML_LENGTH:
        raise HTTPException(status_code=400, detail=f"html_content exceeds maximum allowed length of {MAX_HTML_LENGTH}")

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
        return JSONResponse(status_code=204, content=None)

    text_content = (data.get("text") or "").strip()
    if not text_content or len(text_content) < MIN_EXTRACTED_CHARS:
        logger.info("Extracted text is empty or too short")
        return JSONResponse(status_code=204, content=None)

    title = (data.get("title") or "").strip()
    if not title and payload.fetch_metadata:
        title = (payload.fetch_metadata.get("title") or "").strip()

    # --- SEO description prioritization (per spec) ---
    seo_desc_source = None
    seo_desc_val: Optional[str] = None

    # 1) trafilatura description (preferred) — NORMALIZE but DO NOT CLAMP
    trafi_desc_raw = (data.get("description") or "").strip()
    if trafi_desc_raw:
        try:
            norm = _normalize_whitespace(unescape(st := trafi_desc_raw))
            seo_desc_val = norm  # NOTE: do not clamp here per spec
            seo_desc_source = "trafilatura"
        except Exception:
            cand = unescape(trafi_desc_raw)
            seo_desc_val = cand
            seo_desc_source = "trafilatura"

    # 2) HTML meta description (BeautifulSoup required) — NORMALIZE but DO NOT CLAMP
    if not seo_desc_val:
        md = extract_meta_description(html, max_chars=SEO_DESC_MAX_CHARS)
        if md:
            seo_desc_val = md  # already normalized by extract_meta_description
            seo_desc_source = "meta"

    # 3) generated (transformers -> sumy). Generated output WILL be clamped in generate_description
    if not seo_desc_val:
        try:
            seo_desc_val, gen_src = generate_description(text_content, mode=SEO_DESC_MODE, max_chars=SEO_DESC_MAX_CHARS)
            seo_desc_source = gen_src
        except Exception:
            logger.exception("Description generation failed")
            seo_desc_val = None
            seo_desc_source = None

    seo_desc = seo_desc_val or None

    # languages
    languages_list, lang_meta = _extract_languages(html, text_content, data)
    languages = languages_list or None

    # contact info
    try:
        contact_us = _extract_contact_info(html, text_content)
    except Exception:
        logger.exception("Contact extraction failed")
        contact_us = None

    extraction_metadata: Dict[str, Any] = {
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

    if seo_desc:
        extraction_metadata["seo_description"] = {
            "source": seo_desc_source,
            "length": len(seo_desc),
            "max_chars": SEO_DESC_MAX_CHARS,
            "mode": SEO_DESC_MODE,
        }

    extraction_metadata["languages"] = lang_meta
    if contact_us:
        extraction_metadata["contact_us_extracted"] = True

    document_id = _doc_id_for(payload.company_id, str(payload.url))

    # keywords
    keywords, kw_meta = _extract_keywords(html, str(payload.url), text_content, data)
    if keywords:
        extraction_metadata["keywords"] = kw_meta

    timestamp_ms = int(time.time() * 1000)

    response_doc: Dict[str, Any] = {
        "document_id": document_id,
        "url": str(payload.url),
        "company_id": payload.company_id or str(payload.url),
        "title": title or None,
        "content": text_content,
        "seo_description": seo_desc or None,
        "keywords": keywords or None,
        "languages": languages or None,
        "contact_us": contact_us or None,
        "metadata": payload.metadata or {},
        "extraction_metadata": extraction_metadata,
        "timestamp": timestamp_ms,
    }

    return JSONResponse(status_code=200, content=response_doc)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("extractor.app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")

