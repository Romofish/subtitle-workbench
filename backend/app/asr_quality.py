"""Conservative review hints for machine transcripts; never rewrite spoken text."""
from __future__ import annotations

import re
import unicodedata

QUALITY_RULE_VERSION = 1
REPETITION = re.compile(r'(.{1,32}?)\1{5,}', re.DOTALL)


def asr_quality_warnings(source_text: str, duration_ms: int) -> list[str]:
    """Flag long/repetitive output, not speakers, overlapping voices or accuracy.

    Six consecutive repeats covering at least 24 letters/marks is deliberately
    stricter than ordinary conversational repetition. Thai combining marks are
    retained. A warning is a listening prompt, never proof of hallucination.
    """
    normalized = unicodedata.normalize('NFC', source_text).casefold()
    compact = ''.join(ch for ch in normalized if ch.isalnum() or unicodedata.category(ch).startswith('M'))
    warnings = []
    if any(len(match.group(0)) >= 24 for match in REPETITION.finditer(compact)):
        warnings.append('asr_repetition')
    if duration_ms >= 12000:
        warnings.append('asr_long_segment')
    return warnings
