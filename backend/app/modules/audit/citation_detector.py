"""CitationDetector — 7-stage algorithm for detecting business citations in AI responses.

Stages:
1. Exact canonical name (word-boundary, case-insensitive) → 0.99
2. Alias match → 0.95
3. Phone number (E.164 normalised) → 0.99
4. Website domain (eTLD+1) → 0.95
5. Address fingerprint (locality + street tokens, fuzzy, ≥2 tokens) → 0.80
6. Fuzzy name (Jaro-Winkler ≥ 0.92 + locality corroboration) → 0.75
7. Composite (low-uniqueness name + 2+ corroborating signals) → 0.85

name_uniqueness_score gating:
- ≥ 0.7: stages 1-2 sufficient alone
- < 0.7: require at least one corroborating signal even for stage 1-2 matches
- < 0.4: require ≥2 corroborating signals

Confidence boosting: each corroborating signal adds +0.05, capped at 0.99.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.modules.audit.identity import BusinessIdentity

ALGORITHM_VERSION = "v1"

_NEGATIVE_CUES = frozenset(
    ["avoid", "scam", "complaints", "poor", "bad reviews", "worst", "terrible", "fraud", "fake", "cheating"]
)
_POSITIVE_CUES = frozenset(
    ["recommended", "top-rated", "trusted", "excellent", "best", "highly rated", "award-winning", "top rated"]
)

_SNIPPET_WINDOW = 200  # chars around match for polarity detection
_SNIPPET_LEN = 300     # max snippet returned


class MatchType(str, Enum):
    exact_name = "exact_name"
    alias = "alias"
    phone = "phone"
    website = "website"
    address = "address"
    fuzzy_name = "fuzzy_name"
    composite = "composite"


class Polarity(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


@dataclass(frozen=True)
class CitationResult:
    cited: bool
    confidence: float
    match_type: Optional[MatchType]
    snippet: str
    snippet_start_pos: int
    polarity: Polarity
    corroborating_signals: list[str]
    competitors_mentioned: list[str]
    algorithm_version: str


def _normalize(text: str) -> str:
    """Lower-case, collapse whitespace, strip diacritics."""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def _jaro_winkler(s1: str, s2: str, p: float = 0.1) -> float:
    """Pure-Python Jaro-Winkler similarity."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_dist = max(len1, len2) // 2 - 1
    match_dist = max(match_dist, 0)

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_dist)
        end = min(i + match_dist + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3

    # Winkler prefix bonus
    prefix = 0
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    return jaro + prefix * p * (1 - jaro)


def _detect_polarity(text: str, pos: int) -> Polarity:
    """Detect polarity in a ±SNIPPET_WINDOW window around position pos."""
    start = max(0, pos - _SNIPPET_WINDOW)
    end = min(len(text), pos + _SNIPPET_WINDOW)
    window = text[start:end].lower()
    for cue in _NEGATIVE_CUES:
        if cue in window:
            return Polarity.negative
    for cue in _POSITIVE_CUES:
        if cue in window:
            return Polarity.positive
    return Polarity.neutral


def _extract_snippet(text: str, pos: int) -> tuple[str, int]:
    """Extract a snippet around pos; return (snippet, snippet_start_pos)."""
    start = max(0, pos - 50)
    end = min(len(text), pos + _SNIPPET_LEN - 50)
    return text[start:end], start


def _phone_tokens(text: str) -> list[str]:
    """Extract phone-like strings (digits, +, spaces, dashes) from text."""
    return re.findall(r"[\+]?\d[\d\s\-]{7,15}\d", text)


def _normalize_phone_loose(raw: str) -> str:
    """Strip all non-digit except leading + for comparison."""
    raw = raw.strip()
    if raw.startswith("+"):
        return "+" + re.sub(r"\D", "", raw[1:])
    return re.sub(r"\D", "", raw)


def _find_competitors(text: str, competitors: list[str]) -> list[str]:
    """Return names of competitors mentioned in text."""
    found = []
    text_lower = text.lower()
    for comp in competitors:
        pattern = r"\b" + re.escape(_normalize(comp)) + r"\b"
        if re.search(pattern, text_lower):
            found.append(comp)
    return found


class CitationDetector:
    """7-stage citation detection algorithm."""

    def __init__(self, competitors: list[str] | None = None) -> None:
        self._competitors: list[str] = competitors or []

    def detect(self, text: str, identity: BusinessIdentity) -> CitationResult:
        """Run all 7 stages and return a CitationResult."""
        text_lower = text.lower()
        corroborating: list[str] = []
        competitors_mentioned = _find_competitors(text, self._competitors)

        # Pre-compute corroborating signals for all stages
        corroborating = self._gather_corroborating_signals(text, text_lower, identity)

        # Stage 1: exact canonical name
        result = self._stage_exact_name(text, text_lower, identity, corroborating)
        if result is not None:
            return self._finalize(result, text, competitors_mentioned, corroborating)

        # Stage 2: alias match
        result = self._stage_alias(text, text_lower, identity, corroborating)
        if result is not None:
            return self._finalize(result, text, competitors_mentioned, corroborating)

        # Stage 3: phone number
        result = self._stage_phone(text, identity, corroborating)
        if result is not None:
            return self._finalize(result, text, competitors_mentioned, corroborating)

        # Stage 4: website domain
        result = self._stage_website(text, text_lower, identity, corroborating)
        if result is not None:
            return self._finalize(result, text, competitors_mentioned, corroborating)

        # Stage 5: address fingerprint
        result = self._stage_address(text, text_lower, identity, corroborating)
        if result is not None:
            return self._finalize(result, text, competitors_mentioned, corroborating)

        # Stage 6: fuzzy name
        result = self._stage_fuzzy_name(text, text_lower, identity, corroborating)
        if result is not None:
            return self._finalize(result, text, competitors_mentioned, corroborating)

        # Stage 7: composite
        result = self._stage_composite(text, text_lower, identity, corroborating)
        if result is not None:
            return self._finalize(result, text, competitors_mentioned, corroborating)

        # Not cited
        return CitationResult(
            cited=False,
            confidence=0.0,
            match_type=None,
            snippet="",
            snippet_start_pos=0,
            polarity=Polarity.neutral,
            corroborating_signals=[],
            competitors_mentioned=competitors_mentioned,
            algorithm_version=ALGORITHM_VERSION,
        )

    def _gather_corroborating_signals(
        self, text: str, text_lower: str, identity: BusinessIdentity
    ) -> list[str]:
        """Collect all corroborating signals present in text (used for gating)."""
        signals: list[str] = []

        # Phone signal
        if identity.phone_e164:
            phone_norm = _normalize_phone_loose(identity.phone_e164)
            phone_digits = phone_norm.lstrip("+")
            for raw in _phone_tokens(text):
                candidate = _normalize_phone_loose(raw)
                candidate_digits = candidate.lstrip("+")
                if (
                    candidate == phone_norm
                    or candidate_digits == phone_digits
                    or phone_digits.endswith(candidate_digits)
                    or candidate_digits.endswith(phone_digits[-10:])
                ):
                    signals.append("phone")
                    break

        # Website signal
        if identity.website_etld_plus_one and identity.website_etld_plus_one in text_lower:
            signals.append("website")

        # Locality signal
        if identity.primary_locality:
            if _normalize(identity.primary_locality) in text_lower:
                signals.append("locality")

        # City signal
        if identity.primary_city:
            if _normalize(identity.primary_city) in text_lower:
                signals.append("city")

        # Alias signals (for corroboration beyond alias match itself)
        for alias in identity.aliases:
            pattern = r"\b" + re.escape(alias.text_normalized) + r"\b"
            if re.search(pattern, text_lower):
                signals.append(f"alias:{alias.text}")
                break  # one alias is enough for corroboration signal

        return signals

    def _passes_uniqueness_gate(
        self, identity: BusinessIdentity, corroborating: list[str]
    ) -> bool:
        """Check if uniqueness gating passes based on name_uniqueness_score."""
        score = identity.name_uniqueness_score
        if score >= 0.7:
            return True  # stages 1-2 sufficient alone
        if score < 0.4:
            return len(corroborating) >= 2  # need ≥2 corroborating signals
        # 0.4 <= score < 0.7: need at least 1
        return len(corroborating) >= 1

    def _boost_confidence(self, base: float, corroborating: list[str]) -> float:
        """Add +0.05 per corroborating signal, capped at 0.99."""
        return min(0.99, base + len(corroborating) * 0.05)

    def _stage_exact_name(
        self,
        text: str,
        text_lower: str,
        identity: BusinessIdentity,
        corroborating: list[str],
    ) -> Optional[tuple[float, MatchType, int]]:
        pattern = r"\b" + re.escape(identity.name_normalized) + r"\b"
        m = re.search(pattern, text_lower)
        if m:
            if not self._passes_uniqueness_gate(identity, corroborating):
                return None  # gated out
            pos = m.start()
            conf = self._boost_confidence(0.99, corroborating)
            return conf, MatchType.exact_name, pos
        return None

    def _stage_alias(
        self,
        text: str,
        text_lower: str,
        identity: BusinessIdentity,
        corroborating: list[str],
    ) -> Optional[tuple[float, MatchType, int]]:
        for alias in identity.aliases:
            pattern = r"\b" + re.escape(alias.text_normalized) + r"\b"
            m = re.search(pattern, text_lower)
            if m:
                if not self._passes_uniqueness_gate(identity, corroborating):
                    return None
                pos = m.start()
                conf = self._boost_confidence(0.95, corroborating)
                return conf, MatchType.alias, pos
        return None

    def _stage_phone(
        self,
        text: str,
        identity: BusinessIdentity,
        corroborating: list[str],
    ) -> Optional[tuple[float, MatchType, int]]:
        if not identity.phone_e164:
            return None
        phone_norm = _normalize_phone_loose(identity.phone_e164)
        # strip leading + for suffix comparison
        phone_digits = phone_norm.lstrip("+")
        for raw in _phone_tokens(text):
            candidate = _normalize_phone_loose(raw)
            candidate_digits = candidate.lstrip("+")
            # Match if exact, or if one is a suffix of the other (national vs E.164)
            if (
                candidate == phone_norm
                or candidate_digits == phone_digits
                or phone_digits.endswith(candidate_digits)
                or candidate_digits.endswith(phone_digits[-10:])  # last 10 digits
            ):
                pos = text.find(raw)
                conf = self._boost_confidence(0.99, [s for s in corroborating if s != "phone"])
                return conf, MatchType.phone, pos
        return None

    def _stage_website(
        self,
        text: str,
        text_lower: str,
        identity: BusinessIdentity,
        corroborating: list[str],
    ) -> Optional[tuple[float, MatchType, int]]:
        if not identity.website_etld_plus_one:
            return None
        domain = identity.website_etld_plus_one
        pos = text_lower.find(domain)
        if pos >= 0:
            conf = self._boost_confidence(0.95, [s for s in corroborating if s != "website"])
            return conf, MatchType.website, pos
        return None

    def _stage_address(
        self,
        text: str,
        text_lower: str,
        identity: BusinessIdentity,
        corroborating: list[str],
    ) -> Optional[tuple[float, MatchType, int]]:
        """Address fingerprint: locality + street tokens, ≥2 token matches."""
        if not identity.primary_locality and not identity.primary_city:
            return None

        address_tokens: list[str] = []
        if identity.primary_locality:
            address_tokens.extend(_normalize(identity.primary_locality).split())
        if identity.primary_city:
            address_tokens.extend(_normalize(identity.primary_city).split())

        # Remove very short tokens
        address_tokens = [t for t in address_tokens if len(t) > 2]
        if len(address_tokens) < 2:
            return None

        matched_tokens = []
        first_pos = len(text)
        for token in address_tokens:
            pos = text_lower.find(token)
            if pos >= 0:
                matched_tokens.append(token)
                first_pos = min(first_pos, pos)

        if len(matched_tokens) >= 2:
            conf = self._boost_confidence(0.80, corroborating)
            return conf, MatchType.address, first_pos
        return None

    def _stage_fuzzy_name(
        self,
        text: str,
        text_lower: str,
        identity: BusinessIdentity,
        corroborating: list[str],
    ) -> Optional[tuple[float, MatchType, int]]:
        """Fuzzy name: Jaro-Winkler ≥ 0.92 + locality corroboration."""
        name = identity.name_normalized
        if not name:
            return None

        # Check if locality/city is corroborated
        has_locality = "locality" in corroborating or "city" in corroborating
        if not has_locality:
            return None

        # Slide a window over words in text
        words = text_lower.split()
        name_words = name.split()
        window_size = len(name_words)
        if window_size == 0:
            return None

        best_score = 0.0
        best_start = 0
        # Try sliding windows of window_size words
        for i in range(len(words) - window_size + 1):
            candidate = " ".join(words[i:i + window_size])
            score = _jaro_winkler(name, candidate)
            if score > best_score:
                best_score = score
                # Approximate position
                best_start = text_lower.find(candidate[:min(len(candidate), 20)])

        if best_score >= 0.92:
            conf = self._boost_confidence(0.75, corroborating)
            return conf, MatchType.fuzzy_name, max(0, best_start)
        return None

    def _stage_composite(
        self,
        text: str,
        text_lower: str,
        identity: BusinessIdentity,
        corroborating: list[str],
    ) -> Optional[tuple[float, MatchType, int]]:
        """Composite: low uniqueness name + ≥2 corroborating signals."""
        if identity.name_uniqueness_score >= 0.7:
            return None  # not applicable for high-uniqueness names
        if len(corroborating) < 2:
            return None

        # Name must appear somewhere (even partial)
        name_parts = identity.name_normalized.split()
        if not name_parts:
            return None

        matched_parts = [p for p in name_parts if p in text_lower and len(p) > 2]
        if not matched_parts:
            return None

        # Find first matching position
        pos = min(text_lower.find(p) for p in matched_parts if text_lower.find(p) >= 0)
        conf = self._boost_confidence(0.85, corroborating)
        return conf, MatchType.composite, pos

    def _finalize(
        self,
        detection: tuple[float, MatchType, int],
        text: str,
        competitors_mentioned: list[str],
        corroborating: list[str] | None = None,
    ) -> CitationResult:
        confidence, match_type, pos = detection
        snippet, snippet_start = _extract_snippet(text, pos)
        polarity = _detect_polarity(text, pos)
        return CitationResult(
            cited=True,
            confidence=min(0.99, confidence),
            match_type=match_type,
            snippet=snippet,
            snippet_start_pos=snippet_start,
            polarity=polarity,
            corroborating_signals=list(corroborating) if corroborating else [],
            competitors_mentioned=competitors_mentioned,
            algorithm_version=ALGORITHM_VERSION,
        )
