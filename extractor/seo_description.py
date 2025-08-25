# seo_description.py
"""
SEO description & keyword helpers for the extractor service.

Provides:
 - extract_meta_description(html, max_chars=160) -> Optional[str]
 - generate_description(text, mode="c", max_chars=160) -> (Optional[str], source_str)
 - generate_keywords_with_hf(text, max_keywords=12) -> List[str]

This implementation is strict: the summarization dependencies are mandatory
and will raise ImportError at module import time if not present. BeautifulSoup
and lxml are also mandatory.
"""

import re
import os
from typing import Optional, Tuple, List
from html import unescape
import logging

logger = logging.getLogger("seo_description")

# ---- Summarization dependencies (now mandatory) ----
try:
    from sumy.parsers.plaintext import PlaintextParser  # type: ignore
    from sumy.nlp.tokenizers import Tokenizer  # type: ignore
    from sumy.summarizers.lsa import LsaSummarizer  # type: ignore
except Exception as e:
    raise ImportError(
        "Sumy is required for SEO summarization. Install with: pip install sumy"
    ) from e

try:
    from transformers import pipeline  # type: ignore
except Exception as e:
    raise ImportError(
        "transformers is required for HF-based summarization and keyword extraction. "
        "Install with: pip install transformers"
    ) from e

# ---- Mandatory HTML parsing (BeautifulSoup + lxml) ----
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception as e:
    raise ImportError(
        "BeautifulSoup4 is required. Install with: pip install beautifulsoup4 lxml"
    ) from e

try:
    import lxml  # type: ignore
except Exception as e:
    raise ImportError("lxml is required. Install with: pip install lxml") from e


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clamp(text: str, max_chars: int) -> str:
    """
    Normalize whitespace and clamp to max_chars, preferring to cut at sentence boundary or space.
    Adds an ellipsis char if clipped.
    """
    text = _normalize_whitespace(text)
    if len(text) <= max_chars:
        return text
    # Prefer cut on sentence end or space
    cut = text.rfind(". ", 0, max_chars)
    if cut == -1:
        cut = text.rfind(" ", 0, max_chars)
    if cut == -1:
        cut = max_chars
    return text[:cut].rstrip() + "…"


def extract_meta_description(html: str, max_chars: int = 160) -> Optional[str]:
    """
    Meta description extraction using BeautifulSoup + lxml.
    Returns normalized description string (UNCLAMPED) or None.

    Notes:
      - This function normalizes and unescapes content but DOES NOT clamp to max_chars.
      - The calling code controls clamping behavior.
    """
    if not html:
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return None

    candidates = [
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
        {"itemprop": "description"},
    ]
    for attrs in candidates:
        tag = soup.find("meta", attrs=attrs)
        if tag:
            content = tag.get("content") or tag.get("value") or ""
            content = _normalize_whitespace(unescape(content))
            if content:
                # DO NOT clamp here — return normalized raw
                return content

    # Try JSON-LD description field if present (schema.org)
    try:
        import json  # local import
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.get_text() or ""
            try:
                data = json.loads(raw)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    desc = item.get("description") or item.get("desc")
                    if isinstance(desc, str) and desc.strip():
                        return _normalize_whitespace(unescape(desc))
    except Exception:
        # swallow JSON-LD parsing issues
        pass

    return None


# ---------------- Summarization helpers (Sumy & Transformers) ----------------
_summarizer = None
_hf_summarizer = None


def _ensure_sumy():
    global _summarizer
    if _summarizer is None:
        try:
            _summarizer = LsaSummarizer()  # type: ignore[name-defined]
        except Exception:
            logger.exception("Failed to instantiate Sumy summarizer")
            _summarizer = None
            raise
    return _summarizer


def _ensure_hf():
    global _hf_summarizer
    if _hf_summarizer is None:
        model_name = os.getenv("SEO_SUMMARY_MODEL", "facebook/bart-large-cnn")
        try:
            _hf_summarizer = pipeline("summarization", model=model_name)  # type: ignore[name-defined]
        except Exception:
            logger.exception("Failed to create HF summarization pipeline for model %s", model_name)
            _hf_summarizer = None
            raise
    return _hf_summarizer


def _summarize_sumy(text: str, max_chars: int) -> Optional[str]:
    try:
        summarizer = _ensure_sumy()
        if not summarizer:
            return None
        parser = PlaintextParser.from_string(text, Tokenizer("english"))  # type: ignore[name-defined]
        # choose a small number of sentences; LSA returns sentence objects
        sentences = list(summarizer(parser.document, 3))
        joined = _normalize_whitespace(" ".join(str(s) for s in sentences))
        return _clamp(joined or text, max_chars)
    except Exception:
        logger.exception("Sumy summarization failed")
        return None


def _summarize_hf(text: str, max_chars: int) -> Optional[str]:
    try:
        summarizer = _ensure_hf()
        if not summarizer:
            return None
        # Truncate input to 4000 chars per spec
        result = summarizer(text[:4000], max_length=80, min_length=25, do_sample=False)
        if not result:
            return None
        summary = _normalize_whitespace(result[0].get("summary_text") or result[0].get("text") or "")
        return _clamp(summary or text, max_chars)
    except Exception:
        logger.exception("HF summarization failed")
        return None


def generate_description(text: str, mode: str = "c", max_chars: int = 160) -> Tuple[Optional[str], str]:
    """
    Generate a description within max_chars.
    Returns (description, source) where source is:
      - 'generated:transformers'
      - 'generated:sumy'
      - 'generated:none' (if neither summarizer produced output)

    Mode behavior:
      - 'c' (default): try Transformers first, then Sumy.
      - 'b': prefer Sumy only.
      - other values -> generated:none
    """
    if not text:
        return None, "generated:none"

    mode = (mode or "c").lower()
    if mode == "c":
        # Prefer transformers, then sumy
        # both transformers and sumy are mandatory at import time; attempt HF first
        summary = _summarize_hf(text, max_chars)
        if summary:
            return summary, "generated:transformers"
        summary = _summarize_sumy(text, max_chars)
        if summary:
            return summary, "generated:sumy"
        return None, "generated:none"

    if mode == "b":
        summary = _summarize_sumy(text, max_chars)
        if summary:
            return summary, "generated:sumy"
        return None, "generated:none"

    return None, "generated:none"


# ---------------- LLM-based keyword generation helpers ----------------
_KEYWORD_MODEL = os.getenv("KEYWORD_MODEL", "google/flan-t5-large")
_keyword_pipeline = None


def _ensure_keyword_pipeline():
    """
    Create a text2text-generation HF pipeline for keyword extraction.
    This will raise if transformers/model cannot be loaded.
    """
    global _keyword_pipeline
    if _keyword_pipeline is None:
        try:
            from transformers import pipeline as _hf_pipeline  # local import
            _keyword_pipeline = _hf_pipeline("text2text-generation", model=_KEYWORD_MODEL)
        except Exception:
            logger.exception("Failed to create keyword pipeline for model %s", _KEYWORD_MODEL)
            _keyword_pipeline = None
            raise
    return _keyword_pipeline


def generate_keywords_with_hf(text: str, max_keywords: int = 12) -> List[str]:
    """
    Use an instruction-tuned text2text model to extract keywords/keyphrases.
    Returns a list of normalized keywords (lowercased, stripped), up to max_keywords.
    Will return an empty list on failure, but the pipeline creation itself will raise on import-time/model errors.
    """
    if not text:
        return []

    pipe = _ensure_keyword_pipeline()
    if not pipe:
        return []

    prompt = (
        f"Extract up to {max_keywords} concise keywords or keyphrases from the following text. "
        "Return them as a single comma-separated list, no numbering, no extra commentary.\n\n"
        f"Text: {text[:8000]}"
    )

    try:
        out = pipe(prompt, max_length=128, do_sample=False)
    except Exception:
        logger.exception("Keyword pipeline generation failed")
        return []

    if not out:
        return []

    first = out[0]
    raw = first.get("generated_text") or first.get("text") or str(first)
    # Split and normalize
    parts = [p.strip().lower() for p in re.split(r"[,\n;]+", raw) if p.strip()]
    parts = [re.sub(r"[^\w\s\-]", "", p) for p in parts]  # remove punctuation
    parts = [p for p in parts if 2 <= len(p) <= 100]
    seen = set()
    uniq = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
        if len(uniq) >= max_keywords:
            break
    return uniq
