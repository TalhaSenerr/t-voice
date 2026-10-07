"""Deterministic, conservative transcription cleanup without a language model."""

from __future__ import annotations

import re

# Preserve explicitly marked code, web links, email addresses and dotted names.
# This is intentionally conservative: a filler inside an address is real data.
_PROTECTED = re.compile(
    r"(```[\s\S]*?(?:```|\Z)|`[^`\n]*(?:`|\Z)|"
    r"(?:https?://|www\.)[^\s<>]+|"
    r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+|"
    r"(?<!\w)[\w-]+(?:\.[\w-]+)+(?:/[^\s<>]*)?)",
    re.IGNORECASE,
)
_FILLER = re.compile(
    r"(?<![\w@/\\+#-])(?<!\w\.)"
    r"(?:[eE]{2,}|[ıI]{2,}|[hH](?:[ıI])?[mM]{2,}|[uU][mM]+|[uU][hH]+|[eE][rR][mM]+)"
    r"(?![\w@/\\+#-]|\.[\w])"
    r"[ \t]*(?:[,;:]|\.{2,})?"
)


def _remove_fillers(text: str) -> str:
    result, count = _FILLER.subn("", text)
    if not count:
        return text
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"[ \t]+([,.;:!?])", r"\1", result)
    result = re.sub(r"[,;:]+[ \t]*([.!?])", r"\1", result)
    result = re.sub(r"(?m)^[ \t]*[,.;:!?]+[ \t]*", "", result)
    return result


def _replace_aliases(text: str, replacements: dict[str, str] | None) -> str:
    if not replacements:
        return text
    # One pass prevents A -> B -> C cascades and respects the user's exact map.
    aliases: dict[str, str] = {}
    for source, target in list(replacements.items())[:200]:
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        source, target = source.strip(), target.strip()
        if source and target and len(source) <= 100 and len(target) <= 100:
            aliases[source.casefold()] = target
    if not aliases:
        return text
    pattern = re.compile(
        r"(?<![\w@/\\+#-])(?:"
        + "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
        + r")(?![\w@/\\+#-])",
        re.IGNORECASE,
    )
    return pattern.sub(lambda match: aliases.get(match.group(0).casefold(), match.group(0)), text)


def clean_text(
    text: str,
    enabled: bool = True,
    replacements: dict[str, str] | None = None,
) -> str:
    """Remove unambiguous filler tokens and apply explicit whole-token aliases.

    ``enabled`` controls filler removal only. Explicit replacements still apply.
    Ordinary words such as ``şey``, ``yani``, ``like`` and ``well`` are retained.
    Protected code/URL/email spans are left byte-for-byte intact. Unmarked prose
    cannot distinguish an English hesitation from a technical term named "um";
    disable filler removal or put literal identifiers in backticks when needed.
    """
    if not isinstance(text, str):
        raise TypeError("Metin bir karakter dizisi olmalıdır.")
    if replacements is not None and not isinstance(replacements, dict):
        raise TypeError("Düzeltmeler bir sözlük olmalıdır.")
    pieces = _PROTECTED.split(text)
    for index in range(0, len(pieces), 2):
        plain = _remove_fillers(pieces[index]) if enabled else pieces[index]
        pieces[index] = _replace_aliases(plain, replacements)
    return "".join(pieces).strip()
