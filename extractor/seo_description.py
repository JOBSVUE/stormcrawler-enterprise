import re
from typing import Optional, Tuple
from html import unescape

# ---- Mandatory summarization dependencies ----
# These imports are now strict: if they are missing, import will fail and the service
# will not start. This enforces that transformers and sumy are available.
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer

from transformers import pipeline

_SUMY_AVAILABLE = True
_TRANSFORMERS_AVAILABLE = True
_summarizer = None
_hf_summarizer = None

# Optional HTML parser (BeautifulSoup) — falls back to regex when not available.
_BS4_AVAILABLE = False
_LXML_AVAILABLE = False
try:
    from bs4 import BeautifulSoup  # type: ignore
    _BS4_AVAILABLE = True
    try:
        import lxml  # type: ignore
        _LXML_AVAILABLE = True
    except Exception:
        _LXML_AVAILABLE = False
except Exception:
    _BS4_AVAILABLE = False


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clamp(text: str, max_chars: int) -> str:
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


def _extract_meta_description_regex(html: str, max_chars: int = 160) -> Optional[str]:
    """
    Regex-based meta extraction fallback (keeps original behaviour).
    """
    if not html:
        return None
    for meta in re.findall(r"<meta\b[^>]*>", html, flags=re.I):
        attrs = dict(re.findall(r'(\w[\w:-]*)\s*=\s*["\']([^"\']+)["\']', meta, flags=re.I))
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        if name in ("description", "og:description", "twitter:description"):
            content = attrs.get("content") or ""
            content = _normalize_whitespace(unescape(content))
            if content:
                return _clamp(content, max_chars)
    return None


def extract_meta_description(html: str, max_chars: int = 160) -> Optional[str]:
    """
    Extract description from meta tags in a more robust way using BeautifulSoup when available.

    - If BeautifulSoup is available, parse the HTML and look through all <meta> tags for
      name/property/itemprop values of description / og:description / twitter:description (case-insensitive).
    - If BeautifulSoup isn't available, fall back to the original regex-based implementation.

    Returned string is unescaped, whitespace-normalized and clamped to `max_chars`.
    """
    if not html:
        return None

    if _BS4_AVAILABLE:
        parser = "lxml" if _LXML_AVAILABLE else "html.parser"
        try:
            soup = BeautifulSoup(html, parser)
        except Exception:
            return _extract_meta_description_regex(html, max_chars=max_chars)

        for tag in soup.find_all("meta"):
            try:
                attrs = {k.lower(): v for k, v in (tag.attrs or {}).items()}
            except Exception:
                attrs = {}
            for key in ("name", "property", "itemprop"):
                val = (attrs.get(key) or "").lower()
                if val in ("description", "og:description", "twitter:description", "description:en"):
                    content = attrs.get("content") or attrs.get("value") or ""
                    content = _normalize_whitespace(unescape(content))
                    if content:
                        return _clamp(content, max_chars)
        return None

    # Fallback to regex
    return _extract_meta_description_regex(html, max_chars=max_chars)


def _ensure_sumy():
    global _summarizer
    if _summarizer is None and _SUMY_AVAILABLE:
        _summarizer = LsaSummarizer()
    return _summarizer


def _ensure_hf():
    global _hf_summarizer
    if _hf_summarizer is None and _TRANSFORMERS_AVAILABLE:
        # Lazy-load HF pipeline. If you want to fail at import/startup instead of
        # on first use, instantiate this pipeline at startup (see README / notes).
        _hf_summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
    return _hf_summarizer


def _summarize_sumy(text: str, max_chars: int) -> Optional[str]:
    try:
        summarizer = _ensure_sumy()
        if not summarizer:
            return None
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        sentences = list(summarizer(parser.document, 3))
        joined = _normalize_whitespace(" ".join(str(s) for s in sentences))
        return _clamp(joined or text, max_chars)
    except Exception:
        return None


def _summarize_hf(text: str, max_chars: int) -> Optional[str]:
    try:
        summarizer = _ensure_hf()
        if not summarizer:
            return None
        result = summarizer(text[:4000], max_length=80, min_length=25, do_sample=False)
        summary = _normalize_whitespace(result[0]["summary_text"])
        return _clamp(summary or text, max_chars)
    except Exception:
        return None


def _simple_sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?])\s+", _normalize_whitespace(text))
    return [p for p in parts if p]


def _summarize_simple(text: str, max_chars: int) -> str:
    sentences = _simple_sentences(text)
    if not sentences:
        return _clamp(text, max_chars)
    out = []
    total = 0
    for s in sentences:
        s = _normalize_whitespace(s)
        if not s:
            continue
        if total + len(s) + (1 if total else 0) > max_chars:
            break
        out.append(s)
        total += len(s) + (1 if total else 0)
        if total >= max_chars:
            break
    if not out:
        return _clamp(sentences[0], max_chars)
    return _clamp(" ".join(out), max_chars)


def generate_description(text: str, mode: str = "c", max_chars: int = 160) -> Tuple[Optional[str], str]:
    """
    Generate a description within max_chars.
    Returns (description, source), where source is one of:
    'generated:transformers', 'generated:sumy', 'generated:simple'
    """
    if not text:
        return None, "generated:simple"

    mode = (mode or "c").lower()
    if mode == "c":
        # Prefer transformers, then sumy, fallback to simple
        if _TRANSFORMERS_AVAILABLE:
            summary = _summarize_hf(text, max_chars)
            if summary:
                return summary, "generated:transformers"
        if _SUMY_AVAILABLE:
            summary = _summarize_sumy(text, max_chars)
            if summary:
                return summary, "generated:sumy"
        return _summarize_simple(text, max_chars), "generated:simple"

    if mode == "b":
        return _summarize_simple(text, max_chars), "generated:simple"

    # mode == 'a': first sentence
    sentences = _simple_sentences(text)
    first = sentences[0] if sentences else text
    return _clamp(first, max_chars), "generated:simple"
