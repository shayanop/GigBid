"""PII masking for logs, audit records and traces (R9, E4)."""

import re

_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),  # email
    re.compile(r"(?<![\w-])\+?\d(?:[\s().-]?\d){6,18}(?![\w-])"),  # phone / card / account
]


def redact(value):
    """Masks PII in every string inside value (str, dict, list); other types pass through."""
    if isinstance(value, str):
        for pattern in _PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
