"""SVG sanitizer and branding-leak scanner."""
import re
from typing import Optional

_ALLOWED_SVG_ELEMENTS = frozenset([
    'svg', 'g', 'path', 'rect', 'circle', 'polygon', 'ellipse', 'line',
    'polyline', 'text', 'tspan', 'defs', 'linearGradient', 'radialGradient',
    'stop', 'title', 'desc', 'clipPath', 'mask', 'use',
])

_FORBIDDEN_SVG_PATTERNS = [
    re.compile(r'<script', re.IGNORECASE),
    re.compile(r'<foreignObject', re.IGNORECASE),
    re.compile(r'\bon\w+\s*=', re.IGNORECASE),  # on* event handlers
    re.compile(r'xlink:href\s*=\s*["\']https?://', re.IGNORECASE),  # external refs
    re.compile(r'javascript:', re.IGNORECASE),
]

_FORBIDDEN_BRANDING_TOKENS = frozenset([
    'CitedBy',
    'citedby',
    'Cited by',
    'citedby.app',
    'hello@citedby.app',
])

_ALLOWED_FONTS = frozenset([
    'Inter', 'Roboto', 'Open Sans', 'Lato', 'Montserrat',
    'Poppins', 'Nunito', 'Source Sans Pro',
])

_HEX_COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


def sanitize_svg(svg_content: str) -> tuple[bool, str, list[str]]:
    """
    Sanitize SVG content.
    Returns (is_safe, sanitized_content, warnings).
    If is_safe=False, the SVG should be rejected.
    """
    warnings = []
    for pattern in _FORBIDDEN_SVG_PATTERNS:
        if pattern.search(svg_content):
            return False, '', [f'Forbidden SVG pattern detected: {pattern.pattern}']
    return True, svg_content, warnings


def scan_for_branding_leak(content: str) -> list[dict]:
    """
    Scan content for forbidden CitedBy branding tokens.
    Returns list of findings: [{"token": str, "location": str}]
    """
    findings = []
    for token in _FORBIDDEN_BRANDING_TOKENS:
        if token in content:
            findings.append({"token": token, "location": "content", "severity": "fail"})
    return findings


def validate_hex_color(color: str) -> bool:
    """Validate CSS hex color format."""
    return bool(_HEX_COLOR_RE.match(color))


def validate_font_family(font: str) -> bool:
    """Validate font family against allowlist."""
    return font in _ALLOWED_FONTS


def compute_wcag_contrast_ratio(hex_color: str, bg_color: str = '#FFFFFF') -> float:
    """
    Compute WCAG contrast ratio between two hex colors.
    Returns ratio (e.g., 4.5 for minimum AA compliance).
    """
    def relative_luminance(hex_c: str) -> float:
        r = int(hex_c[1:3], 16) / 255
        g = int(hex_c[3:5], 16) / 255
        b = int(hex_c[5:7], 16) / 255

        def linearize(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)

    lum1 = relative_luminance(hex_color)
    lum2 = relative_luminance(bg_color)
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def check_color_contrast(primary_hex: str, secondary_hex: str) -> list[str]:
    """
    Check color contrast for WCAG AA compliance (4.5:1 ratio).
    Returns list of warning messages (empty = ok).
    """
    warnings = []
    ratio = compute_wcag_contrast_ratio(primary_hex)
    if ratio < 4.5:
        warnings.append(f"Primary color {primary_hex} contrast ratio {ratio:.1f}:1 is below WCAG AA (4.5:1)")
    ratio2 = compute_wcag_contrast_ratio(secondary_hex)
    if ratio2 < 4.5:
        warnings.append(f"Secondary color {secondary_hex} contrast ratio {ratio2:.1f}:1 is below WCAG AA (4.5:1)")
    return warnings


def parse_csv_row(row: dict, row_index: int) -> tuple[Optional[dict], Optional[str]]:
    """
    Validate a CSV row for bulk business import.
    Returns (validated_data, error_message). If error, returns (None, message).
    """
    required = ['name', 'locality', 'city', 'category']
    for field in required:
        if not row.get(field, '').strip():
            return None, f"Row {row_index}: missing required field '{field}'"

    name = row['name'].strip()
    if len(name) > 200:
        return None, f"Row {row_index}: name exceeds 200 characters"
    if len(name) < 2:
        return None, f"Row {row_index}: name too short"

    import hashlib
    idempotency_key = hashlib.sha256(
        f"{name.lower()}:{row['locality'].strip().lower()}".encode()
    ).hexdigest()[:32]

    return {
        'name': name,
        'locality': row['locality'].strip(),
        'city': row['city'].strip(),
        'category': row['category'].strip(),
        'website_url': row.get('website_url', '').strip() or None,
        'phone': row.get('phone', '').strip() or None,
        'idempotency_key': idempotency_key,
    }, None
