from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel, Field
from pwdlib import PasswordHash

import json
import os
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Universal EntQra research providers / retrieval utilities
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen

try:
    import requests
except Exception:
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from tavily import TavilyClient
except Exception:
    TavilyClient = None

try:
    from exa_py import Exa
except Exception:
    Exa = None

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except Exception:
    TfidfVectorizer = None
    cosine_similarity = None

from database.connection import SessionLocal
from database.models import User, Entity, EntityRelationship
from backend.auth import create_access_token

# Keep main.py compatible with both the current auth.py and older local
# versions that only expose create_access_token.
try:
    from backend.auth import verify_access_token as _auth_verify_access_token
except ImportError:
    _auth_verify_access_token = None


def verify_access_token(token: str):
    if _auth_verify_access_token is not None:
        return _auth_verify_access_token(token)
    try:
        import jwt
        import backend.auth as auth_module
        secret = (
            getattr(auth_module, "SECRET_KEY", None)
            or getattr(auth_module, "JWT_SECRET_KEY", None)
            or os.getenv("SECRET_KEY")
            or os.getenv("JWT_SECRET_KEY")
        )
        algorithm = (
            getattr(auth_module, "ALGORITHM", None)
            or getattr(auth_module, "JWT_ALGORITHM", None)
            or "HS256"
        )
        if not secret:
            return jwt.decode(token, options={"verify_signature": False})
        return jwt.decode(token, secret, algorithms=[algorithm])
    except Exception:
        return None


# ==================================================
# FASTAPI APPLICATION
# ==================================================

app = FastAPI(title="ENTORA API")


# ==================================================
# CORS CONFIGURATION
# ==================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


password_hash = PasswordHash.recommended()
security = HTTPBearer()


# ==================================================
# DATABASE DEPENDENCY
# ==================================================

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# ==================================================
# REQUEST MODELS
# ==================================================

class UserCreate(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    password: str | None = Field(
        default=None,
        min_length=8
    )


class EntityCreate(BaseModel):
    name: str
    entity_type: str
    category: str | None = None
    description: str | None = None
    website: str | None = None
    logo_url: str | None = None


class EntityUpdate(BaseModel):
    name: str | None = None
    entity_type: str | None = None
    category: str | None = None
    description: str | None = None
    website: str | None = None
    logo_url: str | None = None


# ==================================================
# ENTITY RELATIONSHIP REQUEST MODEL
# ==================================================

class RelationshipCreate(BaseModel):
    source_entity_id: int
    target_entity_id: int
    relationship_type: str
    description: str | None = None


class IntelligenceSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    max_sources: int = Field(default=10, ge=3, le=10)


# ==================================================
# ENTQRA WEB RESEARCH + INTELLIGENCE ENGINE
# ==================================================

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict


# --------------------------------------------------
# Text / URL utilities
# --------------------------------------------------

_BOILERPLATE_PHRASES = {
    "jump to content", "main menu", "main navigation", "skip to content",
    "table of contents", "sign in", "log in", "subscribe", "contact us",
    "privacy policy", "terms of use", "cookie policy", "all rights reserved",
    "read more", "learn more", "see more", "more about", "related topics",
    "share this", "follow us", "newsletter", "search this site", "menu",
}

_NAV_WORDS = {
    "home", "about", "careers", "contact", "press", "news", "support",
    "products", "services", "resources", "login", "sign in", "register",
}


def _clean_text(value: str) -> str:
    value = unescape(value or "")
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _normalise_search_url(url: str) -> str:
    url = _clean_text(url)
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    target = parse_qs(parsed.query).get("uddg", [None])[0]
    if target:
        target = unquote(target)
        if target.startswith("//"):
            target = "https:" + target
        target_parsed = urlparse(target)
        if target_parsed.scheme in {"http", "https"} and target_parsed.netloc:
            return target
    return url


def _source_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().split("@")[-1].split(":", 1)[0]
    return host.removeprefix("www.")


def _domain_label(domain: str) -> str:
    labels = {
        "about.google": "Google",
        "google.com": "Google",
        "blog.google": "Google",
        "microsoft.com": "Microsoft",
        "britannica.com": "Britannica",
        "reuters.com": "Reuters",
        "apnews.com": "AP News",
        "bbc.com": "BBC",
        "bbc.co.uk": "BBC",
        "nasa.gov": "NASA",
        "who.int": "World Health Organization",
        "wikipedia.org": "Wikipedia",
        "en.wikipedia.org": "Wikipedia",
        "nature.com": "Nature",
        "nih.gov": "NIH",
        "sec.gov": "SEC",
        "github.com": "GitHub",
        "apple.com": "Apple",
        "meta.com": "Meta",
        "ibm.com": "IBM",
        "amazon.com": "Amazon",
    }
    if domain in labels:
        return labels[domain]
    parts = [p for p in domain.split(".") if p]
    return parts[-2].replace("-", " ").title() if len(parts) >= 2 else domain.title()


def _source_quality(domain: str, title: str = "") -> tuple[str, int]:
    domain = (domain or "").lower()
    primary_domains = {
        "about.google", "google.com", "blog.google", "microsoft.com", "nasa.gov",
        "who.int", "sec.gov", "nih.gov", "apple.com", "meta.com", "ibm.com",
        "amazon.com", "github.com", "python.org", "openai.com",
    }
    high_quality = {
        "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nature.com",
        "britannica.com", "theguardian.com", "nytimes.com", "wsj.com",
    }
    reference = {"wikipedia.org", "en.wikipedia.org"}
    if domain in primary_domains or domain.endswith((".gov", ".edu")):
        return "primary", 5
    if domain in high_quality:
        return "high", 4
    if domain in reference:
        return "reference", 3
    if any(x in title.lower() for x in ("official", "documentation", "research", "annual report")):
        return "specialist", 3
    return "general", 2


def _query_terms(query: str) -> list[str]:
    stop_words = {
        "what", "who", "when", "where", "why", "how", "is", "are", "was", "were",
        "the", "a", "an", "of", "to", "for", "in", "on", "and", "or", "with",
        "about", "tell", "me", "does", "do", "can", "could", "would", "should",
        "latest", "current", "information", "relationship", "between", "related",
        "regarding", "explain", "describe", "give", "overview", "history",
    }
    raw = re.findall(r"[A-Za-z0-9][A-Za-z0-9&.'-]{1,}", query.lower())
    return [t.strip(".'-") for t in raw if t.strip(".'-") not in stop_words]


def _infer_subject(query: str) -> str:
    q = _clean_text(query)
    q = re.sub(r"^(please\s+)?(tell me|can you tell me|explain|describe)\s+(about\s+)?", "", q, flags=re.I)
    q = re.sub(r"^(what is|what are|who is|who are|where is|where are|when was|when did|how does|how do|how is)\s+", "", q, flags=re.I)
    q = re.sub(r"\?+$", "", q).strip(" .")
    return q or _clean_text(query)


def _infer_entity_type(subject: str, sources: list[dict], raw_query: str = "") -> str:
    s = subject.lower()
    rq = raw_query.lower()
    if re.match(r"^\s*(who is|who are|biography of|profile of)\b", rq) or any(x in rq for x in ("biography", "footballer", "football player", "cricketer", "actor", "actress", "singer", "scientist", "politician")):
        return "person"
    if re.search(r"\b(who|person|player|actor|singer|scientist|founder|ceo)\b", s):
        return "person"
    if any(x in s for x in ("python", "javascript", "java", "c++", "programming language", "framework")):
        return "technology"
    if any(x in s for x in ("company", "inc", "corp", "corporation", "google", "microsoft", "apple", "amazon", "meta")):
        return "company"
    title_text = " ".join(x.get("title", "") for x in sources[:6]).lower()
    if any(x in title_text for x in ("company", "corporation", "inc.", "ceo")):
        return "company"
    if any(x in title_text for x in ("biography", "footballer", "player", "actor", "singer")):
        return "person"
    return "topic"


def _sentence_key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()


def _is_clean_fact(sentence: str) -> bool:
    s = _clean_text(sentence)
    low = s.lower()
    if len(s) < 45 or len(s) > 650:
        return False
    if any(p in low for p in _BOILERPLATE_PHRASES):
        return False
    if low.count("|") >= 2 or low.count(" > ") >= 2:
        return False
    if low.startswith(tuple(_NAV_WORDS)) and len(s.split()) < 12:
        return False
    # Reject navigation dumps / menu strings with too many short fragments.
    words = s.split()
    if len(words) >= 14 and sum(1 for w in words if len(w) <= 2) / len(words) > 0.35:
        return False
    return True


def _split_sentences(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])", text)
    return [p.strip(" -•") for p in parts if _is_clean_fact(p.strip(" -•"))]


# --------------------------------------------------
# Search result parsing
# --------------------------------------------------

class _SearchResultParser(HTMLParser):
    """Tolerant DuckDuckGo HTML parser; supports both anchor and div snippets."""
    def __init__(self):
        super().__init__()
        self.results = []
        self.current = None
        self.capture = None
        self.buffer = []
        self.capture_tag = None
        self.capture_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "") or ""
        cls = set(classes.split())
        if tag == "a" and "result__a" in cls:
            self._finish_current()
            self.current = {"title": "", "url": attrs.get("href", ""), "snippet": ""}
            self.capture = "title"
            self.capture_tag = tag
            self.capture_depth = 1
            self.buffer = []
            return
        if self.current and any(c.startswith("result__snippet") for c in cls):
            self.capture = "snippet"
            self.capture_tag = tag
            self.capture_depth = 1
            self.buffer = []
            return
        if self.capture:
            self.capture_depth += 1

    def handle_data(self, data):
        if self.current and self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if not self.capture:
            return
        self.capture_depth -= 1
        if self.capture_depth > 0:
            return
        value = _clean_text(" ".join(self.buffer))
        if self.current:
            self.current[self.capture] = value
        if self.capture == "snippet":
            self._finish_current()
        else:
            self.capture = None
            self.buffer = []

    def _finish_current(self):
        if self.current and self.current.get("title") and self.current.get("url"):
            self.results.append(self.current)
        self.current = None
        self.capture = None
        self.capture_tag = None
        self.capture_depth = 0
        self.buffer = []


def _rank_source(source: dict, query: str) -> float:
    terms = _query_terms(query)
    title = source.get("title", "").lower()
    snippet = source.get("snippet", "").lower()
    quality, qw = _source_quality(source.get("domain", ""), source.get("title", ""))
    score = qw * 10
    score += sum(1 for t in terms if t in title) * 8
    score += sum(1 for t in terms if t in snippet) * 2
    if query.lower() in title + " " + snippet:
        score += 10
    if quality == "primary":
        score += 5
    return float(score)


def _rank_sources(query: str, sources: list[dict]) -> list[dict]:
    ranked = []
    for src in sources:
        item = dict(src)
        item["relevance_score"] = round(_rank_source(item, query), 2)
        item["quality"], item["quality_score"] = _source_quality(item.get("domain", ""), item.get("title", ""))
        item["source_name"] = _domain_label(item.get("domain", ""))
        ranked.append(item)
    ranked.sort(key=lambda x: (-x["relevance_score"], -x["quality_score"], x.get("source_name", "")))
    return ranked


def _raw_ddg_search(query: str, limit: int = 5) -> list[dict]:
    search_url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    request = Request(
        search_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Web search provider unavailable: {exc}") from exc

    parser = _SearchResultParser()
    parser.feed(html)
    results = []
    seen = set()
    for raw in parser.results:
        url = _normalise_search_url(raw.get("url", ""))
        title = _clean_text(raw.get("title", ""))
        snippet = _clean_text(raw.get("snippet", ""))
        parsed = urlparse(url)
        if not title or not url or not snippet or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        domain = _source_domain(url)
        if not domain or domain == "duckduckgo.com":
            continue
        key = url.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        results.append({"title": title, "url": url, "snippet": snippet, "domain": domain})
        if len(results) >= limit:
            break
    return results


def _wikipedia_fallback_search(subject: str, limit: int = 3) -> list[dict]:
    """Small dependency-free fallback so a transient search-provider failure does not blank the dashboard."""
    api = (
        "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&utf8=1&origin=*"
        "&srlimit=" + str(limit) + "&srsearch=" + quote_plus(subject)
    )
    request = Request(api, headers={"User-Agent": "EntQra/1.0 research client"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception:
        return []
    results = []
    for row in payload.get("query", {}).get("search", []):
        title = _clean_text(row.get("title", ""))
        snippet = re.sub(r"<[^>]+>", " ", row.get("snippet", ""))
        snippet = _clean_text(snippet)
        if not title or not snippet:
            continue
        results.append({
            "title": title,
            "url": "https://en.wikipedia.org/wiki/" + quote_plus(title.replace(" ", "_")),
            "snippet": snippet,
            "domain": "wikipedia.org",
            "search_query": subject,
            "search_focus": "direct",
        })
    return results


def _search_plan(query: str, subject: str, entity_type: str) -> list[tuple[str, str]]:
    base = f'"{subject}"' if len(subject.split()) <= 8 else subject
    plan = [(query, "direct")]
    if entity_type == "person":
        plan += [
            (f"{base} biography early life career", "background"),
            (f"{base} career achievements statistics", "career"),
            (f"{base} clubs teams awards", "achievements"),
            (f"{base} latest news major events", "developments"),
            (f"{base} official profile", "official"),
        ]
    elif entity_type == "technology":
        plan += [
            (f"{base} history development", "history"),
            (f"{base} features how it works documentation", "technology"),
            (f"{base} ecosystem applications", "applications"),
            (f"{base} versions releases development", "developments"),
            (f"{base} official documentation", "official"),
        ]
    elif entity_type == "company":
        plan += [
            (f"{base} company overview founders history", "overview"),
            (f"{base} products services businesses", "products"),
            (f"{base} leadership CEO founders executives", "people"),
            (f"{base} technology infrastructure operations", "technology"),
            (f"{base} business market competitors annual report", "market"),
            (f"{base} acquisitions launches major developments", "developments"),
        ]
    else:
        plan += [
            (f"{base} overview background history", "overview"),
            (f"{base} how it works features applications", "technology"),
            (f"{base} important facts developments", "developments"),
            (f"{base} official information", "official"),
        ]
    return plan


def _web_search(query: str, max_sources: int = 6) -> list[dict]:
    subject = _infer_subject(query)
    entity_type = _infer_entity_type(subject, [], query)
    plan = _search_plan(query, subject, entity_type)
    per_query = max(2, min(4, max_sources // 2 + 1))
    collected = []
    errors = []

    # Parallel requests make the multi-angle research pipeline practical.
    with ThreadPoolExecutor(max_workers=min(6, len(plan))) as executor:
        futures = {executor.submit(_raw_ddg_search, q, per_query): (q, focus) for q, focus in plan}
        for future in as_completed(futures):
            q, focus = futures[future]
            try:
                for item in future.result():
                    item["search_query"] = q
                    item["search_focus"] = focus
                    collected.append(item)
            except Exception as exc:
                errors.append(str(exc))

    if not collected:
        collected = _wikipedia_fallback_search(subject, limit=min(4, max_sources))
        for item in collected:
            item.setdefault("search_focus", "direct")
        if not collected:
            detail = errors[0] if errors else "No relevant web sources were found."
            raise RuntimeError(detail)
    elif len(collected) < max_sources:
        # Add one neutral reference result when focused searches return too few
        # usable sources. This improves resilience without replacing stronger sources.
        for item in _wikipedia_fallback_search(subject, limit=2):
            if not any(item["url"].rstrip("/") == x["url"].rstrip("/") for x in collected):
                collected.append(item)
                if len(collected) >= max_sources:
                    break

    # Dedupe by canonical URL, retaining the strongest focus metadata.
    by_url = {}
    for item in collected:
        key = item["url"].split("#", 1)[0].rstrip("/")
        if key not in by_url:
            by_url[key] = item
        else:
            old = by_url[key]
            if item.get("quality_score", 0) > old.get("quality_score", 0):
                by_url[key] = item

    ranked = _rank_sources(query, list(by_url.values()))

    # Preserve research breadth: one strong result from each research angle
    # is more useful than six copies of the same general article.
    selected = []
    selected_urls = set()
    selected_focuses = set()
    for item in ranked:
        focus = item.get("search_focus", "direct")
        if focus not in selected_focuses:
            selected.append(item)
            selected_urls.add(item["url"].split("#", 1)[0].rstrip("/"))
            selected_focuses.add(focus)
        if len(selected) >= max_sources:
            break
    if len(selected) < max_sources:
        for item in ranked:
            key = item["url"].split("#", 1)[0].rstrip("/")
            if key in selected_urls:
                continue
            selected.append(item)
            selected_urls.add(key)
            if len(selected) >= max_sources:
                break
    return selected


# --------------------------------------------------
# Page extraction / evidence cleaning
# --------------------------------------------------

class _PageTextParser(HTMLParser):
    """Extract article-like text while excluding navigation and boilerplate."""
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_tags = {"script", "style", "noscript", "svg", "template", "nav", "footer", "header", "form", "aside"}
        self.skip_stack = []
        self.block_tags = {"p", "li", "h1", "h2", "h3", "h4", "h5", "blockquote"}
        self.in_block = False
        self.block_tag = None
        self.block_buffer = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        cls = (attrs.get("class", "") or "").lower()
        ident = (attrs.get("id", "") or "").lower()
        marker = f"{cls} {ident}"
        if self.skip_stack or tag in self.skip_tags or any(x in marker for x in ("nav", "menu", "sidebar", "cookie", "breadcrumb", "footer", "header", "advert", "social", "share")):
            self.skip_stack.append(tag)
            return
        if tag in self.block_tags:
            self.in_block = True
            self.block_tag = tag
            self.block_buffer = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip_stack:
            # Close the most recently opened skipped element.
            if self.skip_stack[-1] == tag:
                self.skip_stack.pop()
            return
        if self.in_block and tag == self.block_tag:
            text = _clean_text(" ".join(self.block_buffer))
            if _is_clean_fact(text):
                self.parts.append(text)
            self.block_buffer = []
            self.in_block = False
            self.block_tag = None

    def handle_data(self, data):
        if not self.skip_stack and self.in_block:
            data = _clean_text(data)
            if data:
                self.block_buffer.append(data)


def _fetch_source_text(url: str, max_chars: int = 24000) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=7) as response:
            content_type = response.headers.get("Content-Type", "")
            if not any(x in content_type.lower() for x in ("text/html", "application/xhtml")):
                return ""
            html = response.read(220000).decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, ValueError):
        return ""
    parser = _PageTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ""
    return _clean_text(" ".join(parser.parts))[:max_chars]


def _enrich_sources(sources: list[dict]) -> list[dict]:
    enriched = [dict(x) for x in sources]
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(enriched)))) as executor:
        futures = {executor.submit(_fetch_source_text, s.get("url", "")): i for i, s in enumerate(enriched)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                page_text = future.result()
            except Exception:
                page_text = ""
            enriched[i]["page_text"] = page_text
            enriched[i]["retrieval"] = "full_page" if page_text else "search_snippet"
    return enriched


def _candidate_sentences(sources: list[dict], query: str) -> list[dict]:
    terms = _query_terms(query)
    candidates = []
    seen = set()
    for idx, source in enumerate(sources):
        texts = []
        if source.get("page_text"):
            texts.append(source["page_text"])
        if source.get("snippet"):
            texts.append(source["snippet"])
        for text in texts:
            for sentence in _split_sentences(text):
                sentence = _clean_text(sentence)
                key = _sentence_key(sentence)
                if key in seen:
                    continue
                low = sentence.lower()
                hits = sum(1 for term in terms if term in low)
                # A sentence may be useful to a focused block even when it
                # does not contain every query term, so do not hard-filter it.
                score = hits * 3 + source.get("quality_score", 2) * 2 + source.get("relevance_score", 0) / 15
                if source.get("retrieval") == "full_page":
                    score += 2
                if len(sentence) <= 420:
                    score += 1
                candidates.append({
                    "text": sentence,
                    "source_index": idx,
                    "source_name": source.get("source_name"),
                    "domain": source.get("domain"),
                    "url": source.get("url"),
                    "quality": source.get("quality"),
                    "score": round(score, 2),
                    "search_focus": source.get("search_focus", "direct"),
                })
                seen.add(key)
    candidates.sort(key=lambda x: -x["score"])
    return candidates


def _extract_evidence(query: str, sources: list[dict], max_items: int = 12) -> list[dict]:
    candidates = _candidate_sentences(sources, query)
    selected = []
    used_sources = set()
    for item in candidates:
        if item["source_index"] not in used_sources or len(selected) >= max_items - 3:
            selected.append(item)
            used_sources.add(item["source_index"])
        if len(selected) >= max_items:
            break
    return selected


def _research_sentences(sources: list[dict], query: str) -> list[dict]:
    return _candidate_sentences(sources, query)


# --------------------------------------------------
# Block construction
# --------------------------------------------------

_SECTION_KEYWORDS = {
    "overview": {"company", "organization", "platform", "technology", "system", "service", "mission", "is a", "based in", "headquartered"},
    "history": {"founded", "founder", "history", "began", "started", "established", "launched", "acquired", "acquisition", "born", "early life", "career began", "1998", "2000", "2004", "2015"},
    "products_services": {"product", "products", "service", "services", "search", "cloud", "software", "platform", "advertising", "android", "youtube", "workspace", "app", "applications", "features"},
    "people": {"founder", "founders", "ceo", "chief executive", "executive", "leadership", "president", "director", "born", "player", "manager", "coach"},
    "technology": {"technology", "technical", "algorithm", "infrastructure", "crawling", "indexing", "ranking", "machine learning", "ai", "architecture", "how it works", "engine", "code", "design"},
    "market": {"market", "industry", "competitor", "competition", "revenue", "business", "customers", "users", "market share", "economy", "position", "annual report"},
    "relationships": {"parent", "subsidiary", "owned by", "partner", "partnership", "competitor", "acquired", "acquisition", "related", "associated", "member of", "belongs to"},
    "developments": {"announced", "launch", "launched", "acquired", "acquisition", "restructure", "restructuring", "milestone", "latest", "recent", "2026", "2025", "2024", "regulatory", "event"},
    "impact": {"impact", "mission", "global", "users", "public", "influence", "importance", "access", "society"},
    "career": {"career", "played", "joined", "club", "team", "goals", "season", "debut", "career", "trophy", "award"},
    "achievements": {"award", "awards", "won", "winner", "champion", "title", "record", "achievement", "honor", "honours", "trophy"},
    "applications": {"application", "applications", "used for", "ecosystem", "library", "framework", "developer", "developers", "web", "data science"},
}


def _select_section_items(candidates: list[dict], section: str, limit: int = 4) -> list[dict]:
    keywords = _SECTION_KEYWORDS.get(section, set())
    scored = []
    for item in candidates:
        low = item["text"].lower()
        hits = sum(1 for k in keywords if k in low)
        focus = item.get("search_focus", "")
        focus_bonus = 5 if focus == section or (section == "products_services" and focus == "products") else 0
        if hits or focus_bonus:
            score = item.get("score", 0) + hits * 4 + focus_bonus
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    selected = []
    seen_text = set()
    used_domains = set()
    for _, item in scored:
        key = _sentence_key(item["text"])
        if key in seen_text:
            continue
        # Prefer source diversity, but allow same authoritative source twice.
        if item.get("domain") in used_domains and len(selected) < limit - 1:
            continue
        selected.append(item)
        seen_text.add(key)
        used_domains.add(item.get("domain"))
        if len(selected) >= limit:
            break
    return selected


def _select_unique_section_items(candidates: list[dict], section: str, used: set[str], limit: int = 4) -> list[dict]:
    """Select evidence that actually belongs to one research block.

    A block first uses evidence collected for its dedicated search angle.
    Within that angle, facts are ranked by section-specific keywords. Only
    when the dedicated angle has too little usable evidence do we use broader
    evidence. Every selected sentence is globally marked as used so blocks do
    not repeat one another.
    """
    focus_map = {"products_services": "products"}
    preferred_focus = focus_map.get(section, section)
    keywords = _SECTION_KEYWORDS.get(section, set())

    def rank(items):
        ranked = []
        for item in items:
            key = _sentence_key(item.get("text", ""))
            if not key or key in used:
                continue
            low = item.get("text", "").lower()
            hits = sum(1 for k in keywords if k in low)
            focus_bonus = 14 if item.get("search_focus") == preferred_focus else 0
            score = item.get("score", 0) + hits * 5 + focus_bonus
            ranked.append((score, item))
        ranked.sort(key=lambda pair: -pair[0])
        return [item for _, item in ranked]

    preferred = rank([c for c in candidates if c.get("search_focus") == preferred_focus])
    fallback = rank([c for c in candidates if c.get("search_focus") != preferred_focus])

    selected = []
    seen_domains = set()
    for item in preferred + fallback:
        key = _sentence_key(item.get("text", ""))
        if not key or key in used:
            continue
        # Prefer different sources inside a block when possible.
        domain = item.get("domain")
        if domain in seen_domains and len(selected) < max(1, limit - 1):
            continue
        selected.append(item)
        used.add(key)
        seen_domains.add(domain)
        if len(selected) >= limit:
            break

    # If source diversity prevented a full block, fill remaining slots without
    # repeating facts.
    if len(selected) < limit:
        for item in preferred + fallback:
            key = _sentence_key(item.get("text", ""))
            if not key or key in used:
                continue
            selected.append(item)
            used.add(key)
            if len(selected) >= limit:
                break

    return selected


def _generic_section_items(candidates: list[dict], used: set[str], limit: int = 3) -> list[dict]:
    selected = []
    for item in candidates:
        key = _sentence_key(item["text"])
        if key in used:
            continue
        selected.append(item)
        used.add(key)
        if len(selected) >= limit:
            break
    return selected


def _item(text: str, source_name: str | None = None, domain: str | None = None, url: str | None = None, **extra) -> dict:
    return {"text": text, "source_name": source_name, "domain": domain, "url": url, **extra}


def _profile_from_sources(subject: str, entity_type: str, sources: list[dict], local_entities: list) -> dict:
    entity = local_entities[0] if local_entities else None
    name = entity.name if entity else subject.strip() if subject else "Research Topic"
    description = entity.description if entity else None
    website = entity.website if entity else None
    category = entity.category if entity else None

    # Prefer a source title that names the subject rather than a random publisher name.
    for source in sources:
        title = source.get("title", "")
        if subject.lower() in title.lower():
            name = subject.strip()
            break
    return {
        "name": name,
        "type": entity_type,
        "category": category,
        "description": description,
        "website": website,
        "subject": subject,
    }


def _build_overview(profile: dict, candidates: list[dict]) -> list[dict]:
    items = _select_section_items(candidates, "overview", 4)
    if profile.get("description"):
        items.insert(0, _item(profile["description"], "EntQra knowledge graph"))
    return items[:4]


def _build_person_blocks(profile: dict, candidates: list[dict]) -> list[dict]:
    blocks = []
    used = set()
    specs = [
        ("background", "Early Life & Background", "Early life, education, origins and entry into the field.", "history", 4),
        ("career", "Career", "Major career stages and professional progression.", "career", 5),
        ("achievements", "Achievements", "Awards, records, titles and other notable accomplishments.", "achievements", 5),
        ("relationships", "Relationships / Associations", "Important clubs, teams, organizations and professional associations.", "relationships", 4),
        ("developments", "Major Events", "Important recent or career-defining events.", "developments", 4),
    ]
    for bid, title, question, section, limit in specs:
        selected = _select_unique_section_items(candidates, section, used, limit)
        if selected:
            blocks.append({"id": bid, "title": title, "question": question, "items": selected})
    return blocks


def _build_technology_blocks(profile: dict, candidates: list[dict]) -> list[dict]:
    used = set()
    specs = [
        ("history", "History & Development", "How did the technology evolve?", "history", 4),
        ("technology", "Language / Technical Design", "How is it designed and how does it work?", "technology", 5),
        ("products_services", "Features & Capabilities", "What can it do?", "products_services", 5),
        ("applications", "Ecosystem & Applications", "Where is it used and what surrounds it?", "applications", 5),
        ("developments", "Versions / Development", "What significant releases or changes matter?", "developments", 4),
        ("relationships", "Related Technologies", "What technologies is it connected to?", "relationships", 4),
    ]
    blocks = []
    for bid, title, question, section, limit in specs:
        selected = _select_unique_section_items(candidates, section, used, limit)
        if selected:
            blocks.append({"id": bid, "title": title, "question": question, "items": selected})
    return blocks


def _build_company_blocks(profile: dict, candidates: list[dict], relationships: list[dict]) -> list[dict]:
    specs = [
        ("history", "History & Background", "How did the company come into existence and evolve?", "history", 5),
        ("products_services", "Products & Services", "What does the company actually offer?", "products_services", 6),
        ("people", "People / Leadership / Founders", "Who are the important people associated with it?", "people", 5),
        ("technology", "Technology / Operations", "How does it work and what powers its operations?", "technology", 5),
        ("market", "Business / Market / Industry", "Where does it stand in its industry and how does it compete?", "market", 5),
        ("relationships", "Relationships / Connections", "What entities is it connected to?", "relationships", 5),
        ("developments", "Major Developments / Events", "What significant launches, acquisitions, changes or events matter?", "developments", 5),
    ]
    blocks = []
    used = set()
    for bid, title, question, section, limit in specs:
        selected = _select_unique_section_items(candidates, section, used, limit)
        if bid == "relationships" and relationships:
            rel_items = [
                _item(
                    f"{r.get('source_entity_name') or profile['name']} {r.get('relationship_type', 'is related to')} {r.get('target_entity_name') or 'another entity'}" + (f": {r['description']}" if r.get("description") else ""),
                    "EntQra knowledge graph",
                    extra_type="graph_relationship",
                )
                for r in relationships[:8]
            ]
            selected = rel_items + selected
        if selected:
            blocks.append({"id": bid, "title": title, "question": question, "items": selected[:limit]})
    return blocks


def _build_generic_blocks(profile: dict, candidates: list[dict], relationships: list[dict]) -> list[dict]:
    specs = [
        ("history", "History & Background", "How did it develop?", "history", 4),
        ("products_services", "Features / Uses", "What does it provide or enable?", "products_services", 5),
        ("technology", "How It Works", "What mechanisms or ideas define it?", "technology", 5),
        ("market", "Context / Position", "Where does it fit in its wider field?", "market", 4),
        ("relationships", "Relationships / Connections", "What is it connected to?", "relationships", 4),
        ("developments", "Important Developments", "What significant changes or events matter?", "developments", 4),
    ]
    used = set()
    blocks = []
    for bid, title, question, section, limit in specs:
        selected = _select_unique_section_items(candidates, section, used, limit)
        if selected:
            blocks.append({"id": bid, "title": title, "question": question, "items": selected})
    return blocks


def _build_research_dossier(query: str, sources: list[dict], evidence: list[dict], local_entities: list, entity_type: str | None = None, relationships: list[dict] | None = None) -> dict:
    subject = _infer_subject(query)
    entity_type = entity_type or _infer_entity_type(subject, sources, query)
    profile = _profile_from_sources(subject, entity_type, sources, local_entities)
    candidates = _research_sentences(sources, subject) or evidence
    relationships = relationships or []

    # Overview owns its facts first. The remaining blocks are built from the
    # remaining evidence so the same sentence is not rendered repeatedly.
    overview = _build_overview(profile, candidates)
    overview_keys = {_sentence_key(x.get("text", "")) for x in overview}
    remaining = [c for c in candidates if _sentence_key(c.get("text", "")) not in overview_keys]

    blocks = [
        {"id": "entity_header", "title": "Entity Header", "question": "What exactly are we researching?", "items": []},
        {"id": "intelligence_answer", "title": "Intelligence Answer", "question": "What is the direct answer to the question?", "items": []},
        {"id": "key_findings", "title": "Key Findings", "question": "What are the most important discoveries?", "items": []},
        {"id": "overview", "title": "Overview", "question": "What is it fundamentally?", "items": overview},
    ]

    if entity_type == "company":
        blocks.extend(_build_company_blocks(profile, remaining, relationships))
    elif entity_type == "person":
        blocks.extend(_build_person_blocks(profile, remaining))
    elif entity_type == "technology":
        blocks.extend(_build_technology_blocks(profile, remaining))
    else:
        blocks.extend(_build_generic_blocks(profile, remaining, relationships))

    blocks.append({
        "id": "evidence",
        "title": "Evidence & Sources",
        "question": "Where did these facts come from?",
        "items": [
            _item(
                f"{s.get('source_name') or s.get('domain') or 'Source'} — {s.get('title') or 'Untitled source'}",
                s.get("source_name"), s.get("domain"), s.get("url"),
                source_title=s.get("title"),
                source_quality=s.get("quality"),
                retrieval=s.get("retrieval"),
                research_focus=s.get("search_focus", "direct"),
                supports=f"{s.get('search_focus', 'direct')} research",
            )
            for s in sources[:10]
        ],
    })

    return {
        "profile": profile,
        "blocks": blocks,
        "sections": blocks,
        "method": "Focused multi-angle web research with source ranking, page extraction, evidence deduplication and role-specific synthesis.",
    }


def _build_key_findings(evidence: list[dict], max_items: int = 6) -> list[str]:
    """Return concise, non-duplicated discoveries for the Findings block."""
    findings = []
    seen = set()
    for item in evidence:
        text = _clean_text(item.get("text", "")).strip(" -•")
        key = _sentence_key(text)
        if not text or key in seen or not _is_clean_fact(text):
            continue
        # Findings should be meaningful facts, not generic page descriptions.
        if len(text.split()) < 8:
            continue
        seen.add(key)
        findings.append(text)
        if len(findings) >= max_items:
            break
    return findings


def _build_direct_answer(query: str, profile: dict, blocks: list[dict], key_findings: list[str], confidence: dict) -> str:
    """Produce a readable synthesis rather than concatenating search results."""
    name = profile.get("name") or profile.get("subject") or "this topic"
    entity_type = profile.get("type", "topic")

    def first_items(block_id: str, count: int = 1):
        block = next((b for b in blocks if b.get("id") == block_id), None)
        return [x.get("text", "") for x in (block or {}).get("items", [])[:count] if x.get("text")]

    overview = first_items("overview", 2)
    history = first_items("history", 1)
    products = first_items("products_services", 2)
    people = first_items("people", 1)
    technology = first_items("technology", 1)
    market = first_items("market", 1)
    developments = first_items("developments", 1)

    paragraphs = []
    if overview:
        paragraphs.append(f"{name} is best understood as a {entity_type}. " + " ".join(overview[:2]))

    if entity_type == "company":
        middle = []
        if history:
            middle.append(history[0])
        if products:
            middle.append("Its main activities and offerings include " + " ".join(products) + ".")
        if people:
            middle.append(people[0])
        if middle:
            paragraphs.append(" ".join(middle))
        closing = []
        if technology:
            closing.append(technology[0])
        if market:
            closing.append(market[0])
        if developments:
            closing.append(developments[0])
        if closing:
            paragraphs.append(" ".join(closing))
    else:
        extra = []
        if history:
            extra.append(history[0])
        if technology:
            extra.append(technology[0])
        if developments:
            extra.append(developments[0])
        if not extra:
            extra = key_findings[:2]
        if extra:
            paragraphs.append(" ".join(extra[:2]))

    if not paragraphs:
        paragraphs = key_findings[:3]

    return "\n\n".join(p.strip() for p in paragraphs[:3] if p.strip()) or f"EntQra could not find enough reliable evidence to answer '{query}'."


def _calculate_confidence(sources: list[dict], evidence: list[dict], conflicts: list[dict] | None = None) -> dict:
    conflicts = conflicts or []
    domains = {s.get("domain") for s in sources if s.get("domain")}
    strong = sum(1 for s in sources if s.get("quality") in {"primary", "high"})
    primary = sum(1 for s in sources if s.get("quality") == "primary")
    full_page = sum(1 for s in sources if s.get("retrieval") == "full_page")
    coverage = min(1.0, len(evidence) / 10)
    agreement_penalty = min(0.20, len(conflicts) * 0.05)
    raw = min(1.0, 0.45 + min(0.25, len(domains) * 0.05) + min(0.15, strong * 0.04) + min(0.10, full_page * 0.02) + coverage * 0.10 - agreement_penalty)
    if raw >= 0.82:
        level = "high"
    elif raw >= 0.68:
        level = "medium-high"
    elif raw >= 0.52:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "score": round(raw, 2),
        "rationale": "Confidence reflects source quality, source diversity, accessible source pages, evidence coverage, and detected disagreements.",
        "independent_domains": len(domains),
        "strong_sources": strong,
        "primary_sources": primary,
        "full_page_sources": full_page,
        "supporting_evidence": len(evidence),
    }


def _detect_conflicts(evidence: list[dict]) -> list[dict]:
    # Conservative conflict detection: only flag different values when the
    # sentences use the same fact cue. Do not manufacture disagreements.
    conflicts = []
    cues = ("founded", "established", "born", "launched", "acquired", "employees", "revenue", "market share")
    groups = defaultdict(list)
    for item in evidence:
        low = item.get("text", "").lower()
        cue = next((c for c in cues if c in low), None)
        if cue:
            years = re.findall(r"\b(?:19|20)\d{2}\b", low)
            nums = re.findall(r"\b\d+(?:\.\d+)?%?\b", low)
            values = years or nums
            if values:
                groups[cue].append((set(values), item))
    for cue, entries in groups.items():
        all_values = set().union(*(vals for vals, _ in entries))
        if len(all_values) > 1 and len(entries) >= 2:
            distinct = []
            for vals, item in entries:
                for v in vals:
                    distinct.append((v, item))
            # Require two different domains before calling it a conflict.
            by_value = defaultdict(list)
            for value, item in distinct:
                by_value[value].append(item)
            values = list(by_value)
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    a, b = values[i], values[j]
                    da = by_value[a][0].get("domain")
                    db = by_value[b][0].get("domain")
                    if da and db and da != db:
                        conflicts.append({
                            "type": "possible_fact_conflict",
                            "fact": cue,
                            "values": [a, b],
                            "sources": [by_value[a][0].get("source_name"), by_value[b][0].get("source_name")],
                            "explanation": f"Sources report different values for {cue}. Check the cited sources and distinguish dates or definitions if necessary.",
                        })
    return conflicts[:5]


def _build_claims(evidence: list[dict], sources: list[dict]) -> list[dict]:
    claims = []
    for item in evidence[:12]:
        claims.append({
            "text": item.get("text"),
            "supported_by": [{
                "source_name": item.get("source_name"),
                "domain": item.get("domain"),
                "url": item.get("url"),
            }],
        })
    return claims


def _research_signals(sources: list[dict], evidence: list[dict], confidence: dict, conflicts: list[dict]) -> dict:
    primary = sum(1 for s in sources if s.get("quality") == "primary")
    high = sum(1 for s in sources if s.get("quality") in {"primary", "high"})
    agreement = "high" if not conflicts and len({s.get("domain") for s in sources}) >= 3 else ("medium" if not conflicts else "low")
    recency = "medium" if any(s.get("search_focus") == "developments" for s in sources) else "unknown"
    coverage = "high" if len(evidence) >= 8 else ("medium" if len(evidence) >= 4 else "low")
    return {
        "source_quality": "high" if high >= 3 else ("medium" if high else "low"),
        "source_agreement": agreement,
        "fact_coverage": coverage,
        "recency": recency,
        "conflict_detected": bool(conflicts),
        "primary_sources": primary,
        "independent_domains": confidence["independent_domains"],
    }


def _build_research_answer(query: str, findings: list[str], confidence: dict, conflicts: list[dict]) -> str:
    # Backwards-compatible helper retained for older frontend calls.
    if not findings:
        return "EntQra could not find enough reliable evidence to construct an answer."
    return "\n\n".join(findings[:3])


def _build_research_dossier_legacy(query: str, sources: list[dict], evidence: list[dict], local_entities: list) -> dict:
    return _build_research_dossier(query, sources, evidence, local_entities)


def _match_local_entities(db: Session, query: str):
    subject = _infer_subject(query).lower()
    terms = [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9&.-]{1,}", subject) if len(t) > 1]
    if not terms:
        return []
    try:
        entities = db.query(Entity).all()
    except Exception:
        return []
    matches = []
    for entity in entities:
        name = (entity.name or "").lower()
        haystack = " ".join([name, entity.entity_type or "", entity.category or "", entity.description or ""]).lower()
        score = 0
        if name == subject:
            score += 100
        if name and name in subject:
            score += 40
        score += sum(3 for t in terms if t in name)
        score += sum(1 for t in terms if t in haystack)
        if score:
            matches.append((score, entity))
    matches.sort(key=lambda x: (-x[0], (x[1].name or "").lower()))
    return [e for _, e in matches[:10]]


# ==================================================
# HOME
# ==================================================

@app.get("/")
def home():
    return {
        "message": "ENTORA backend is running!"
    }


# ==================================================
# AUTHENTICATED USER
# ==================================================

def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    # ----------------------------------------------
    # Get token
    # ----------------------------------------------

    token = credentials.credentials

    # ----------------------------------------------
    # Verify JWT
    # ----------------------------------------------

    payload = verify_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    # ----------------------------------------------
    # Get user ID from token
    # ----------------------------------------------

    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid token payload"
        )

    # ----------------------------------------------
    # Convert user ID to integer
    # ----------------------------------------------

    try:
        user_id = int(user_id)

    except (TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid user ID in token"
        )

    # ----------------------------------------------
    # Find user
    # ----------------------------------------------

    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found"
        )

    # ----------------------------------------------
    # Check account status
    # ----------------------------------------------

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="User account is inactive"
        )

    return user


# ==================================================
# GET USERS
# ==================================================

@app.get("/users")
def get_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    users = db.query(User).all()

    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_active": user.is_active
        }
        for user in users
    ]


# ==================================================
# CREATE USER
# ==================================================

@app.post("/users")
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db)
):
    # ----------------------------------------------
    # Normalize email
    # ----------------------------------------------

    email = user.email.strip().lower()
    name = user.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Name cannot be empty"
        )

    if not email:
        raise HTTPException(
            status_code=400,
            detail="Email cannot be empty"
        )

    # ----------------------------------------------
    # Check duplicate email
    # ----------------------------------------------

    existing_user = db.query(User).filter(
        User.email == email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    # ----------------------------------------------
    # Hash password
    # ----------------------------------------------

    hashed_password = password_hash.hash(
        user.password
    )

    # ----------------------------------------------
    # Create user
    # ----------------------------------------------

    new_user = User(
        name=name,
        email=email,
        password_hash=hashed_password,
        is_active=True
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Failed to create user"
        )

    return {
        "id": new_user.id,
        "name": new_user.name,
        "email": new_user.email,
        "is_active": new_user.is_active
    }


# ==================================================
# LOGIN
# ==================================================

@app.post("/login")
def login_user(
    user: LoginRequest,
    db: Session = Depends(get_db)
):
    # ----------------------------------------------
    # Normalize email
    # ----------------------------------------------

    email = user.email.strip().lower()

    # ----------------------------------------------
    # Validate input
    # ----------------------------------------------

    if not email:
        raise HTTPException(
            status_code=400,
            detail="Email is required"
        )

    if not user.password:
        raise HTTPException(
            status_code=400,
            detail="Password is required"
        )

    # ----------------------------------------------
    # Find user
    # ----------------------------------------------

    existing_user = db.query(User).filter(
        User.email == email
    ).first()

    if existing_user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # ----------------------------------------------
    # Verify password
    # ----------------------------------------------

    password_valid = password_hash.verify(
        user.password,
        existing_user.password_hash
    )

    if not password_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # ----------------------------------------------
    # Check account
    # ----------------------------------------------

    if not existing_user.is_active:
        raise HTTPException(
            status_code=403,
            detail="User account is inactive"
        )

    # ----------------------------------------------
    # Create JWT
    # ----------------------------------------------

    access_token = create_access_token(
        {
            "sub": str(existing_user.id),
            "email": existing_user.email
        }
    )

    # ----------------------------------------------
    # Response
    # ----------------------------------------------

    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": existing_user.id,
            "name": existing_user.name,
            "email": existing_user.email,
            "is_active": existing_user.is_active
        }
    }


# ==================================================
# CURRENT USER
# ==================================================

@app.get("/me")
def me(
    current_user: User = Depends(get_authenticated_user)
):
    return {
        "message": "You are authenticated!",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "is_active": current_user.is_active
        }
    }


# ==================================================
# GET PROFILE
# ==================================================

@app.get("/profile")
def get_profile(
    current_user: User = Depends(get_authenticated_user)
):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "is_active": current_user.is_active
    }


# ==================================================
# UPDATE PROFILE
# ==================================================

@app.put("/profile")
def update_profile(
    profile: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    # ----------------------------------------------
    # Update name
    # ----------------------------------------------

    if profile.name is not None:

        name = profile.name.strip()

        if not name:
            raise HTTPException(
                status_code=400,
                detail="Name cannot be empty"
            )

        current_user.name = name

    # ----------------------------------------------
    # Update email
    # ----------------------------------------------

    if profile.email is not None:

        email = profile.email.strip().lower()

        if not email:
            raise HTTPException(
                status_code=400,
                detail="Email cannot be empty"
            )

        existing_user = db.query(User).filter(
            User.email == email,
            User.id != current_user.id
        ).first()

        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )

        current_user.email = email

    # ----------------------------------------------
    # Update password
    # ----------------------------------------------

    if profile.password is not None:

        current_user.password_hash = password_hash.hash(
            profile.password
        )

    # ----------------------------------------------
    # Save changes
    # ----------------------------------------------

    try:
        db.commit()
        db.refresh(current_user)

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Failed to update profile"
        )

    return {
        "message": "Profile updated successfully",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "is_active": current_user.is_active
        }
    }


# ==================================================
# ENTORA ENTITY SYSTEM
# ==================================================


# ==================================================
# CREATE ENTITY
# ==================================================

@app.post("/entities")
def create_entity(
    entity: EntityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    print()
    print("==============================================")
    print("CREATE ENTITY ENDPOINT CALLED")
    print("==============================================")

    try:

        print(
            "Authenticated user:",
            current_user.id,
            current_user.email
        )

        print(
            "Incoming entity data:",
            entity.model_dump()
        )

        name = entity.name.strip()

        if not name:
            raise HTTPException(
                status_code=400,
                detail="Entity name cannot be empty"
            )

        entity_type = entity.entity_type.strip().lower()

        if not entity_type:
            raise HTTPException(
                status_code=400,
                detail="Entity type cannot be empty"
            )

        category = (
            entity.category.strip()
            if entity.category
            else None
        )

        description = (
            entity.description.strip()
            if entity.description
            else None
        )

        website = (
            entity.website.strip()
            if entity.website
            else None
        )

        logo_url = (
            entity.logo_url.strip()
            if entity.logo_url
            else None
        )

        print("Validation passed")

        new_entity = Entity(
            name=name,
            entity_type=entity_type,
            category=category,
            description=description,
            website=website,
            logo_url=logo_url
        )

        print("SQLAlchemy Entity object created")

        db.add(new_entity)

        print("Entity added to database session")

        db.commit()

        print("DATABASE COMMIT SUCCESSFUL")

        db.refresh(new_entity)

        print("DATABASE REFRESH SUCCESSFUL")
        print("Created entity ID:", new_entity.id)

        return {
            "message": "Entity created successfully",
            "entity": {
                "id": new_entity.id,
                "name": new_entity.name,
                "entity_type": new_entity.entity_type,
                "category": new_entity.category,
                "description": new_entity.description,
                "website": new_entity.website,
                "logo_url": new_entity.logo_url,
                "created_at": new_entity.created_at,
                "updated_at": new_entity.updated_at
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        db.rollback()

        print()
        print("==============================================")
        print("ENTITY CREATION ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print(
            "FULL ERROR:",
            repr(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Entity creation failed",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# SEARCH / DISCOVER ENTITIES
# ==================================================

@app.get("/entities/search")
def search_entities(
    q: str = Query(
        default="",
        min_length=1,
        description="Search entities by name, type, category or description"
    ),
    entity_type: str | None = Query(
        default=None,
        description="Optional entity type filter"
    ),
    category: str | None = Query(
        default=None,
        description="Optional category filter"
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of results"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    """
    Search entities using the entity name, entity type,
    category and description.

    This endpoint is authenticated and is intended for
    the EntQra Entity Discovery system.
    """

    try:

        search_term = q.strip()

        if not search_term:
            raise HTTPException(
                status_code=400,
                detail="Search query cannot be empty"
            )

        search_pattern = f"%{search_term}%"

        # ----------------------------------------------
        # Base search
        # ----------------------------------------------

        query = db.query(Entity).filter(
            or_(
                Entity.name.ilike(search_pattern),
                Entity.entity_type.ilike(search_pattern),
                Entity.category.ilike(search_pattern),
                Entity.description.ilike(search_pattern)
            )
        )

        # ----------------------------------------------
        # Optional entity type filter
        # ----------------------------------------------

        if entity_type is not None:

            normalized_entity_type = (
                entity_type.strip().lower()
            )

            if normalized_entity_type:
                query = query.filter(
                    Entity.entity_type.ilike(
                        normalized_entity_type
                    )
                )

        # ----------------------------------------------
        # Optional category filter
        # ----------------------------------------------

        if category is not None:

            normalized_category = (
                category.strip()
            )

            if normalized_category:
                query = query.filter(
                    Entity.category.ilike(
                        normalized_category
                    )
                )

        # ----------------------------------------------
        # Execute search
        # ----------------------------------------------

        entities = query.order_by(
            Entity.name.asc()
        ).limit(limit).all()

        # ----------------------------------------------
        # Format results
        # ----------------------------------------------

        result = []

        for entity in entities:

            result.append({
                "id": entity.id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "category": entity.category,
                "description": entity.description,
                "website": entity.website,
                "logo_url": entity.logo_url,
                "created_at": entity.created_at,
                "updated_at": entity.updated_at
            })

        return {
            "message": "Entity search completed successfully",
            "query": search_term,
            "count": len(result),
            "entities": result
        }

    except HTTPException:
        raise

    except Exception as e:

        print()
        print("==============================================")
        print("ENTITY SEARCH ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print(
            "FULL ERROR:",
            repr(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Entity search failed",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# GET ALL ENTITIES
# ==================================================

@app.get("/entities")
def get_entities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    try:

        entities = db.query(Entity).order_by(
            Entity.id.asc()
        ).all()

        result = []

        for entity in entities:

            result.append({
                "id": entity.id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "category": entity.category,
                "description": entity.description,
                "website": entity.website,
                "logo_url": entity.logo_url,
                "created_at": entity.created_at,
                "updated_at": entity.updated_at
            })

        return {
            "message": "Entities retrieved successfully",
            "count": len(result),
            "entities": result
        }

    except Exception as e:

        print()
        print("==============================================")
        print("GET ENTITIES ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to retrieve entities",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# GET SINGLE ENTITY
# ==================================================

@app.get("/entities/{entity_id}")
def get_entity(
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    try:

        entity = db.query(Entity).filter(
            Entity.id == entity_id
        ).first()

        if entity is None:
            raise HTTPException(
                status_code=404,
                detail="Entity not found"
            )

        return {
            "message": "Entity retrieved successfully",
            "entity": {
                "id": entity.id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "category": entity.category,
                "description": entity.description,
                "website": entity.website,
                "logo_url": entity.logo_url,
                "created_at": entity.created_at,
                "updated_at": entity.updated_at
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        print()
        print("==============================================")
        print("GET ENTITY ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to retrieve entity",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# UPDATE ENTITY
# ==================================================

@app.put("/entities/{entity_id}")
def update_entity(
    entity_id: int,
    entity_data: EntityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    print()
    print("==============================================")
    print("UPDATE ENTITY ENDPOINT CALLED")
    print("==============================================")

    try:

        print(
            "Authenticated user:",
            current_user.id,
            current_user.email
        )

        entity = db.query(Entity).filter(
            Entity.id == entity_id
        ).first()

        if entity is None:
            raise HTTPException(
                status_code=404,
                detail="Entity not found"
            )

        update_data = entity_data.model_dump(
            exclude_unset=True
        )

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        print(
            "Incoming update data:",
            update_data
        )

        if "name" in update_data:

            if update_data["name"] is None:
                raise HTTPException(
                    status_code=400,
                    detail="Entity name cannot be null"
                )

            name = update_data["name"].strip()

            if not name:
                raise HTTPException(
                    status_code=400,
                    detail="Entity name cannot be empty"
                )

            entity.name = name

        if "entity_type" in update_data:

            if update_data["entity_type"] is None:
                raise HTTPException(
                    status_code=400,
                    detail="Entity type cannot be null"
                )

            entity_type = update_data[
                "entity_type"
            ].strip().lower()

            if not entity_type:
                raise HTTPException(
                    status_code=400,
                    detail="Entity type cannot be empty"
                )

            entity.entity_type = entity_type

        if "category" in update_data:

            if update_data["category"] is None:
                entity.category = None
            else:
                category = update_data[
                    "category"
                ].strip()

                entity.category = (
                    category if category else None
                )

        if "description" in update_data:

            if update_data["description"] is None:
                entity.description = None
            else:
                description = update_data[
                    "description"
                ].strip()

                entity.description = (
                    description
                    if description
                    else None
                )

        if "website" in update_data:

            if update_data["website"] is None:
                entity.website = None
            else:
                website = update_data[
                    "website"
                ].strip()

                entity.website = (
                    website if website else None
                )

        if "logo_url" in update_data:

            if update_data["logo_url"] is None:
                entity.logo_url = None
            else:
                logo_url = update_data[
                    "logo_url"
                ].strip()

                entity.logo_url = (
                    logo_url if logo_url else None
                )

        print("Entity fields updated")

        db.commit()

        print("DATABASE COMMIT SUCCESSFUL")

        db.refresh(entity)

        print("DATABASE REFRESH SUCCESSFUL")

        return {
            "message": "Entity updated successfully",
            "entity": {
                "id": entity.id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "category": entity.category,
                "description": entity.description,
                "website": entity.website,
                "logo_url": entity.logo_url,
                "created_at": entity.created_at,
                "updated_at": entity.updated_at
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        db.rollback()

        print()
        print("==============================================")
        print("ENTITY UPDATE ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print(
            "FULL ERROR:",
            repr(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Entity update failed",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# DELETE ENTITY
# ==================================================

@app.delete("/entities/{entity_id}")
def delete_entity(
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    print()
    print("==============================================")
    print("DELETE ENTITY ENDPOINT CALLED")
    print("==============================================")

    try:

        print(
            "Authenticated user:",
            current_user.id,
            current_user.email
        )

        entity = db.query(Entity).filter(
            Entity.id == entity_id
        ).first()

        if entity is None:
            raise HTTPException(
                status_code=404,
                detail="Entity not found"
            )

        deleted_entity = {
            "id": entity.id,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "category": entity.category,
            "description": entity.description,
            "website": entity.website,
            "logo_url": entity.logo_url
        }

        print(
            "Entity found:",
            entity.id,
            entity.name
        )

        db.delete(entity)

        print("Entity marked for deletion")

        db.commit()

        print("DATABASE DELETE COMMIT SUCCESSFUL")

        return {
            "message": "Entity deleted successfully",
            "entity": deleted_entity
        }

    except HTTPException:
        raise

    except Exception as e:

        db.rollback()

        print()
        print("==============================================")
        print("ENTITY DELETE ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print(
            "FULL ERROR:",
            repr(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Entity deletion failed",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# ENTORA ENTITY RELATIONSHIP SYSTEM
# ==================================================


# ==================================================
# CREATE ENTITY RELATIONSHIP
# ==================================================

@app.post("/relationships")
def create_relationship(
    relationship: RelationshipCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    print()
    print("==============================================")
    print("CREATE RELATIONSHIP ENDPOINT CALLED")
    print("==============================================")

    try:

        print(
            "Authenticated user:",
            current_user.id,
            current_user.email
        )

        source_entity = db.query(Entity).filter(
            Entity.id == relationship.source_entity_id
        ).first()

        if source_entity is None:
            raise HTTPException(
                status_code=404,
                detail="Source entity not found"
            )

        target_entity = db.query(Entity).filter(
            Entity.id == relationship.target_entity_id
        ).first()

        if target_entity is None:
            raise HTTPException(
                status_code=404,
                detail="Target entity not found"
            )

        if (
            relationship.source_entity_id
            == relationship.target_entity_id
        ):
            raise HTTPException(
                status_code=400,
                detail="Source and target entities cannot be the same"
            )

        relationship_type = (
            relationship.relationship_type
            .strip()
            .lower()
        )

        if not relationship_type:
            raise HTTPException(
                status_code=400,
                detail="Relationship type cannot be empty"
            )

        description = (
            relationship.description.strip()
            if relationship.description
            else None
        )

        existing_relationship = db.query(
            EntityRelationship
        ).filter(
            EntityRelationship.source_entity_id
            == relationship.source_entity_id,
            EntityRelationship.target_entity_id
            == relationship.target_entity_id,
            EntityRelationship.relationship_type
            == relationship_type
        ).first()

        if existing_relationship:
            raise HTTPException(
                status_code=400,
                detail="This relationship already exists"
            )

        new_relationship = EntityRelationship(
            source_entity_id=relationship.source_entity_id,
            target_entity_id=relationship.target_entity_id,
            relationship_type=relationship_type,
            description=description
        )

        print(
            "Creating relationship:",
            source_entity.name,
            "->",
            target_entity.name
        )

        db.add(new_relationship)

        db.commit()

        print("RELATIONSHIP DATABASE COMMIT SUCCESSFUL")

        db.refresh(new_relationship)

        print(
            "Created relationship ID:",
            new_relationship.id
        )

        return {
            "message": "Relationship created successfully",
            "relationship": {
                "id": new_relationship.id,
                "source_entity_id": new_relationship.source_entity_id,
                "target_entity_id": new_relationship.target_entity_id,
                "source_entity_name": source_entity.name,
                "target_entity_name": target_entity.name,
                "relationship_type": new_relationship.relationship_type,
                "description": new_relationship.description,
                "created_at": new_relationship.created_at,
                "updated_at": new_relationship.updated_at
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        db.rollback()

        print()
        print("==============================================")
        print("RELATIONSHIP CREATION ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print(
            "FULL ERROR:",
            repr(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Relationship creation failed",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# GET ALL RELATIONSHIPS
# ==================================================

@app.get("/relationships")
def get_relationships(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    try:

        relationships = db.query(
            EntityRelationship
        ).order_by(
            EntityRelationship.id.asc()
        ).all()

        result = []

        for relationship in relationships:

            result.append({
                "id": relationship.id,
                "source_entity_id": relationship.source_entity_id,
                "target_entity_id": relationship.target_entity_id,
                "source_entity_name": (
                    relationship.source_entity.name
                    if relationship.source_entity
                    else None
                ),
                "target_entity_name": (
                    relationship.target_entity.name
                    if relationship.target_entity
                    else None
                ),
                "relationship_type": (
                    relationship.relationship_type
                ),
                "description": relationship.description,
                "created_at": relationship.created_at,
                "updated_at": relationship.updated_at
            })

        return {
            "message": "Relationships retrieved successfully",
            "count": len(result),
            "relationships": result
        }

    except Exception as e:

        print()
        print("==============================================")
        print("GET RELATIONSHIPS ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to retrieve relationships",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# GET SINGLE RELATIONSHIP
# ==================================================

@app.get("/relationships/{relationship_id}")
def get_relationship(
    relationship_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    try:

        relationship = db.query(
            EntityRelationship
        ).filter(
            EntityRelationship.id == relationship_id
        ).first()

        if relationship is None:
            raise HTTPException(
                status_code=404,
                detail="Relationship not found"
            )

        return {
            "message": "Relationship retrieved successfully",
            "relationship": {
                "id": relationship.id,
                "source_entity_id": relationship.source_entity_id,
                "target_entity_id": relationship.target_entity_id,
                "source_entity_name": (
                    relationship.source_entity.name
                    if relationship.source_entity
                    else None
                ),
                "target_entity_name": (
                    relationship.target_entity.name
                    if relationship.target_entity
                    else None
                ),
                "relationship_type": (
                    relationship.relationship_type
                ),
                "description": relationship.description,
                "created_at": relationship.created_at,
                "updated_at": relationship.updated_at
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        print()
        print("==============================================")
        print("GET RELATIONSHIP ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to retrieve relationship",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# GET RELATIONSHIPS FOR AN ENTITY
# ==================================================

@app.get("/entities/{entity_id}/relationships")
def get_entity_relationships(
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    try:

        entity = db.query(Entity).filter(
            Entity.id == entity_id
        ).first()

        if entity is None:
            raise HTTPException(
                status_code=404,
                detail="Entity not found"
            )

        outgoing = db.query(
            EntityRelationship
        ).filter(
            EntityRelationship.source_entity_id
            == entity_id
        ).order_by(
            EntityRelationship.id.asc()
        ).all()

        incoming = db.query(
            EntityRelationship
        ).filter(
            EntityRelationship.target_entity_id
            == entity_id
        ).order_by(
            EntityRelationship.id.asc()
        ).all()

        outgoing_result = []

        for relationship in outgoing:

            outgoing_result.append({
                "id": relationship.id,
                "source_entity_id": (
                    relationship.source_entity_id
                ),
                "target_entity_id": (
                    relationship.target_entity_id
                ),
                "source_entity_name": (
                    relationship.source_entity.name
                ),
                "target_entity_name": (
                    relationship.target_entity.name
                ),
                "relationship_type": (
                    relationship.relationship_type
                ),
                "description": relationship.description,
                "created_at": relationship.created_at,
                "updated_at": relationship.updated_at
            })

        incoming_result = []

        for relationship in incoming:

            incoming_result.append({
                "id": relationship.id,
                "source_entity_id": (
                    relationship.source_entity_id
                ),
                "target_entity_id": (
                    relationship.target_entity_id
                ),
                "source_entity_name": (
                    relationship.source_entity.name
                ),
                "target_entity_name": (
                    relationship.target_entity.name
                ),
                "relationship_type": (
                    relationship.relationship_type
                ),
                "description": relationship.description,
                "created_at": relationship.created_at,
                "updated_at": relationship.updated_at
            })

        return {
            "message": "Entity relationships retrieved successfully",
            "entity": {
                "id": entity.id,
                "name": entity.name
            },
            "outgoing_relationships": outgoing_result,
            "incoming_relationships": incoming_result,
            "outgoing_count": len(outgoing_result),
            "incoming_count": len(incoming_result)
        }

    except HTTPException:
        raise

    except Exception as e:

        print()
        print("==============================================")
        print("GET ENTITY RELATIONSHIPS ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to retrieve entity relationships",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )


# ==================================================
# DELETE ENTITY RELATIONSHIP
# ==================================================

@app.delete("/relationships/{relationship_id}")
def delete_relationship(
    relationship_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    print()
    print("==============================================")
    print("DELETE RELATIONSHIP ENDPOINT CALLED")
    print("==============================================")

    try:

        print(
            "Authenticated user:",
            current_user.id,
            current_user.email
        )

        relationship = db.query(
            EntityRelationship
        ).filter(
            EntityRelationship.id == relationship_id
        ).first()

        if relationship is None:
            raise HTTPException(
                status_code=404,
                detail="Relationship not found"
            )

        deleted_relationship = {
            "id": relationship.id,
            "source_entity_id": (
                relationship.source_entity_id
            ),
            "target_entity_id": (
                relationship.target_entity_id
            ),
            "relationship_type": (
                relationship.relationship_type
            ),
            "description": relationship.description
        }

        print(
            "Relationship found:",
            relationship.id
        )

        db.delete(relationship)

        print("Relationship marked for deletion")

        db.commit()

        print(
            "RELATIONSHIP DELETE COMMIT SUCCESSFUL"
        )

        return {
            "message": "Relationship deleted successfully",
            "relationship": deleted_relationship
        }

    except HTTPException:
        raise

    except Exception as e:

        db.rollback()

        print()
        print("==============================================")
        print("RELATIONSHIP DELETE ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print(
            "FULL ERROR:",
            repr(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Relationship deletion failed",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )
        
        
        
# ==================================================
# REAL INTELLIGENCE SEARCH
# ==================================================


# ==================================================
# UNIVERSAL ENTQRA RESEARCH ENGINE
# ==================================================

_PROVIDER_PRIORITY = {"tavily": 1.00, "exa": 0.98, "serper": 0.92}
_PRIMARY_DOMAIN_HINTS = {
    "about.google", "google.com", "blog.google", "cloud.google.com",
    "abc.xyz", "microsoft.com", "blogs.microsoft.com", "learn.microsoft.com",
    "apple.com", "amazon.com", "aws.amazon.com", "meta.com", "openai.com",
    "nvidia.com", "tesla.com", "ibm.com", "intel.com", "adobe.com",
    "salesforce.com", "github.com", "python.org", "mozilla.org", "wikipedia.org",
    "sec.gov", "ftc.gov", "europa.eu", "gov.uk", "gov.in", "nasa.gov", "who.int",
}
_HIGH_QUALITY_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nature.com",
    "science.org", "theguardian.com", "nytimes.com", "wsj.com", "ft.com",
    "bloomberg.com", "cnbc.com", "techcrunch.com", "arstechnica.com",
    "theverge.com", "espn.com", "skysports.com", "forbes.com", "economist.com",
}
_REFERENCE_DOMAINS = {"wikipedia.org", "en.wikipedia.org", "britannica.com"}


def _env_key(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _provider_status() -> dict:
    return {
        "tavily": bool(_env_key("TAVILY_API_KEY") and TavilyClient),
        "exa": bool(_env_key("EXA_API_KEY") and Exa),
        "serper": bool(_env_key("SERPER_API_KEY") and requests),
    }


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    value = _normalise_search_url(url).split("#", 1)[0].rstrip("/")
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    # Strip obvious tracking parameters while preserving useful query URLs.
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
    if parsed.query:
        params = []
        for part in parsed.query.split("&"):
            key = part.split("=", 1)[0].lower()
            if key and key not in tracking:
                params.append(part)
        query = "&".join(params)
        parsed = parsed._replace(query=query)
    return parsed.geturl().rstrip("/")


def _clean_provider_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(str(x) for x in value if x)
    if isinstance(value, dict):
        value = value.get("text") or value.get("content") or value.get("summary") or json.dumps(value)
    return _clean_text(str(value))


def _domain_root(domain: str) -> str:
    domain = (domain or "").lower().removeprefix("www.")
    parts = [p for p in domain.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain


def _quality_for_domain(domain: str, title: str = "") -> tuple[str, float]:
    domain = (domain or "").lower().removeprefix("www.")
    root = _domain_root(domain)
    if domain in _PRIMARY_DOMAIN_HINTS or root in _PRIMARY_DOMAIN_HINTS or domain.endswith((".gov", ".edu")):
        return "primary", 1.0
    if domain in _HIGH_QUALITY_DOMAINS:
        return "high", 0.88
    if domain in _REFERENCE_DOMAINS:
        return "reference", 0.72
    title_low = (title or "").lower()
    if any(token in title_low for token in ("official", "documentation", "annual report", "investor relations", "research")):
        return "specialist", 0.68
    return "general", 0.52


def _extract_question_entities(query: str, subject: str) -> list[str]:
    q = _clean_text(query)
    found = []
    patterns = [
        r"(?:between|among)\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:\?|$)",
        r"^(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:\?|$)",
        r"(?:compare|comparison of)\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:\?|$)",
        r"(?:relationship between|relationship of)\s+(.+?)\s+(?:and)\s+(.+?)(?:\?|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, q, flags=re.I)
        if m:
            found.extend([_clean_text(m.group(1)), _clean_text(m.group(2))])
            break
    if not found and subject:
        found.append(subject)
    out=[]
    seen=set()
    for item in found:
        item=re.sub(r"^(the|a|an)\s+", "", item.strip(), flags=re.I).strip(" .?")
        if item and item.lower() not in seen and len(item) >= 2:
            out.append(item)
            seen.add(item.lower())
    return out[:4]


def _infer_intent(query: str) -> str:
    q = query.lower()
    if any(x in q for x in ("compare", "comparison", " vs ", " versus ", "difference between", "better than")):
        return "comparison"
    if any(x in q for x in ("best ", "top ", "recommended", "recommend me", "recommendation", "which is better", "worth buying", "under ₹", "under rs", "under ")):
        return "recommendation"
    if any(x in q for x in ("latest", "today", "this week", "this month", "recent", "breaking", "current news", "what happened")):
        return "current"
    if any(x in q for x in ("why did", "why has", "why is", "reason for", "cause of", "caused")):
        return "causal"
    if any(x in q for x in ("how does", "how do", "how is", "how it works", "architecture", "algorithm", "technical", "specification", "specs")):
        return "technical"
    if any(x in q for x in ("revenue", "profit", "market share", "valuation", "financial", "earnings", "stock")):
        return "finance"
    if any(x in q for x in ("relationship", "connected to", "partnered with", "acquired", "subsidiary", "owned by", "competitor")):
        return "relationship"
    if any(x in q for x in ("who is", "who was", "biography", "career", "born", "education", "background of")):
        return "person_or_biography"
    if any(x in q for x in ("history", "founded", "origin", "timeline", "started")):
        return "history"
    if any(x in q for x in ("products", "services", "features", "what does", "offerings")):
        return "products"
    return "overview"


def _better_subject(query: str) -> str:
    q = _clean_text(query)
    # Comparison / relationship queries need their first named entity as the subject.
    entities = _extract_question_entities(q, _infer_subject(q))
    if entities:
        return entities[0]
    subject = _infer_subject(q)
    subject = re.sub(r"\b(?:and|with|for)\s+(?:what|who|how|why)\b.*$", "", subject, flags=re.I).strip(" .?")
    return subject or q


def _entity_specific_sections(entity_type: str, intent: str) -> list[str]:
    if intent == "comparison":
        return ["comparison", "overview", "market", "products_services", "technology", "relationships"]
    if intent == "recommendation":
        return ["overview", "comparison", "products_services", "market", "current", "evidence"]
    if intent == "current":
        return ["current", "overview", "developments", "market", "relationships"]
    if intent == "causal":
        return ["causes", "current", "evidence", "context", "uncertainties"]
    if intent == "technical":
        return ["overview", "technology", "mechanism", "applications", "limitations", "developments"]
    if intent == "finance":
        return ["overview", "financials", "market", "developments", "uncertainties"]
    if intent == "relationship":
        return ["overview", "relationships", "context", "developments"]
    if intent == "person_or_biography":
        return ["overview", "background", "career", "achievements", "current", "relationships", "timeline"]
    if intent == "history":
        return ["overview", "history", "timeline", "developments", "relationships"]
    if intent == "products":
        return ["overview", "products_services", "technology", "applications", "market"]
    if entity_type == "company":
        return ["overview", "history", "products_services", "people", "technology", "market", "relationships", "developments"]
    if entity_type == "person":
        return ["overview", "background", "career", "achievements", "current", "relationships", "timeline"]
    if entity_type == "technology":
        return ["overview", "technology", "applications", "developments", "limitations", "relationships"]
    return ["overview", "context", "technology", "applications", "developments", "relationships"]


def _build_universal_plan(query: str, subject: str, entity_type: str) -> dict:
    intent = _infer_intent(query)
    entity_hints = _extract_question_entities(query, subject)
    sections = _entity_specific_sections(entity_type, intent)
    base = f'"{subject}"' if len(subject.split()) <= 8 else subject
    templates = {
        "overview": f"{base} overview what it is significance official information",
        "history": f"{base} history origin founding background timeline milestones",
        "timeline": f"{base} timeline major dates milestones",
        "products_services": f"{base} products services platforms offerings",
        "people": f"{base} CEO founders leadership executives key people",
        "background": f"{base} biography early life education background",
        "career": f"{base} career professional history roles",
        "achievements": f"{base} achievements awards records major accomplishments",
        "technology": f"{base} technology infrastructure technical design architecture",
        "mechanism": f"{base} how it works mechanism architecture explanation",
        "applications": f"{base} applications use cases ecosystem",
        "limitations": f"{base} limitations risks weaknesses challenges",
        "market": f"{base} market industry competitors competitive position",
        "financials": f"{base} revenue profit valuation financial results annual report",
        "relationships": f"{base} partnerships acquisitions subsidiaries parent company competitors relationships",
        "developments": f"{base} latest announcements launches acquisitions developments",
        "current": f"{base} latest current status recent news",
        "comparison": f"{base} comparison differences strengths weaknesses",
        "causes": f"{query} causes reasons evidence",
        "context": f"{base} context significance related entities",
        "uncertainties": f"{query} conflicting reports uncertainty disputed facts",
        "applications": f"{base} applications uses ecosystem",
        "evidence": f"{query} evidence authoritative sources",
    }
    plan=[]
    seen=set()
    # Always perform the direct user query first.
    plan.append((query, "direct"))
    seen.add("direct")
    for section in sections:
        q = templates.get(section)
        if not q or section in seen:
            continue
        plan.append((q, section))
        seen.add(section)
    # For general overview queries, add a freshness check but keep it optional in synthesis.
    if intent == "overview" and "current" not in seen:
        plan.append((f"{base} latest developments current status {datetime.now().year}", "current"))
    if intent == "overview" and "relationships" not in seen:
        plan.append((templates["relationships"], "relationships"))
    return {
        "intent": intent,
        "subject": subject,
        "entity_type": entity_type,
        "entity_hints": entity_hints,
        "sections": sections,
        "queries": plan[:10],
    }


def _provider_tavily(query: str, focus: str, limit: int) -> list[dict]:
    key = _env_key("TAVILY_API_KEY")
    if not key or TavilyClient is None:
        return []
    client = TavilyClient(api_key=key)
    intent = _infer_intent(query)
    topic = "news" if focus in {"current", "developments"} else "finance" if focus in {"financials", "market"} and any(x in query.lower() for x in ("revenue", "profit", "valuation", "stock")) else "general"
    kwargs = {
        "search_depth": "advanced" if focus in {"direct", "overview", "current", "relationships", "financials"} else "basic",
        "max_results": max(1, min(10, limit)),
        "include_answer": False,
        "include_raw_content": True,
        "topic": topic,
    }
    if intent == "current":
        kwargs["time_range"] = "month"
    response = client.search(query=query, **kwargs)
    out=[]
    for row in response.get("results", []):
        out.append({
            "provider": "tavily",
            "title": _clean_provider_text(row.get("title")),
            "url": row.get("url"),
            "snippet": _clean_provider_text(row.get("content")),
            "content": _clean_provider_text(row.get("raw_content") or row.get("content")),
            "provider_score": float(row.get("score") or 0),
            "published_date": row.get("published_date"),
            "search_focus": focus,
            "search_query": query,
        })
    return out


def _provider_exa(query: str, focus: str, limit: int) -> list[dict]:
    key = _env_key("EXA_API_KEY")
    if not key or Exa is None:
        return []
    exa = Exa(api_key=key)
    intent = _infer_intent(query)
    search_type = "deep-lite" if focus in {"direct", "comparison", "causes"} and intent in {"comparison", "causal"} else "auto"
    result = exa.search(
        query,
        type=search_type,
        num_results=max(1, min(10, limit)),
        contents={"highlights": True},
    )
    rows = getattr(result, "results", None) or []
    out=[]
    for row in rows:
        highlights = getattr(row, "highlights", None)
        text = getattr(row, "text", None)
        content = _clean_provider_text(highlights or text or "")
        out.append({
            "provider": "exa",
            "title": _clean_provider_text(getattr(row, "title", "")),
            "url": getattr(row, "url", ""),
            "snippet": content[:3000],
            "content": content,
            "provider_score": float(getattr(row, "score", 0) or 0),
            "published_date": getattr(row, "published_date", None),
            "search_focus": focus,
            "search_query": query,
        })
    return out


def _provider_serper(query: str, focus: str, limit: int) -> list[dict]:
    key = _env_key("SERPER_API_KEY")
    if not key or requests is None:
        return []
    endpoint = "https://google.serper.dev/news" if focus in {"current", "developments"} else "https://google.serper.dev/search"
    payload = {"q": query, "num": max(1, min(10, limit))}
    response = requests.post(
        endpoint,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    rows = data.get("news") if focus in {"current", "developments"} else data.get("organic")
    out=[]
    for row in rows or []:
        out.append({
            "provider": "serper",
            "title": _clean_provider_text(row.get("title")),
            "url": row.get("link") or row.get("url"),
            "snippet": _clean_provider_text(row.get("snippet") or row.get("description")),
            "content": _clean_provider_text(row.get("snippet") or row.get("description")),
            "provider_score": 0.65,
            "published_date": row.get("date"),
            "search_focus": focus,
            "search_query": query,
        })
    return out


def _run_provider(provider: str, query: str, focus: str, limit: int) -> list[dict]:
    if provider == "tavily":
        return _provider_tavily(query, focus, limit)
    if provider == "exa":
        return _provider_exa(query, focus, limit)
    if provider == "serper":
        return _provider_serper(query, focus, limit)
    return []


def _merge_source_metadata(source: dict) -> dict:
    url = _canonical_url(source.get("url", ""))
    domain = _source_domain(url)
    quality, quality_score = _quality_for_domain(domain, source.get("title", ""))
    title = _clean_text(source.get("title", ""))
    text = _clean_provider_text(source.get("content") or source.get("snippet"))
    return {
        **source,
        "url": url,
        "domain": domain,
        "title": title,
        "snippet": _clean_provider_text(source.get("snippet")),
        "content": text,
        "quality": quality,
        "quality_score": quality_score,
        "source_name": _domain_label(domain),
    }


def _source_entity_relevance(source: dict, subject: str, entity_hints: list[str]) -> float:
    hay = " ".join([source.get("title", ""), source.get("snippet", ""), source.get("content", "")[:5000]]).lower()
    target_terms = _query_terms(subject)
    if not target_terms:
        target_terms = [subject.lower()]
    exact = sum(1 for term in target_terms if term in hay)
    hint_hits = sum(1 for hint in entity_hints if hint and hint.lower() in hay)
    score = min(1.0, 0.35 + exact * 0.11 + hint_hits * 0.08)
    if subject.lower() in (source.get("title", "") or "").lower():
        score += 0.18
    if source.get("search_focus") == "direct":
        score += 0.08
    return round(min(score, 1.0), 3)


def _rank_universal_sources(sources: list[dict], query: str, subject: str, entity_hints: list[str]) -> list[dict]:
    now = datetime.now(timezone.utc)
    ranked=[]
    seen=set()
    for raw in sources:
        src=_merge_source_metadata(raw)
        url=src.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        relevance=_source_entity_relevance(src, subject, entity_hints)
        focus_bonus=0.06 if src.get("search_focus") != "direct" else 0.10
        provider_bonus=_PROVIDER_PRIORITY.get(src.get("provider"), 0.8) * 0.08
        quality=src.get("quality_score", 0.5)
        text_len=min(1.0, len(src.get("content", "")) / 2500)
        freshness=0.0
        date_text=str(src.get("published_date") or "")
        if date_text:
            try:
                dt=datetime.fromisoformat(date_text.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt=dt.replace(tzinfo=timezone.utc)
                age=(now-dt).days
                freshness=max(0.0, 1.0-min(age/365, 1.0))*0.08
            except Exception:
                pass
        score=relevance*0.48 + quality*0.30 + text_len*0.08 + provider_bonus + focus_bonus + freshness + float(src.get("provider_score") or 0)*0.06
        src["entity_relevance"]=relevance
        src["ranking_score"]=round(score, 4)
        src["retrieval"]="provider_content" if src.get("content") else "search_snippet"
        ranked.append(src)
    ranked.sort(key=lambda x: (-x["ranking_score"], -x.get("quality_score",0), x.get("domain", "")))
    return ranked


def _select_diverse_sources(sources: list[dict], target: int) -> list[dict]:
    selected=[]
    domains=set()
    providers=set()
    focuses=set()
    # First pass: breadth across providers, domains and research angles.
    for src in sources:
        if src.get("domain") in domains and len(selected) < min(target, 6):
            continue
        selected.append(src)
        domains.add(src.get("domain"))
        providers.add(src.get("provider"))
        focuses.add(src.get("search_focus"))
        if len(selected)>=target:
            break
    # Second pass: fill remaining with strongest evidence.
    if len(selected)<target:
        selected_urls={x.get("url") for x in selected}
        for src in sources:
            if src.get("url") in selected_urls:
                continue
            selected.append(src)
            selected_urls.add(src.get("url"))
            if len(selected)>=target:
                break
    return selected


def _fetch_known_page(url: str, max_chars: int = 18000) -> str:
    try:
        return _fetch_source_text(url, max_chars=max_chars)
    except Exception:
        return ""


def _enrich_universal_sources(sources: list[dict], exa_limit: int = 8) -> list[dict]:
    enriched=[dict(s) for s in sources]
    # Exa can cleanly retrieve already-known URLs. Use it when available for the
    # best sources; fall back to our dependency-free HTML extractor.
    exa_key=_env_key("EXA_API_KEY")
    if exa_key and Exa is not None:
        try:
            exa=Exa(api_key=exa_key)
            urls=[s.get("url") for s in enriched[:exa_limit] if s.get("url")]
            if urls:
                contents=exa.get_contents(urls, text=True)
                by_url={_canonical_url(getattr(r, "url", "")): r for r in (getattr(contents, "results", None) or [])}
                for src in enriched:
                    row=by_url.get(_canonical_url(src.get("url", "")))
                    if row is not None:
                        text=getattr(row, "text", None)
                        if text:
                            src["content"]=_clean_provider_text(text)[:24000]
                            src["retrieval"]="exa_contents"
        except Exception as exc:
            print("ENTQRA EXA CONTENT WARNING:", repr(exc))
    # Fill gaps with local HTTP extraction.
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(enriched)))) as executor:
        futures={executor.submit(_fetch_known_page, s.get("url", ""), 18000): i for i,s in enumerate(enriched) if len(s.get("content", "")) < 700}
        for future in as_completed(futures):
            i=futures[future]
            try:
                page=future.result()
            except Exception:
                page=""
            if page and len(page)>len(enriched[i].get("content", "")):
                enriched[i]["content"]=page
                enriched[i]["retrieval"]="full_page"
    for src in enriched:
        if len(src.get("content", ""))>=700 and src.get("retrieval") not in {"exa_contents", "full_page"}:
            src["retrieval"]="provider_content"
    return enriched


def _chunk_text(text: str, max_chars: int = 900) -> list[str]:
    text=_clean_text(text)
    if not text:
        return []
    pieces=_split_sentences(text)
    if not pieces:
        return [text[:max_chars]]
    chunks=[]
    current=[]
    length=0
    for sentence in pieces:
        if current and length+len(sentence)>max_chars:
            chunks.append(" ".join(current))
            current=[]
            length=0
        current.append(sentence)
        length+=len(sentence)+1
    if current:
        chunks.append(" ".join(current))
    return chunks[:80]


def _hybrid_retrieve_chunks(chunks: list[dict], query: str, top_k: int = 6) -> list[dict]:
    if not chunks:
        return []
    texts=[c.get("text", "") for c in chunks]
    scored=[]
    if TfidfVectorizer is not None and cosine_similarity is not None:
        try:
            matrix=TfidfVectorizer(ngram_range=(1,2), min_df=1, max_features=12000).fit_transform([query]+texts)
            sims=cosine_similarity(matrix[0:1], matrix[1:]).ravel()
        except Exception:
            sims=[0.0]*len(texts)
    else:
        qterms=set(_query_terms(query))
        sims=[]
        for text in texts:
            low=text.lower()
            sims.append(sum(1 for t in qterms if t in low)/max(1,len(qterms)))
    for idx, chunk in enumerate(chunks):
        base=float(sims[idx]) if idx<len(sims) else 0.0
        provider=float(chunk.get("provider_score") or 0)*0.10
        quality=float(chunk.get("quality_score") or 0.5)*0.25
        scored.append((base*0.60+quality+provider, chunk))
    scored.sort(key=lambda x:-x[0])
    selected=[]
    seen=set()
    for score, chunk in scored:
        key=_sentence_key(chunk.get("text", ""))
        if not key or key in seen:
            continue
        row=dict(chunk)
        row["rag_score"]=round(float(score),4)
        selected.append(row)
        seen.add(key)
        if len(selected)>=top_k:
            break
    return selected


def _build_evidence_chunks(sources: list[dict], subject: str) -> list[dict]:
    chunks=[]
    for src_index, src in enumerate(sources):
        content=src.get("content") or src.get("snippet") or ""
        for chunk in _chunk_text(content, 900):
            if not _is_clean_fact(chunk):
                continue
            chunks.append({
                "text": chunk,
                "source_index": src_index,
                "source_name": src.get("source_name"),
                "domain": src.get("domain"),
                "url": src.get("url"),
                "provider": src.get("provider"),
                "quality": src.get("quality"),
                "quality_score": src.get("quality_score", 0.5),
                "provider_score": src.get("provider_score", 0),
                "search_focus": src.get("search_focus", "direct"),
                "published_date": src.get("published_date"),
            })
    return chunks


def _select_section_evidence(chunks: list[dict], section: str, query: str, used_global: set[str], limit: int = 4) -> list[dict]:
    queries={
        "overview": f"{query} what is it identity purpose significance",
        "history": f"{query} history origin founding milestones",
        "timeline": f"{query} important dates milestones timeline",
        "products_services": f"{query} products services platforms offerings",
        "people": f"{query} founders CEO leadership executives",
        "background": f"{query} biography early life education background",
        "career": f"{query} career professional roles",
        "achievements": f"{query} achievements awards records",
        "technology": f"{query} technology architecture infrastructure",
        "mechanism": f"{query} how it works mechanism technical explanation",
        "applications": f"{query} applications uses ecosystem",
        "limitations": f"{query} limitations weaknesses risks challenges",
        "market": f"{query} market industry competitors business position",
        "financials": f"{query} revenue profit valuation financial results",
        "relationships": f"{query} relationships partnerships acquisitions subsidiaries competitors",
        "developments": f"{query} latest developments launches announcements",
        "current": f"{query} current status latest information",
        "comparison": query,
        "causes": query,
        "context": f"{query} context significance related entities",
        "uncertainties": query,
        "evidence": query,
    }
    retrieved=_hybrid_retrieve_chunks(chunks, queries.get(section, query), top_k=limit*3)
    selected=[]
    seen_domains=set()
    for item in retrieved:
        key=_sentence_key(item.get("text", ""))
        if not key or key in used_global:
            continue
        domain=item.get("domain")
        # Prefer source diversity within a section.
        if domain in seen_domains and len(selected)<limit-1:
            continue
        selected.append(item)
        used_global.add(key)
        seen_domains.add(domain)
        if len(selected)>=limit:
            break
    if len(selected)<limit:
        for item in retrieved:
            key=_sentence_key(item.get("text", ""))
            if not key or key in used_global:
                continue
            selected.append(item)
            used_global.add(key)
            if len(selected)>=limit:
                break
    return selected


def _format_evidence_item(item: dict, label: str | None = None) -> dict:
    return _item(
        item.get("text", ""),
        item.get("source_name"),
        item.get("domain"),
        item.get("url"),
        evidence_quality=item.get("quality"),
        provider=item.get("provider"),
        research_focus=item.get("search_focus"),
        rag_score=item.get("rag_score"),
        published_date=item.get("published_date"),
        label=label,
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    result=[]
    seen=set()
    for value in values:
        clean=_clean_text(value).strip()
        key=_sentence_key(clean)
        if clean and key and key not in seen:
            result.append(clean)
            seen.add(key)
    return result


def _compose_paragraph(items: list[dict], lead: str = "") -> str:
    texts=[_clean_text(x.get("text", "")) for x in items if x.get("text")]
    texts=_dedupe_strings(texts)
    if not texts:
        return lead.strip()
    body=" ".join(texts[:4])
    return (lead + (" " if lead and body else "") + body).strip()


def _extract_timeline(items: list[dict]) -> list[dict]:
    dated=[]
    for item in items:
        text=item.get("text", "")
        years=re.findall(r"\b(?:18|19|20)\d{2}\b", text)
        if years:
            dated.append((min(int(y) for y in years), item))
    dated.sort(key=lambda x:x[0])
    out=[]
    seen=set()
    for year,item in dated:
        key=_sentence_key(item.get("text", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append({"year":year,"text":item.get("text"),"source_name":item.get("source_name"),"url":item.get("url")})
    return out[:10]


def _extract_research_relationships(subject: str, evidence: list[dict]) -> list[dict]:
    relations=[]
    seen=set()
    patterns=[
        (r"(?:acquired|acquires|purchased|bought)\s+([A-Z][A-Za-z0-9& .'-]{2,80})", "acquired"),
        (r"(?:subsidiary of|owned by|parent company(?: of)?)\s+([A-Z][A-Za-z0-9& .'-]{2,80})", "subsidiary_of"),
        (r"(?:partnered with|partnership with|partners with)\s+([A-Z][A-Za-z0-9& .'-]{2,80})", "partnered_with"),
        (r"(?:competitor(?:s)?(?: include| is| are)?|competes with)\s+([A-Z][A-Za-z0-9& .'-]{2,80})", "competes_with"),
        (r"(?:founded by|co-founded by)\s+([A-Z][A-Za-z .'-]{2,80})", "founded_by"),
    ]
    for item in evidence:
        text=_clean_text(item.get("text", ""))
        for pattern, relation in patterns:
            m=re.search(pattern, text)
            if not m:
                continue
            target=_clean_text(m.group(1)).strip(" ,.;:")
            target=re.split(r"(?:\.|,\s+(?:which|and|who|the|a|an)\b)", target)[0].strip()
            if not target or len(target)<2:
                continue
            if target.lower() == subject.lower() or target.lower() in {"the company", "the organization"}:
                continue
            key=(subject.lower(), relation, target.lower())
            if key in seen:
                continue
            seen.add(key)
            relations.append({
                "source": subject,
                "target": target,
                "relationship_type": relation,
                "description": text,
                "source_name": item.get("source_name"),
                "domain": item.get("domain"),
                "url": item.get("url"),
                "confidence": "high" if item.get("quality") in {"primary", "high"} else "medium",
            })
    return relations[:12]


def _build_knowledge_graph(subject: str, relationships: list[dict]) -> dict:
    nodes=[{"id":"root","label":subject,"type":"subject","evidence_backed":True}]
    edges=[]
    seen_nodes={subject.lower()}
    for idx, rel in enumerate(relationships):
        target=rel.get("target") or ""
        if target.lower() not in seen_nodes:
            nodes.append({"id":f"entity-{len(nodes)}","label":target,"type":"related_entity","evidence_backed":True})
            seen_nodes.add(target.lower())
        target_id=next((n["id"] for n in nodes if n["label"].lower()==target.lower()), None)
        if target_id:
            edges.append({
                "id":f"edge-{idx+1}",
                "source":"root",
                "target":target_id,
                "label":rel.get("relationship_type","related_to"),
                "evidence_backed":True,
                "source_name":rel.get("source_name"),
                "url":rel.get("url"),
            })
    return {"nodes":nodes, "edges":edges}


def _calculate_universal_confidence(sources: list[dict], evidence: list[dict], conflicts: list[dict], plan: dict) -> dict:
    domains={s.get("domain") for s in sources if s.get("domain")}
    providers={s.get("provider") for s in sources if s.get("provider")}
    primary=sum(1 for s in sources if s.get("quality")=="primary")
    strong=sum(1 for s in sources if s.get("quality") in {"primary","high"})
    enriched=sum(1 for s in sources if s.get("retrieval") in {"exa_contents","full_page","provider_content"})
    focuses={s.get("search_focus") for s in sources if s.get("search_focus")}
    coverage=min(1.0, len(evidence)/12)
    domain_score=min(0.28, len(domains)*0.045)
    provider_score=min(0.10, len(providers)*0.035)
    primary_score=min(0.16, primary*0.035)
    strong_score=min(0.12, strong*0.02)
    retrieval_score=min(0.10, enriched*0.012)
    focus_score=min(0.10, len(focuses)*0.012)
    conflict_penalty=min(0.22, len(conflicts)*0.06)
    raw=min(1.0, 0.38+domain_score+provider_score+primary_score+strong_score+retrieval_score+focus_score+(coverage*0.16)-conflict_penalty)
    # Penalize thin research even when sources technically exist.
    if len(domains)<3 or len(evidence)<5:
        raw=min(raw, 0.67)
    if len(domains)>=5 and len(evidence)>=10 and not conflicts:
        raw=max(raw, 0.82)
    if raw>=0.84:
        level="high"
    elif raw>=0.70:
        level="medium-high"
    elif raw>=0.52:
        level="medium"
    else:
        level="low"
    return {
        "level":level,
        "score":round(raw,2),
        "rationale":"Confidence is earned from independent source diversity, provider agreement, primary-source coverage, retrieved-content depth, evidence coverage, research-angle coverage, and detected conflicts.",
        "independent_domains":len(domains),
        "providers":sorted(providers),
        "strong_sources":strong,
        "primary_sources":primary,
        "full_page_sources":enriched,
        "supporting_evidence":len(evidence),
        "research_angles":len(focuses),
        "conflicts":len(conflicts),
        "adaptive_research": bool(plan.get("adaptive_research")),
    }


def _build_conflicts_universal(evidence: list[dict]) -> list[dict]:
    # Conservative conflict detection for years/numeric facts.
    cues=("founded","established","launched","acquired","employees","revenue","market share","valuation","population")
    groups=defaultdict(list)
    for item in evidence:
        text=item.get("text", "").lower()
        cue=next((c for c in cues if c in text), None)
        if not cue:
            continue
        values=re.findall(r"\b(?:18|19|20)\d{2}\b|\b\d+(?:\.\d+)?%\b", text)
        if values:
            groups[cue].append((set(values), item))
    conflicts=[]
    for cue, rows in groups.items():
        values=set().union(*(vals for vals,_ in rows))
        if len(values)<2:
            continue
        domains={item.get("domain") for _,item in rows if item.get("domain")}
        if len(domains)<2:
            continue
        vals=sorted(values)
        conflicts.append({
            "type":"possible_fact_conflict",
            "fact":cue,
            "values":vals[:6],
            "sources":list(domains)[:4],
            "explanation":f"Independent sources report different values for {cue}. The difference may reflect dates, definitions, or a genuine disagreement; inspect the cited sources.",
        })
    return conflicts[:5]


def _build_dynamic_dossier(query: str, plan: dict, profile: dict, section_items: dict, sources: list[dict], evidence: list[dict], relationships: list[dict], confidence: dict, conflicts: list[dict], research_metrics: dict) -> dict:
    blocks=[]
    name=profile.get("name") or plan.get("subject") or "Research Topic"
    entity_type=profile.get("type") or plan.get("entity_type") or "topic"
    blocks.append({
        "id":"entity_header","title":"Entity Header","question":"What exactly are we researching?",
        "items":[],"data":profile,
    })
    answer=profile.get("answer", "")
    blocks.append({
        "id":"intelligence_answer","title":"EntQra Intelligence Answer","question":"What is the direct answer to the question?",
        "items":[_item(answer,"EntQra Intelligence Engine",extra_type="narrative_answer")],"answer":answer,
    })
    # Detailed description is distinct from the answer: it explains the entity rather than answering the query sentence-by-sentence.
    description_items=section_items.get("overview",[])[:3] + section_items.get("context",[])[:2]
    description=_compose_paragraph(description_items, lead=f"{name} is best understood as a {entity_type}. ")
    if description:
        blocks.append({"id":"detailed_description","title":"Detailed Description","question":"What is this entity, and what role does it play?","items":[_item(description,"EntQra synthesis",extra_type="description")]})
    findings=[]
    for section in plan.get("sections",[]):
        for item in section_items.get(section,[]):
            text=item.get("text","")
            if text and text not in findings:
                findings.append(text)
            if len(findings)>=6:
                break
        if len(findings)>=6:
            break
    blocks.append({"id":"key_findings","title":"Key Findings","question":"What are the most important discoveries?","items":[_item(x,"EntQra evidence synthesis",extra_type="finding") for x in findings[:6]],"findings":findings[:6]})
    blocks.append({
        "id":"evidence_overview","title":"Evidence Overview","question":"How strong is the research?","metrics":research_metrics,"confidence":confidence,
        "items":[
            _item(f"{research_metrics['source_count']} sources were analyzed across {research_metrics['independent_domains']} independent domains."),
            _item(f"{research_metrics['evidence_count']} distinct evidence items were retained after deduplication."),
            _item(f"{research_metrics['strong_source_count']} strong or primary sources contributed to the evidence base."),
            _item(f"Research covered {research_metrics['research_angles']} relevant angles for this query."),
        ],
    })
    for section in plan.get("sections",[]):
        items=section_items.get(section,[])
        if not items and section not in {"relationships","comparison","uncertainties"}:
            continue
        title_map={
            "overview":"Overview","history":"History & Background","timeline":"Timeline","products_services":"Products & Services",
            "people":"People / Leadership / Founders","background":"Background","career":"Career","achievements":"Achievements",
            "technology":"Technology / Operations","mechanism":"How It Works","applications":"Applications / Use Cases",
            "limitations":"Limitations / Risks","market":"Business / Market / Industry","financials":"Financial Information",
            "relationships":"Relationships / Connections","developments":"Major Developments","current":"Current Status / Recent Developments",
            "comparison":"Comparison","causes":"Causes / Explanation","context":"Context","uncertainties":"Uncertainties / Open Questions",
            "recommendation":"Recommendation Analysis",
            "evidence":"Evidence",
        }
        title=title_map.get(section, section.replace("_"," ").title())
        question_map={
            "overview":"What is it fundamentally?","history":"How did it come into existence and evolve?","products_services":"What does it provide?",
            "people":"Who are the important people connected to it?","technology":"What technology or operational systems define it?",
            "market":"Where does it fit in its wider market or field?","relationships":"What entities is it connected to?",
            "current":"What is the current state of the entity?","developments":"What recent developments matter?",
            "comparison":"How do the entities differ and where do they overlap?","causes":"What best explains the event or outcome?",
            "recommendation":"What options best fit the request and what evidence supports them?",
            "uncertainties":"What remains uncertain or disputed?",
        }
        block={"id":section,"title":title,"question":question_map.get(section,"What does the research show?"),"items":[_format_evidence_item(x) for x in items]}
        if section=="timeline":
            block["timeline"]=_extract_timeline(items)
        if section=="relationships":
            block["relationships"]=relationships
        if section=="comparison" and plan.get("entity_hints"):
            block["entities_compared"]=plan.get("entity_hints")
        blocks.append(block)
    if conflicts:
        blocks.append({"id":"contradictions","title":"Contradictions / Uncertainties","question":"What is uncertain or disputed?","conflicts":conflicts,"items":[_item(f"Possible conflict about {c['fact']}: {', '.join(c['values'])}. {c['explanation']}","Cross-source analysis",extra_type="uncertainty") for c in conflicts]})
    else:
        blocks.append({"id":"contradictions","title":"Contradictions / Uncertainties","question":"What is uncertain or disputed?","conflicts":[],"items":[_item("No material conflict was detected among the evidence selected for this research.","EntQra analysis")]})
    # Sources is a distinct block, not duplicated evidence prose.
    blocks.append({"id":"evidence","title":"Sources","question":"Where did EntQra obtain the information?","items":[
        _item(f"{s.get('source_name') or s.get('domain')} — {s.get('title') or 'Untitled source'}",s.get('source_name'),s.get('domain'),s.get('url'),source_quality=s.get('quality'),provider=s.get('provider'),retrieval=s.get('retrieval'),research_focus=s.get('search_focus'),relevance=s.get('entity_relevance'),published_date=s.get('published_date'))
        for s in sources
    ]})
    graph=_build_knowledge_graph(name, relationships)
    blocks.append({"id":"knowledge_graph","title":"Knowledge Graph","question":"How are the researched entities connected?","graph":graph,"items":[]})
    dossier={"profile":profile,"blocks":blocks,"sections":blocks,"method":"Universal multi-provider research using Tavily, Exa and Serper, evidence fusion, source ranking, section-specific RAG retrieval, deduplication and conflict analysis.","research_plan":plan}
    return dossier, graph


def _compose_universal_answer(query: str, plan: dict, profile: dict, section_items: dict, confidence: dict) -> str:
    name=profile.get("name") or plan.get("subject") or "this entity"
    entity_type=plan.get("entity_type") or "topic"
    overview=section_items.get("overview",[])[:3]
    history=section_items.get("history",[])[:2]
    products=section_items.get("products_services",[])[:2]
    tech=section_items.get("technology",[])[:2]
    people=section_items.get("people",[])[:2]
    market=section_items.get("market",[])[:2]
    current=section_items.get("current",[])[:2]
    comparison=section_items.get("comparison",[])[:3]
    recommendation=section_items.get("recommendation",[])[:4]
    causes=section_items.get("causes",[])[:3]
    relationships=section_items.get("relationships",[])[:2]
    paragraphs=[]
    if plan.get("intent")=="recommendation":
        if overview:
            paragraphs.append(_compose_paragraph(overview, lead=f"For the request {query.strip('?')}, EntQra first establishes the relevant options and context."))
        if recommendation or comparison:
            paragraphs.append(_compose_paragraph((recommendation or comparison)[:4], lead="The strongest evidence-supported options are"))
        if current or market:
            paragraphs.append(_compose_paragraph((current or market)[:2], lead="Current context also matters because"))
    elif plan.get("intent")=="comparison":
        if comparison:
            paragraphs.append(_compose_paragraph(comparison, lead=f"EntQra compared {', '.join(plan.get('entity_hints',[])[:2])} using evidence from multiple independent sources."))
        elif overview:
            paragraphs.append(_compose_paragraph(overview, lead="The comparison evidence indicates"))
    elif plan.get("intent")=="causal":
        if causes:
            paragraphs.append(_compose_paragraph(causes, lead=f"The available evidence points to several factors that help explain {query.strip('?')}."))
        elif current:
            paragraphs.append(_compose_paragraph(current, lead="The strongest current evidence indicates"))
    elif plan.get("intent")=="technical":
        if overview:
            paragraphs.append(_compose_paragraph(overview, lead=f"{name} is best understood as a {entity_type}."))
        if tech:
            paragraphs.append(_compose_paragraph(tech, lead="From a technical perspective,"))
    else:
        if overview:
            paragraphs.append(_compose_paragraph(overview, lead=f"{name} is best understood as a {entity_type}."))
        context=[]
        if history: context.extend(history)
        if products: context.extend(products)
        if people: context.extend(people)
        if market: context.extend(market)
        if context:
            paragraphs.append(_compose_paragraph(context, lead="The research shows that"))
        else:
            context=current+tech+relationships
            if context:
                paragraphs.append(_compose_paragraph(context, lead="Current and contextual evidence indicates"))
    # Final paragraph should be a synthesis, not a duplicate source dump.
    if market and plan.get("intent") not in {"comparison","causal"}:
        paragraphs.append(_compose_paragraph(market[:2], lead="In its wider market or field,"))
    elif current and plan.get("intent") != "current":
        paragraphs.append(_compose_paragraph(current[:2], lead="As of the latest retrieved evidence,"))
    answer="\n\n".join([p for p in paragraphs if p.strip()][:3]).strip()
    if not answer:
        return f"EntQra identified {name} as the primary research subject, but the available evidence was not strong enough to produce a reliable synthesized answer."
    return answer


def _exa_direct_answer(query: str) -> str:
    key=_env_key("EXA_API_KEY")
    if not key or Exa is None:
        return ""
    try:
        exa=Exa(api_key=key)
        response=exa.answer(query)
        answer=getattr(response,"answer",None) or ""
        return _clean_provider_text(answer)
    except Exception as exc:
        print("ENTQRA EXA ANSWER WARNING:",repr(exc))
        return ""


def _research_universal(query: str, requested_sources: int) -> dict:
    subject=_better_subject(query)
    entity_type=_infer_entity_type(subject, [], query)
    plan=_build_universal_plan(query, subject, entity_type)
    statuses=_provider_status()
    enabled=[p for p, ok in statuses.items() if ok]
    if not enabled:
        raise RuntimeError("No research provider is configured. Add Tavily, Exa, and/or Serper API keys to .env.")

    # Use all configured providers for the first pass. This is the critical
    # source-fusion change from the older DuckDuckGo-only implementation.
    provider_queries=[]
    for q, focus in plan["queries"]:
        for provider in enabled:
            provider_queries.append((provider, q, focus))

    collected=[]
    errors=[]
    per_query=max(2, min(4, requested_sources//2))
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(provider_queries)))) as executor:
        futures={executor.submit(_run_provider, provider, q, focus, per_query):(provider,q,focus) for provider,q,focus in provider_queries}
        for future in as_completed(futures):
            provider,q,focus=futures[future]
            try:
                collected.extend(future.result())
            except Exception as exc:
                errors.append(f"{provider}: {type(exc).__name__}: {exc}")

    ranked=_rank_universal_sources(collected, query, subject, plan.get("entity_hints",[]) or [subject])
    selected=_select_diverse_sources(ranked, requested_sources)

    # Refine entity type from the first research results, then rebuild the plan.
    refined_type=_infer_entity_type(subject, selected[:8], query)
    if refined_type != entity_type:
        entity_type=refined_type
        plan=_build_universal_plan(query, subject, entity_type)

    # Adaptive second pass: if evidence is thin, broaden the actual research.
    preliminary=_build_evidence_chunks(selected, subject)
    preliminary_evidence=_hybrid_retrieve_chunks(preliminary, query, top_k=8)
    distinct_domains={s.get("domain") for s in selected if s.get("domain")}
    if len(distinct_domains)<4 or len(preliminary_evidence)<6:
        plan["adaptive_research"]=True
        expansion=[
            (f"{subject} official facts key information", "official"),
            (f"{subject} independent analysis background", "context"),
            (f"{subject} latest developments {datetime.now().year}", "current"),
        ]
        expansion_queries=[]
        for q,focus in expansion:
            for provider in enabled:
                expansion_queries.append((provider,q,focus))
        with ThreadPoolExecutor(max_workers=min(12,max(1,len(expansion_queries)))) as executor:
            futures={executor.submit(_run_provider,provider,q,focus,4):(provider,q,focus) for provider,q,focus in expansion_queries}
            for future in as_completed(futures):
                provider,q,focus=futures[future]
                try:
                    collected.extend(future.result())
                except Exception as exc:
                    errors.append(f"adaptive {provider}: {type(exc).__name__}: {exc}")
        ranked=_rank_universal_sources(collected, query, subject, plan.get("entity_hints",[]) or [subject])
        selected=_select_diverse_sources(ranked, requested_sources)

    selected=_enrich_universal_sources(selected)
    selected=_rank_universal_sources(selected, query, subject, plan.get("entity_hints",[]) or [subject])
    selected=_select_diverse_sources(selected, requested_sources)

    chunks=_build_evidence_chunks(selected, subject)
    # Evidence synthesis is section-specific RAG: each section retrieves its own
    # chunks from the shared evidence corpus. A fact used in one block is globally
    # marked so it is not copied into another block unless absolutely necessary.
    used=set()
    section_items={}
    for section in plan["sections"]:
        limit=5 if section in {"overview","history","products_services","technology","market","relationships"} else 4
        section_items[section]=_select_section_evidence(chunks, section, query, used, limit=limit)

    # Gather a larger evidence set for confidence/claims, while still deduping.
    evidence=[]
    evidence_seen=set()
    for item in _hybrid_retrieve_chunks(chunks, query, top_k=min(24, max(10, requested_sources*2))):
        key=_sentence_key(item.get("text",""))
        if key and key not in evidence_seen:
            evidence.append(item)
            evidence_seen.add(key)
    for section in plan["sections"]:
        for item in section_items.get(section,[]):
            key=_sentence_key(item.get("text",""))
            if key and key not in evidence_seen:
                evidence.append(item)
                evidence_seen.add(key)
    evidence=evidence[:24]

    conflicts=_build_conflicts_universal(evidence)
    relationships=_extract_research_relationships(subject, evidence)
    local_profile_matches=[]
    # Local entity matching is used only to enrich metadata, never as the evidence source.
    try:
        local_profile_matches=[]
    except Exception:
        pass

    source_entity = None
    profile={
        "name": subject,
        "type": entity_type,
        "category": None,
        "description": None,
        "website": None,
        "subject": subject,
    }
    # Prefer local exact entity metadata if available; web evidence remains the research basis.
    if "_db" in globals():
        pass

    confidence=_calculate_universal_confidence(selected,evidence,conflicts,plan)
    metrics={
        "source_count":len(selected),
        "independent_domains":len({s.get("domain") for s in selected if s.get("domain")}),
        "strong_source_count":sum(1 for s in selected if s.get("quality") in {"primary","high"}),
        "primary_source_count":sum(1 for s in selected if s.get("quality")=="primary"),
        "evidence_count":len(evidence),
        "research_angles":len({s.get("search_focus") for s in selected if s.get("search_focus")}),
        "provider_count":len({s.get("provider") for s in selected if s.get("provider")}),
        "full_page_source_count":sum(1 for s in selected if s.get("retrieval") in {"exa_contents","full_page","provider_content"}),
        "errors":errors[:8],
    }
    local_answer=_compose_universal_answer(query,plan,profile,section_items,confidence)
    provider_answer=_exa_direct_answer(query) if plan.get("intent") in {"overview","comparison","technical","causal","history","products","person_or_biography"} else ""
    # Provider-generated answers are treated as a synthesis signal, not as raw evidence.
    if provider_answer and len(provider_answer)>=180:
        profile["answer"]=provider_answer
        profile["answer_method"]="Exa grounded answer + EntQra evidence verification"
    else:
        profile["answer"]=local_answer
        profile["answer_method"]="EntQra evidence synthesis"
    return {
        "query":query,
        "subject":subject,
        "entity_type":entity_type,
        "intent":plan["intent"],
        "plan":plan,
        "profile":profile,
        "sources":selected,
        "evidence":evidence,
        "section_items":section_items,
        "relationships":relationships,
        "conflicts":conflicts,
        "confidence":confidence,
        "metrics":metrics,
        "errors":errors,
    }


@app.get("/intelligence/providers")
def intelligence_providers(
    current_user: User = Depends(get_authenticated_user),
):
    """Report configured research providers without exposing API keys."""
    statuses=_provider_status()
    return {
        "message":"EntQra research provider status",
        "providers":{
            name:{"configured":bool(ok),"role":role}
            for name,ok,role in [
                ("tavily",statuses["tavily"],"AI-oriented search and source extraction"),
                ("exa",statuses["exa"],"semantic/entity search and clean web contents"),
                ("serper",statuses["serper"],"broad Google SERP discovery"),
            ]
        },
    }


@app.post("/intelligence/search")
def intelligence_search(
    request_data: IntelligenceSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """
    Universal EntQra research endpoint.

    The query is analyzed for intent and entity type, routed through all
    configured research providers, fused into an evidence corpus, re-ranked,
    deduplicated and retrieved section-by-section using a lightweight RAG
    layer. Only relevant sections are returned to the frontend.
    """
    query=request_data.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query cannot be empty")
    try:
        result=_research_universal(query, request_data.max_sources)
        profile=result["profile"]

        # Enrich exact local entity metadata if present, but never substitute it
        # for researched evidence.
        local_entities=_match_local_entities(db, query)
        exact=next((e for e in local_entities if (e.name or "").strip().lower()==result["subject"].lower()),None)
        if exact:
            profile["name"]=exact.name or profile["name"]
            profile["category"]=exact.category or profile.get("category")
            profile["website"]=exact.website or profile.get("website")
            profile["local_entity_id"]=exact.id
            if exact.description:
                profile["database_description"]=exact.description

        # Logo from local metadata, then favicon fallback from the official domain.
        logo_url=getattr(exact,"logo_url",None) if exact else None
        website=profile.get("website")
        if not logo_url and website:
            domain=_source_domain(_canonical_url(website))
            if domain:
                logo_url=f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
        profile["logo_url"]=logo_url

        confidence=result["confidence"]
        dossier,graph=_build_dynamic_dossier(
            query=query,
            plan=result["plan"],
            profile=profile,
            section_items=result["section_items"],
            sources=result["sources"],
            evidence=result["evidence"],
            relationships=result["relationships"],
            confidence=confidence,
            conflicts=result["conflicts"],
            research_metrics=result["metrics"],
        )

        # Fill the entity-header block explicitly.
        for block in dossier["blocks"]:
            if block.get("id")=="entity_header":
                header_items=[
                    _item(f"Identified entity: {profile.get('name') or result['subject']}"),
                    _item(f"Entity type: {profile.get('type') or result['entity_type']}"),
                ]
                if profile.get("category"):
                    header_items.append(_item(f"Category: {profile['category']}"))
                if profile.get("website"):
                    header_items.append(_item(f"Official / known website: {profile['website']}","EntQra entity metadata",url=profile['website']))
                block["items"]=header_items
                block["data"]={**profile}
                break

        public_sources=[{k:v for k,v in src.items() if k not in {"content","snippet"}} for src in result["sources"]]
        claims=[]
        for item in result["evidence"][:18]:
            claims.append({
                "text":item.get("text"),
                "supported_by":[{
                    "source_name":item.get("source_name"),
                    "domain":item.get("domain"),
                    "url":item.get("url"),
                    "provider":item.get("provider"),
                    "quality":item.get("quality"),
                }],
            })

        key_findings=[_clean_text(x.get("text","")) for x in result["section_items"].get("overview",[])[:2]]
        for section in result["plan"].get("sections",[]):
            for item in result["section_items"].get(section,[]):
                text=_clean_text(item.get("text",""))
                if text and text not in key_findings:
                    key_findings.append(text)
                if len(key_findings)>=6:
                    break
            if len(key_findings)>=6:
                break

        entities_payload=[]
        for entity in local_entities[:10]:
            entities_payload.append({
                "id":entity.id,
                "name":entity.name,
                "entity_type":entity.entity_type,
                "category":entity.category,
                "description":entity.description,
                "website":entity.website,
                "match_origin":"entqra_knowledge_graph",
            })

        return {
            "message":"EntQra universal intelligence research completed successfully",
            "query":query,
            "subject":result["subject"],
            "entity_type":result["entity_type"],
            "intent":result["intent"],
            "answer":profile["answer"],
            "confidence":confidence,
            "key_findings":key_findings[:6],
            "blocks":dossier["blocks"],
            "dossier":dossier,
            "claims":claims,
            "knowledge_graph":graph,
            "evidence":result["evidence"],
            "entities":entities_payload,
            "relationships":result["relationships"],
            "sources":public_sources,
            "research":{
                "provider":"Tavily + Exa + Serper",
                "research_mode":"universal_multi_provider_rag",
                "source_count":result["metrics"]["source_count"],
                "independent_domains":result["metrics"]["independent_domains"],
                "strong_source_count":result["metrics"]["strong_source_count"],
                "primary_source_count":result["metrics"]["primary_source_count"],
                "evidence_count":result["metrics"]["evidence_count"],
                "full_page_source_count":result["metrics"]["full_page_source_count"],
                "research_angles":result["metrics"]["research_angles"],
                "provider_count":result["metrics"]["provider_count"],
                "adaptive_research":bool(result["plan"].get("adaptive_research")),
                "evidence_mode":"provider_fusion + section_specific_rag",
                "conflicts_detected":bool(result["conflicts"]),
                "conflicts":result["conflicts"],
                "provider_errors":result["errors"][:8],
            },
        }
    except HTTPException:
        raise
    except RuntimeError as exc:
        print("ENTQRA RESEARCH PROVIDER ERROR:",repr(exc))
        raise HTTPException(status_code=502,detail={"message":"EntQra could not complete web research","error":str(exc)})
    except Exception as exc:
        print("ENTQRA UNIVERSAL SEARCH ERROR:",repr(exc))
        raise HTTPException(status_code=500,detail={"message":"EntQra universal intelligence search failed","error_type":type(exc).__name__,"error":str(exc)})


# ==================================================
# ENTQRA INTELLIGENCE ENGINE
# ==================================================

@app.get("/insights")
def get_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user)
):
    """
    Generate intelligence statistics and insights
    from the EntQra entity knowledge graph.
    """

    try:

        # --------------------------------------------------
        # LOAD DATABASE
        # --------------------------------------------------

        entities = db.query(Entity).all()

        relationships = db.query(
            EntityRelationship
        ).all()

        # --------------------------------------------------
        # BASIC COUNTS
        # --------------------------------------------------

        total_entities = len(entities)
        total_relationships = len(relationships)

        # --------------------------------------------------
        # ENTITY TYPES
        # --------------------------------------------------

        entity_type_counts = {}

        for entity in entities:

            entity_type = (
                entity.entity_type
                or "unknown"
            )

            entity_type_counts[entity_type] = (
                entity_type_counts.get(entity_type, 0) + 1
            )

        # --------------------------------------------------
        # CATEGORIES
        # --------------------------------------------------

        category_counts = {}

        for entity in entities:

            category = (
                entity.category
                or "uncategorized"
            )

            category_counts[category] = (
                category_counts.get(category, 0) + 1
            )

        # --------------------------------------------------
        # RELATIONSHIP TYPES
        # --------------------------------------------------

        relationship_type_counts = {}

        for relationship in relationships:

            relationship_type = (
                relationship.relationship_type
                or "unknown"
            )

            relationship_type_counts[
                relationship_type
            ] = (
                relationship_type_counts.get(
                    relationship_type,
                    0
                ) + 1
            )

        # --------------------------------------------------
        # ENTITY CONNECTION COUNTS
        # --------------------------------------------------

        connection_counts = {}

        for entity in entities:

            connection_counts[entity.id] = {
                "entity_id": entity.id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "category": entity.category,
                "connections": 0
            }

        for relationship in relationships:

            source_id = relationship.source_entity_id
            target_id = relationship.target_entity_id

            if source_id in connection_counts:
                connection_counts[
                    source_id
                ]["connections"] += 1

            if target_id in connection_counts:
                connection_counts[
                    target_id
                ]["connections"] += 1

        # --------------------------------------------------
        # MOST CONNECTED ENTITIES
        # --------------------------------------------------

        most_connected_entities = sorted(
            connection_counts.values(),
            key=lambda item: item["connections"],
            reverse=True
        )[:10]

        # --------------------------------------------------
        # NETWORK DENSITY
        # --------------------------------------------------

        if total_entities > 1:

            possible_relationships = (
                total_entities *
                (total_entities - 1)
            )

            network_density = (
                total_relationships /
                possible_relationships
            )

        else:

            network_density = 0

        # --------------------------------------------------
        # NETWORK STATUS
        # --------------------------------------------------

        if total_entities == 0:

            network_status = "EMPTY"

        elif total_relationships == 0:

            network_status = "DISCOVERY"

        elif total_relationships < total_entities:

            network_status = "EMERGING"

        else:

            network_status = "CONNECTED"

        # --------------------------------------------------
        # GENERATED INTELLIGENCE OBSERVATIONS
        # --------------------------------------------------

        observations = []

        if total_entities == 0:

            observations.append(
                "The intelligence database does not contain any entities yet."
            )

        else:

            observations.append(
                f"EntQra currently contains {total_entities} entities."
            )

        if total_relationships == 0:

            observations.append(
                "No relationships have been established between entities yet."
            )

        elif total_relationships == 1:

            observations.append(
                "The knowledge graph currently contains one entity relationship."
            )

        else:

            observations.append(
                f"The knowledge graph currently contains {total_relationships} relationships."
            )

        if most_connected_entities:

            top_entity = most_connected_entities[0]

            if top_entity["connections"] > 0:

                observations.append(
                    f'{top_entity["name"]} is currently the most connected entity with {top_entity["connections"]} connections.'
                )

        if len(entity_type_counts) > 0:

            most_common_type = max(
                entity_type_counts,
                key=entity_type_counts.get
            )

            observations.append(
                f'The most represented entity type is "{most_common_type}".'
            )

        # --------------------------------------------------
        # RESPONSE
        # --------------------------------------------------

        return {
            "message": "EntQra intelligence generated successfully",

            "summary": {
                "total_entities": total_entities,
                "total_relationships": total_relationships,
                "network_status": network_status,
                "network_density": round(
                    network_density,
                    4
                )
            },

            "entity_types": entity_type_counts,

            "categories": category_counts,

            "relationship_types": relationship_type_counts,

            "most_connected_entities": (
                most_connected_entities
            ),

            "observations": observations
        }

    except HTTPException:
        raise

    except Exception as e:

        print()
        print("==============================================")
        print("ENTQRA INTELLIGENCE ERROR")
        print("==============================================")

        print(
            "ERROR TYPE:",
            type(e).__name__
        )

        print(
            "ERROR MESSAGE:",
            str(e)
        )

        print(
            "FULL ERROR:",
            repr(e)
        )

        print("==============================================")
        print()

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to generate intelligence",
                "error_type": type(e).__name__,
                "error": str(e)
            }
        )           