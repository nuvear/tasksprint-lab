"""Minimal, strict YAML-frontmatter reader for the kit's Markdown files.

Only the subset the supplied files use is accepted: ``key: value`` pairs at the
top level, one level of nesting (``metadata:`` followed by indented pairs), and
optionally quoted scalar strings. Anything else is an error rather than a guess.
No YAML library is used, so no tags, anchors or object construction exist.
"""
from __future__ import annotations

import re

_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]{0,63}):(?:\s+(.*))?$")


class FrontmatterError(ValueError):
    pass


def _scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    elif value[:1] in "[{&*!|>":
        raise FrontmatterError("unsupported YAML value form")
    return value


def split(text: str) -> tuple[dict[str, object], str]:
    """Return (frontmatter mapping, body). The file must start with a frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("missing frontmatter block")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise FrontmatterError("unterminated frontmatter block") from None
    meta: dict[str, object] = {}
    parent: dict[str, str] | None = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[:1] in (" ", "\t")
        m = _KEY.match(raw.strip())
        if not m:
            raise FrontmatterError("malformed frontmatter line")
        key, value = m.group(1), m.group(2)
        if indented:
            if parent is None or value is None:
                raise FrontmatterError("unexpected indentation in frontmatter")
            if key in parent:
                raise FrontmatterError("duplicate frontmatter key")
            parent[key] = _scalar(value)
            continue
        if key in meta:
            raise FrontmatterError("duplicate frontmatter key")
        if value is None or value.strip() == "":
            parent = {}
            meta[key] = parent
        else:
            parent = None
            meta[key] = _scalar(value)
    body = "\n".join(lines[end + 1:]).strip("\n") + "\n"
    return meta, body
