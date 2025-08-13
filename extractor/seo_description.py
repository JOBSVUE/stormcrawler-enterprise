import re
from typing import Optional, Tuple
from html import unescape

_SUMY_AVAILABLE = False
_TRANSFORMERS_AVAILABLE = False
_summarizer = None
_hf_summarizer = None

# Try Sumy
try:
    from sumy.parsers.plaintext import PlaintextParser  # type: ignore
    from sumy.nlp.tokenizers import Tokenizer  # type: ignore
    from sumy.summarizers.lsa import LsaSummarizer  # type: ignore
    _SUMY_AVAILABLE = True
except Exception:
    _SUMY_AVAILABLE = False

# Try Transformers summarizer (bart-large-cnn)
try:
    from transformers import pipeline  # type: ignore
    _TRANSFORMERS_AVAILABLE = True
except Exception:
    _TRANSFORMERS_AVAILABLE = False


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


def extract_meta_description(html: str, max_chars: int = 160) -> Optional[str]:
    """
    Extract description from meta tags: name=description, property=og:description, name=twitter:description.
    Regex-based to avoid extra deps; decodes entities; returns clamped string.
    """
    if not html:
        return None
    # Find all meta tags
    for meta in re.findall(r"<meta\b[^>]*>", html, flags=re.I):
        # Pull attributes
        attrs = dict(re.findall(r'(\w[\w:-]*)\s*=\s*["\']([^"\']+)["\']', meta, flags=re.I))
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        if name in ("description", "og:description", "twitter:description"):
            content = attrs.get("content") or ""
            content = _normalize_whitespace(unescape(content))
            if content:
                return _clamp(content, max_chars)
    return None


def _ensure_sumy():
    global _summarizer
    if _summarizer is None and _SUMY_AVAILABLE:
        _summarizer = LsaSummarizer()
    return _summarizer


def _ensure_hf():
    global _hf_summarizer
    if _hf_summarizer is None and _TRANSFORMERS_AVAILABLE:
        # Lazy load; callers should expect first call to be slow if model is not cached
        _hf_summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
    return _hf_summarizer


def _summarize_sumy(text: str, max_chars: int) -> Optional[str]:
    try:
        summarizer = _ensure_sumy()
        if not summarizer:
            return None
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        # Take small number of sentences and clamp
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
        # Approximate target length (tokens != chars; keep it small)
        result = summarizer(text[:4000], max_length=80, min_length=25, do_sample=False)
        summary = _normalize_whitespace(result[0]["summary_text"])
        return _clamp(summary or text, max_chars)
    except Exception:
        return None


def _simple_sentences(text: str) -> list:
    # Very naive sentence split
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
