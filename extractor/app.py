"""
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

# Require phonenumbers for phone normalization (mandatory per request)
try:
    import phonenumbers  # type: ignore
    from phonenumbers import NumberParseException, PhoneNumberFormat
except Exception as e:
    raise ImportError("phonenumbers is required. Install with: pip install phonenumbers") from e

# SEO helpers — these imports will fail if required summarizers / parsers are missing
try:
    from .extraction_helpers import (
        extract_meta_description,
        generate_description,
        _normalize_whitespace,
        _clamp,
        generate_keywords_with_hf,
    )
    from . import extraction_helpers as seo_desc_mod
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("extract_api_rest")
    logger.critical("Failed to import extraction_helpers or mandatory summarization libraries: %s", e)
    raise

# langdetect (mandatory for language detection fallback)
try:
    from langdetect import detect_langs  # type: ignore
except Exception as e:
    raise ImportError("langdetect is required. Install with: pip install langdetect") from e

# BeautifulSoup is already enforced in extraction_helpers.py; import for HTML lang parsing
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
        p = re.sub(r"[^\w\s\-]", " ", p)  # keep unicode word chars, spaces, hyphens
        p = re.sub(r"[-_]+", " ", p).strip().lower()
        if 2 <= len(p) <= 100 and p not in ("keyword","keywords","tag","tags"):
            out.append(p)
    # dedupe preserving order
    seen = set()
    uniq = []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    # filter stopwords
    filtered = [k for k in uniq if k not in _STOPWORDS]
    return filtered


def _kw_from_meta(html: str) -> List[str]:
    """
    Robust meta keyword extraction using BeautifulSoup.
    Looks for meta tags where name/property/itemprop contains 'keyword' (case-insensitive)
    and extracts content/value.
    """
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        # fallback to regex-based extraction if BeautifulSoup fails (very defensive)
        return _kw_from_meta_regex(html)

    candidates: List[str] = []
    try:
        for tag in soup.find_all("meta"):
            name_attr = ""
            # check common attributes
            for a in ("name", "property", "itemprop"):
                if tag.has_attr(a):
                    name_attr = (tag.get(a) or "").lower()
                    if "keyword" in name_attr:
                        content = (tag.get("content") or tag.get("value") or "").strip()
                        if content:
                            candidates.extend(_kw_parse_list(content))
                        break
    except Exception:
        # in case of unexpected tag structures, fallback
        return _kw_from_meta_regex(html)
    return candidates[:20]


def _kw_from_meta_regex(html: str) -> List[str]:
    # Original regex fallback for extreme edge cases
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
    """
    Robust JSON-LD keyword extraction using BeautifulSoup to find script tags
    and json.loads on their contents. Handles arrays, dicts, nested 'keyword' keys,
    and values which may be strings, lists, or objects with 'name'.
    """
    if not html:
        return []

    out = []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        # fallback to the regex-based approach used previously
        return _kw_from_jsonld_regex(html)

    try:
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text() or ""
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                # skip invalid JSON blocks
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                # search for keys containing "keyword" (case-insensitive)
                for k, v in item.items():
                    if "keyword" in str(k).lower():
                        if isinstance(v, str):
                            out.extend(_kw_parse_list(v))
                        elif isinstance(v, list):
                            for e in v:
                                if isinstance(e, str):
                                    out.extend(_kw_parse_list(e))
                                elif isinstance(e, dict) and "name" in e:
                                    name_val = e.get("name") or ""
                                    if isinstance(name_val, str):
                                        out.extend(_kw_parse_list(name_val))
                        elif isinstance(v, dict) and "name" in v:
                            name_val = v.get("name") or ""
                            if isinstance(name_val, str):
                                out.extend(_kw_parse_list(name_val))
                # also check common schema fields which sometimes carry keywords
                if "about" in item and isinstance(item["about"], (str, list, dict)):
                    maybe = item["about"]
                    if isinstance(maybe, str):
                        out.extend(_kw_parse_list(maybe))
                    elif isinstance(maybe, list):
                        for e in maybe:
                            if isinstance(e, str):
                                out.extend(_kw_parse_list(e))
                            elif isinstance(e, dict) and "name" in e:
                                out.extend(_kw_parse_list(str(e["name"])))
    except Exception:
        return _kw_from_jsonld_regex(html)

    return _kw_parse_list(", ".join(out))[:20]


def _kw_from_jsonld_regex(html: str) -> List[str]:
    import json as _json
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or "", flags=re.I | re.S):
        try:
            data = _json.loads(m.group(1))
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


# -------------------- Contact info extraction (enhanced) --------------------
def _guess_country_from_html_url(html: str, url: str, trafi: Dict[str, Any]) -> Optional[str]:
    """
    Heuristic to guess ISO country code (2-letter) to assist phonenumbers parsing.
    Order:
      1) JSON-LD address country (if present)
      2) meta property og:locale (en_US -> US)
      3) html lang with region (en-US -> US)
      4) TLD mapping for common country-code TLDs (.de -> DE)
      5) trafilatura sitename country? (not reliable)
      6) None (caller must handle)
    """
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        soup = None

    # 1) JSON-LD address country
    try:
        for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or "", flags=re.I | re.S):
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    addr = item.get("address") or item.get("Address") or item.get("postalAddress")
                    if isinstance(addr, dict):
                        country = addr.get("addressCountry") or addr.get("country")
                        if isinstance(country, str) and len(country.strip()) >= 2:
                            return country.strip().upper()
    except Exception:
        pass

    # 2) og:locale
    try:
        if soup:
            og = soup.find("meta", attrs={"property": "og:locale"})
            if og and og.get("content"):
                c = og.get("content")
                if "_" in c:
                    return c.split("_")[-1].upper()
                if "-" in c:
                    return c.split("-")[-1].upper()
    except Exception:
        pass

    # 3) html lang attribute with region
    try:
        if soup:
            html_tag = soup.find("html")
            if html_tag:
                lang_attr = (html_tag.get("lang") or "").strip()
                if "-" in lang_attr:
                    return lang_attr.split("-")[-1].upper()
                if "_" in lang_attr:
                    return lang_attr.split("_")[-1].upper()
    except Exception:
        pass

    # 4) tld mapping for common TLDs
    try:
        parsed = urlparse(url or "")
        host = (parsed.netloc or "").lower()
        if host:
            # strip port
            host = host.split(":")[0]
            parts = host.split(".")
            if len(parts) > 1:
                tld = parts[-1]
                tld_map = {
                    "us": "US", "uk": "GB", "co": None, "de": "DE", "fr": "FR",
                    "ir": "IR", "ca": "CA", "au": "AU", "nl": "NL", "es": "ES",
                    "it": "IT", "ch": "CH", "se": "SE", "no": "NO", "be": "BE",
                    "dk": "DK", "fi": "FI", "at": "AT", "br": "BR", "in": "IN",
                    "jp": "JP", "kr": "KR"
                }
                if tld in tld_map and tld_map[tld]:
                    return tld_map[tld]
    except Exception:
        pass

    # 5) trafilatura site info (best-effort)
    try:
        sitename = trafi.get("sitename") if isinstance(trafi, dict) else None
        if sitename and isinstance(sitename, str) and len(sitename) >= 2:
            # nothing robust here — skip
            pass
    except Exception:
        pass

    return None


def _format_e164(candidate: str, region_hint: Optional[str]) -> Optional[str]:
    """
    Try to parse candidate phone string into E.164 with phonenumbers.
    Returns E.164 string on success, otherwise None.
    """
    if not candidate or not candidate.strip():
        return None
    raw = candidate.strip()
    # Remove common surrounding text
    raw = re.sub(r"(tel:|phone:|\s+ext[:\.]?\s*\d+)$", "", raw, flags=re.I).strip()
    # If string contains known anchors like "Call us: +49 30 ..." keep them
    try:
        if raw.startswith("+"):
            num = phonenumbers.parse(raw, None)
        else:
            # try region hint if provided
            if region_hint:
                num = phonenumbers.parse(raw, region_hint)
            else:
                # fallback: try 'US' parse attempt
                try:
                    num = phonenumbers.parse(raw, "US")
                except NumberParseException:
                    num = phonenumbers.parse(raw, None)
        if phonenumbers.is_valid_number(num):
            return phonenumbers.format_number(num, PhoneNumberFormat.E164)
        # if not valid but possible, still attempt E164 of the country code if available
        if phonenumbers.is_possible_number(num):
            try:
                return phonenumbers.format_number(num, PhoneNumberFormat.E164)
            except Exception:
                return None
    except NumberParseException:
        return None
    except Exception:
        return None
    return None


def _extract_addresses_from_jsonld(html: str) -> List[Dict[str, Any]]:
    """
    Extract structured addresses from JSON-LD (schema.org PostalAddress or address fields).
    Returns list of dicts with fields:
      streetAddress, addressLocality, addressRegion, postalCode, addressCountry, raw
    """
    out: List[Dict[str, Any]] = []
    try:
        for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or "", flags=re.I | re.S):
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Direct PostalAddress object
                if item.get("@type") and str(item.get("@type")).lower() in ("postaladdress", "address"):
                    addr = {
                        "streetAddress": item.get("streetAddress"),
                        "addressLocality": item.get("addressLocality"),
                        "addressRegion": item.get("addressRegion"),
                        "postalCode": item.get("postalCode"),
                        "addressCountry": item.get("addressCountry"),
                        "raw": _normalize_whitespace(" ".join(filter(None, [
                            item.get("streetAddress") or "",
                            item.get("addressLocality") or "",
                            item.get("addressRegion") or "",
                            item.get("postalCode") or "",
                            item.get("addressCountry") or ""
                        ])))
                    }
                    out.append({k: v for k, v in addr.items() if v})
                # Nested address fields (e.g. in Organization, LocalBusiness)
                for k, v in item.items():
                    if k.lower() == "address" and isinstance(v, dict):
                        addr = {
                            "streetAddress": v.get("streetAddress"),
                            "addressLocality": v.get("addressLocality"),
                            "addressRegion": v.get("addressRegion"),
                            "postalCode": v.get("postalCode"),
                            "addressCountry": v.get("addressCountry"),
                            "raw": _normalize_whitespace(" ".join(filter(None, [
                                v.get("streetAddress") or "",
                                v.get("addressLocality") or "",
                                v.get("addressRegion") or "",
                                v.get("postalCode") or "",
                                v.get("addressCountry") or ""
                            ])))
                        }
                        out.append({k: v for k, v in addr.items() if v})
    except Exception:
        pass
    return out


def _extract_addresses_from_tags_and_text(html: str) -> List[Dict[str, Any]]:
    """
    Look for <address> tags and also do a heuristic scan for address-like lines.
    Heuristic lines: lines containing street words + digits or postal code patterns.
    Returns list of {streetAddress..., raw}
    """
    out: List[Dict[str, Any]] = []
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        soup = None

    # 1) <address> tags
    if soup:
        for addr_tag in soup.find_all("address"):
            txt = addr_tag.get_text(separator=" ", strip=True)
            if txt:
                parts = [p.strip() for p in re.split(r"[\n,;]+", txt) if p.strip()]
                # attempt simple structuring: last part might be "City, Region postal"
                struct = {"raw": txt}
                if parts:
                    # heuristics: find postal code-like token
                    postal = None
                    for p in parts[::-1]:
                        if re.search(r"\d{3,6}", p):
                            postal = p
                            break
                    struct["streetAddress"] = parts[0] if len(parts) >= 1 else None
                    if len(parts) >= 2:
                        struct["addressLocality"] = parts[1]
                    if postal:
                        struct["postalCode"] = postal
                out.append({k: v for k, v in struct.items() if v})
    # 2) Heuristic scan in visible text: look for lines with street keywords or postal code patterns
    text_blocks = []
    try:
        if soup:
            # gather sensible text blocks like paragraphs, divs, lis
            for tag in soup.find_all(["p", "div", "li"]):
                t = tag.get_text(separator=" ", strip=True)
                if t and len(t) < 400 and (len(t.split()) >= 3):
                    text_blocks.append(t)
        else:
            # fallback to raw html stripped
            text_blocks = re.split(r"[\n\r]+", re.sub(r"<[^>]+>", "\n", html or ""))
    except Exception:
        text_blocks = []

    # heuristics for address-like text
    address_keywords = r"\b(street|st\.|road|rd\.|avenue|ave\.|boulevard|blvd|lane|ln\.|way|platz|straße|strasse|خیابان|No\.|No:|suite|apt|apartment)\b"
    postal_pattern = r"\b\d{3,6}\b"
    for block in text_blocks:
        if re.search(address_keywords, block, flags=re.I) or re.search(postal_pattern, block):
            # further filter out phone-like text: reject if too many digits relative to letters
            digits = len(re.findall(r"\d", block))
            letters = len(re.findall(r"[A-Za-z\u00C0-\u017F\u0600-\u06FF]", block))
            if digits > letters * 2 and digits > 6:
                # likely a phone cluster, skip
                continue
            # candidate
            raw = _normalize_whitespace(block)
            # try to split into street, city etc by commas
            parts = [p.strip() for p in re.split(r"[,\n;]+", raw) if p.strip()]
            struct = {"raw": raw}
            if parts:
                struct["streetAddress"] = parts[0]
                if len(parts) >= 2:
                    struct["addressLocality"] = parts[1]
                # find postal code
                for p in parts:
                    m = re.search(r"(\b\d{3,6}\b)", p)
                    if m:
                        struct["postalCode"] = m.group(1)
                        break
            out.append({k: v for k, v in struct.items() if v})

    # dedupe by raw
    seen_raw = set()
    uniq = []
    for a in out:
        r = a.get("raw") or ""
        if r and r not in seen_raw:
            seen_raw.add(r)
            uniq.append(a)
    return uniq


def _extract_social_media(html: str) -> Dict[str, List[str]]:
    """
    Extract social media profile URLs from HTML; prefer href attributes and absolute URLs.
    Returns dict platform -> [urls]
    """
    social_patterns = {
        "facebook": r"https?://(?:www\.)?facebook\.com/[^\s\"'>]+",
        "twitter": r"https?://(?:www\.)?twitter\.com/[^\s\"'>]+",
        "instagram": r"https?://(?:www\.)?instagram\.com/[^\s\"'>]+",
        "linkedin": r"https?://(?:www\.)?linkedin\.com/[^\s\"'>]+",
        "youtube": r"https?://(?:www\.)?youtube\.com/[^\s\"'>]+",
        "telegram": r"https?://(?:t\.me|telegram\.me)/[^\s\"'>]+",
        "whatsapp": r"https?://wa\.me/[^\s\"'>]+",
        "tiktok": r"https?://(?:www\.)?tiktok\.com/[^\s\"'>]+",
        "xing": r"https?://(?:www\.)?xing\.com/[^\s\"'>]+",
        "pinterest": r"https?://(?:www\.)?pinterest\.[^\s\"'>]+",
    }
    found: Dict[str, List[str]] = {}
    try:
        # use BeautifulSoup to prefer hrefs
        soup = BeautifulSoup(html or "", "lxml")
        for a in soup.find_all("a", href=True):
            href = a.get("href") or ""
            for platform, patt in social_patterns.items():
                if re.search(patt, href, flags=re.I):
                    found.setdefault(platform, []).append(href.strip())
        # fallback to regex on raw html for any missed
        raw = html or ""
        for platform, patt in social_patterns.items():
            matches = re.findall(patt, raw, flags=re.I)
            if matches:
                existing = found.get(platform, [])
                for m in matches:
                    if m not in existing:
                        existing.append(m)
                if existing:
                    found[platform] = sorted(set(existing))
    except Exception:
        # final fallback to regex only
        raw = html or ""
        for platform, patt in social_patterns.items():
            matches = re.findall(patt, raw, flags=re.I)
            if matches:
                found[platform] = sorted(set(matches))
    return {k: v for k, v in found.items() if v}


def _extract_contact_info(html: str, text: str, url: str, trafi: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract contact info from the HTML blob and visible text.
    Returns a dict with keys:
      - emails: [str]            (optional)
      - phones: [str]            (optional)  (normalized to E.164 where possible)
      - faxes: [str]             (optional)  (normalized to E.164 where possible)
      - social_media: {platform: [str]}  (optional)
      - addresses: [ {streetAddress, addressLocality, addressRegion, postalCode, addressCountry, raw} ] or [{ "raw": "..."}]
    Returns None if nothing found.
    """
    contact_info: Dict[str, Any] = {}

    # --- Emails ---
    try:
        emails = set(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", html))
        # also scan mailto:
        try:
            soup = BeautifulSoup(html or "", "lxml")
            for a in soup.find_all("a", href=True):
                href = a.get("href") or ""
                if href.lower().startswith("mailto:"):
                    addr = href.split(":", 1)[1].split("?")[0].strip()
                    if addr:
                        emails.add(addr)
        except Exception:
            pass
        if emails:
            contact_info["emails"] = sorted(emails)
    except Exception:
        pass

    # --- Social media ---
    try:
        social_found = _extract_social_media(html)
        if social_found:
            contact_info["social_media"] = social_found
    except Exception:
        pass

    # --- Phones & Faxes (gather candidates from multiple sources) ---
    phone_candidates = set()
    try:
        # 1) tel: links
        try:
            soup = BeautifulSoup(html or "", "lxml")
            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if href.lower().startswith("tel:"):
                    phone_candidates.add(href.split(":", 1)[1])
        except Exception:
            pass

        # 2) JSON-LD telephone fields
        for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or "", flags=re.I | re.S):
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    # common keys: telephone, faxNumber, contactPoint
                    tel = item.get("telephone") or item.get("phone") or item.get("contactTelephone")
                    if isinstance(tel, str) and tel.strip():
                        phone_candidates.add(tel.strip())
                    fax = item.get("faxNumber")
                    if isinstance(fax, str) and fax.strip():
                        phone_candidates.add(fax.strip())
                    # contactPoint array/dict
                    cp = item.get("contactPoint")
                    if isinstance(cp, list):
                        for c in cp:
                            if isinstance(c, dict):
                                t = c.get("telephone") or c.get("phone")
                                f = c.get("faxNumber")
                                if isinstance(t, str) and t.strip():
                                    phone_candidates.add(t.strip())
                                if isinstance(f, str) and f.strip():
                                    phone_candidates.add(f.strip())
                    elif isinstance(cp, dict):
                        t = cp.get("telephone") or cp.get("phone")
                        f = cp.get("faxNumber")
                        if isinstance(t, str) and t.strip():
                            phone_candidates.add(t.strip())
                        if isinstance(f, str) and f.strip():
                            phone_candidates.add(f.strip())
        # 3) plain-text regex in HTML and visible text
        phone_candidates.update(re.findall(r"(?:\+?\d[\d\-\s().]{6,}\d)", html))
        phone_candidates.update(re.findall(r"(?:\+?\d[\d\-\s().]{6,}\d)", text))
        # 4) surrounding 'fax' heuristics captured separately below
    except Exception:
        pass

    # 4) fax patterns (look for 'fax' nearby)
    fax_candidates = set()
    try:
        for match in re.finditer(r"(fax[:\s]*)([\+\d][\d\-\s().]{6,}\d)", html, flags=re.I):
            raw = match.group(2)
            fax_candidates.add(raw.strip())
    except Exception:
        pass

    # Normalize phones and separate fax if labeled or matched above
    phones_out: List[str] = []
    faxes_out: List[str] = []

    region_hint = _guess_country_from_html_url(html, url, trafi)  # e.g. 'US', 'DE', or None

    # If region_hint is like 'GB' phonenumbers expects 'GB' (OK). phonenumbers.parse uses region as ISO 3166-1 alpha-2
    for cand in sorted(phone_candidates):
        formatted = _format_e164(cand, region_hint)
        if formatted:
            phones_out.append(formatted)
        else:
            # fallback: include cleaned digits if no E.164 possible
            digits = re.sub(r"[^\d+]", "", cand)
            if digits:
                phones_out.append(digits)

    for cand in sorted(fax_candidates):
        formatted = _format_e164(cand, region_hint)
        if formatted:
            faxes_out.append(formatted)
        else:
            digits = re.sub(r"[^\d+]", "", cand)
            if digits:
                faxes_out.append(digits)

    # Deduplicate
    if phones_out:
        contact_info["phones"] = sorted(list(dict.fromkeys(phones_out)))
    if faxes_out:
        # If a fax candidate appears in phones, prefer it in faxes too but keep distinct lists
        contact_info["faxes"] = sorted(list(dict.fromkeys(faxes_out)))

    # --- Addresses ---
    addresses: List[Dict[str, Any]] = []
    try:
        # JSON-LD structured addresses
        addresses.extend(_extract_addresses_from_jsonld(html))
    except Exception:
        pass

    try:
        # <address> tags and heuristics
        addresses.extend(_extract_addresses_from_tags_and_text(html))
    except Exception:
        pass

    # Deduplicate addresses by raw field
    if addresses:
        seen_raw = set()
        uniq_addr = []
        for a in addresses:
            r = a.get("raw") or ""
            r_norm = _normalize_whitespace(r).lower() if r else ""
            if r_norm and r_norm not in seen_raw:
                seen_raw.add(r_norm)
                # ensure keys present as requested
                cleaned = {}
                for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"):
                    if a.get(key):
                        cleaned[key] = a.get(key)
                cleaned["raw"] = a.get("raw")
                uniq_addr.append(cleaned)
        if uniq_addr:
            contact_info["addresses"] = uniq_addr

    if not contact_info:
        return None
    return contact_info


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

    # contact info (now enhanced)
    try:
        contact_us = _extract_contact_info(html, text_content, str(payload.url), data)
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
