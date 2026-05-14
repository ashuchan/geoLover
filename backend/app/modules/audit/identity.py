"""BusinessIdentity value object — not persisted to DB directly.

Built from business profile data and used by CitationDetector.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field


def _normalize_name(text: str) -> str:
    """Lower-case, collapse whitespace, strip diacritics."""
    # Strip diacritics (NFD decompose, remove combining chars)
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lower case and collapse whitespace
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def _etld_plus_one(url_or_domain: str) -> str | None:
    """Extract eTLD+1 from a URL or domain, e.g. 'https://www.sharmadental.in' → 'sharmadental.in'."""
    if not url_or_domain:
        return None
    # Strip scheme
    domain = re.sub(r"^https?://", "", url_or_domain, flags=re.IGNORECASE)
    # Strip path / query
    domain = domain.split("/")[0].split("?")[0].split("#")[0].lower()
    # Strip port
    domain = re.sub(r":\d+$", "", domain)
    # Strip www.
    domain = re.sub(r"^www\.", "", domain)
    if not domain:
        return None
    return domain


def _build_signal_set(
    name_normalized: str,
    aliases_normalized: list[str],
    phone_e164: str | None,
    website_etld: str | None,
    locality: str | None,
    city: str | None,
) -> set[str]:
    tokens: set[str] = set()
    # Add name tokens
    tokens.update(name_normalized.split())
    for alias in aliases_normalized:
        tokens.update(alias.split())
    if phone_e164:
        tokens.add(phone_e164)
    if website_etld:
        tokens.add(website_etld)
    if locality:
        tokens.update(_normalize_name(locality).split())
    if city:
        tokens.update(_normalize_name(city).split())
    return tokens


@dataclass(frozen=True)
class NormalisedAlias:
    text: str
    text_normalized: str
    alias_type: str


@dataclass
class BusinessIdentity:
    """Value object representing a business's full identity for citation matching."""

    business_id: uuid.UUID
    canonical_name: str
    name_normalized: str  # lower-case, whitespace-collapsed, diacritic-stripped
    aliases: list[NormalisedAlias] = field(default_factory=list)
    phone_e164: str | None = None  # normalised E.164
    website_etld_plus_one: str | None = None  # e.g. "sharmadental.in"
    primary_locality: str | None = None
    primary_city: str | None = None
    name_uniqueness_score: float = 0.5  # 0-1
    keywords: list[str] = field(default_factory=list)
    identity_signal_set: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.identity_signal_set:
            self.identity_signal_set = _build_signal_set(
                self.name_normalized,
                [a.text_normalized for a in self.aliases],
                self.phone_e164,
                self.website_etld_plus_one,
                self.primary_locality,
                self.primary_city,
            )

    @classmethod
    def build(
        cls,
        *,
        business_id: uuid.UUID,
        canonical_name: str,
        aliases: list[NormalisedAlias] | None = None,
        phone_e164: str | None = None,
        website_url: str | None = None,
        website_etld_plus_one: str | None = None,  # accepted as alternative to website_url
        primary_locality: str | None = None,
        primary_city: str | None = None,
        name_uniqueness_score: float = 0.5,
        keywords: list[str] | None = None,
    ) -> "BusinessIdentity":
        name_normalized = _normalize_name(canonical_name)
        # Accept either website_url (extract eTLD+1) or website_etld_plus_one directly
        if website_etld_plus_one is not None:
            website_etld = website_etld_plus_one
        elif website_url is not None:
            website_etld = _etld_plus_one(website_url)
        else:
            website_etld = None
        return cls(
            business_id=business_id,
            canonical_name=canonical_name,
            name_normalized=name_normalized,
            aliases=aliases or [],
            phone_e164=phone_e164,
            website_etld_plus_one=website_etld,
            primary_locality=primary_locality,
            primary_city=primary_city,
            name_uniqueness_score=name_uniqueness_score,
            keywords=keywords or [],
        )
