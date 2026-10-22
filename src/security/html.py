"""HTML neutralization for untrusted web text (WS-12 · WS-15).

A job board returns HTML, and that HTML is stored, returned by the API, fed
to the model, and written into the rendered resume. Two of those are
script-execution contexts:

- The API returns descriptions inside a JSON body. A JSON body is not
  executed — but a browser that is allowed to *sniff* the response, or any
  consumer that renders a description as HTML, will execute it. The
  ``X-Content-Type-Options: nosniff`` header (see
  :mod:`src.api.middleware`) closes the sniffing case; this module closes
  the rendering case, and closes it at the **source**: the hostile text
  never enters the system in a form that could be executed.
- The tailored resume is a DOCX, not a browser, so it is not an XSS sink —
  but the *research* and *tailoring* stages put listing text in front of a
  model, and HTML in a prompt is both noise and a smuggling channel.

The sanitization is deliberately simple and **deterministic**: strip the
elements whose *content* is code or style, strip every remaining tag, then
decode the entities. The order matters and is the whole point:

1. **Elements with dangerous content are removed with their content.**
   ``<script>alert(1)</script>`` must not leave ``alert(1)`` behind as
   visible text, and ``<style>`` must not smuggle CSS. The content between
   the tags is dropped, not just the tags.
2. **Every remaining tag is removed.** What is left is text, not markup.
3. **Entities are decoded last.** Decoding *first* would let
   ``&lt;script&gt;`` become a real tag; decoding after the tags are gone
   cannot, because there are no tags left to decode into. The output is
   then re-checked for any tag that decoding might have revealed.

The result is plain text: it is safe to place in an HTML context, safe to
put in a prompt, and still a faithful reading of the posting.

**Why this is a scanner and not a set of regular expressions (WS-15).**
The first implementation stripped the dangerous blocks with a pattern like
``<script\\b[^>]*>.*?</script>`` and the ``.*?`` was *lazy*, with
``re.DOTALL``. A lazy quantifier is not free: the engine retries it at
every position where the literal prefix can match, so the cost of the
whole scan is quadratic in the length of the input. Measured on the old
implementation: 128 KB of ``<script>`` took **25 seconds** of CPU, and the
length cap was applied *after* the neutralization, so it did not help. One
hostile board could buy minutes of a refresh thread with a single field.

The scanner below cannot retry, because it advances a cursor: it finds the
next ``<``, decides what it is, and jumps past it. The output, the order
of the steps, and the guarantee — **no tag survives** — are unchanged; the
cost is now linear in the length of the input. A scanner also gets the
unterminated cases right for free: an unterminated comment swallows the
rest of the text, which is what a browser does with it, and an unterminated
dangerous element keeps its *content* (the text) but loses its tag, which
is what a browser does with it too.
"""

from __future__ import annotations

import html
import re

__all__ = ["escape_for_html", "neutralize_html", "strip_dangerous_html"]

#: Elements whose **content** is code, style, or embedded foreign content.
#: The content between the opening and the closing tag is dropped entirely.
_DANGEROUS_BLOCKS = frozenset(
    {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "applet",
        "noscript",
        "template",
        "svg",
        "math",
        "frame",
        "frameset",
        "base",
        "link",
        "meta",
    }
)

#: The most characters the neutralizer will read from one field.
#:
#: The neutralizer is linear now, so this is not a performance fix — it is a
#: bound on how much work one hostile field can ask for, and on how much
#: memory the intermediate copy can take. A description is capped at 20,000
#: characters by the contract, so a megabyte of input is already generous
#: by three orders of magnitude; anything past it is dropped.
MAX_NEUTRALIZE_INPUT_CHARS = 1_000_000

#: The name at the start of a tag. Deliberately ``[A-Za-z][A-Za-z0-9]*`` and
#: nothing more: a name stops at the first character that cannot be part of
#: it, so ``<script src=x>`` is the ``script`` element and ``<script-x>``
#: is not — the same reading the old ``\b``-anchored pattern gave.
_TAG_NAME_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9]*)")

#: The closing tag of a dangerous element, per element name. Compiled once
#: and kept, because the names come from a fixed set.
_CLOSING_PATTERNS: dict[str, re.Pattern[str]] = {}


def _closing_pattern(name: str) -> re.Pattern[str]:
    """The compiled ``</name>`` pattern for the dangerous element *name*."""
    pattern = _CLOSING_PATTERNS.get(name)
    if pattern is None:
        pattern = re.compile(r"</\s*" + re.escape(name) + r"\s*>", re.IGNORECASE)
        _CLOSING_PATTERNS[name] = pattern
    return pattern


def _scan(text: str, *, drop_dangerous_content: bool) -> str:
    """Remove every tag from *text* in a single linear pass.

    Args:
        text: The text to scan.
        drop_dangerous_content: When true, the **content** of a dangerous
            element is dropped with the element. When false, only the tags
            are removed and the content is kept — which is what the second
            pass after the entity decode needs, so that a decoded
            ``&lt;script&gt;alert(1)&lt;/script&gt;`` loses its tags
            without silently eating the sentence around them.

    Returns:
        The text with the tags removed.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    # The dangerous element names already searched for with no closing tag
    # found. The cursor only moves forward, so a name that had no closing
    # tag after its first occurrence has none after any later occurrence
    # either — and remembering that is what keeps this pass linear when a
    # board sends ten thousand unterminated ``<script>`` tags.
    unclosed: set[str] = set()

    while True:
        start = text.find("<", index)
        if start < 0:
            out.append(text[index:])
            break
        out.append(text[index:start])

        # A comment, a CDATA section, or a processing instruction: none of
        # them is content, and each runs to its own terminator.
        if text.startswith("<!--", start):
            end = text.find("-->", start + 4)
            out.append(" ")
            index = length if end < 0 else end + 3
            continue
        if text.startswith("<![CDATA[", start):
            end = text.find("]]>", start + 9)
            out.append(" ")
            index = length if end < 0 else end + 3
            continue
        if text.startswith("<?", start):
            end = text.find("?>", start + 2)
            out.append(" ")
            index = length if end < 0 else end + 2
            continue

        end = text.find(">", start)
        if end < 0:
            # No closing angle bracket: this ``<`` is ordinary text.
            out.append("<")
            index = start + 1
            continue

        match = _TAG_NAME_RE.match(text, start)
        name = match.group(1).lower() if match else ""
        if drop_dangerous_content and name in _DANGEROUS_BLOCKS and name not in unclosed:
            closing = _closing_pattern(name).search(text, end + 1)
            if closing is not None:
                # The element and its content go together.
                out.append(" ")
                index = closing.end()
                continue
            # No closing tag: the element keeps its content as text and
            # loses only its tag, which is what the old void-form pattern
            # did and what a browser does with it.
            unclosed.add(name)

        out.append(" ")
        index = end + 1

    return "".join(out)


def strip_dangerous_html(raw: str | None) -> str:
    """Remove the elements whose content is code or style, content included.

    The text that is left is safe to keep as text: no script body, no CSS
    body, no embedded object.
    """
    if not raw:
        return ""
    text = raw[:MAX_NEUTRALIZE_INPUT_CHARS]
    return _scan(text, drop_dangerous_content=True)


def neutralize_html(raw: str | None, *, collapse_whitespace: bool = True) -> str:
    """Turn untrusted HTML into plain, safe text.

    The steps are, in order:

    1. remove the elements whose content is code or style, content included;
    2. remove every remaining tag;
    3. decode the HTML entities;
    4. remove any tag that decoding revealed (a belt-and-braces pass — the
       entity decode cannot create a tag that was not there, but the check
       is free and the invariant is worth stating in code);
    5. drop control characters and, optionally, collapse whitespace.

    The invariant that matters: **no tag survives**. The order guarantees
    it, because the entity decode — the only step that could introduce a
    tag — is followed by another tag strip. A body that arrives entity
    encoded (``&lt;script&gt;``) therefore loses its tags too.

    Args:
        raw: The untrusted HTML.
        collapse_whitespace: When true, runs of whitespace become a single
            space. When false the whitespace is left alone, so a
            board-supplied plain-text field keeps its line structure — the
            difference between "the posting as written" and "the posting
            reflowed".

    Returns:
        Plain text with no markup, safe to render, store, or prompt with.
    """
    if not raw:
        return ""
    text = raw[:MAX_NEUTRALIZE_INPUT_CHARS]
    text = _scan(text, drop_dangerous_content=True)
    text = html.unescape(text)
    # A decode can reveal a tag (``&lt;script&gt;``); remove it again.
    text = _scan(text, drop_dangerous_content=False)
    text = _CONTROL_RE.sub(" ", text)
    if collapse_whitespace:
        return _WHITESPACE_RE.sub(" ", text).strip()
    return text.strip()


def escape_for_html(raw: str | None) -> str:
    """Escape *raw* so it is inert when placed in an HTML text context.

    Used where the text must keep its markup (a description rendered in a
    page) rather than lose it.
    """
    if not raw:
        return ""
    return html.escape(raw, quote=True)


#: Whitespace runs.
_WHITESPACE_RE = re.compile(r"\s+")

#: Control characters that are never legitimate in a job description and can
#: confuse a terminal, a log line, or a downstream parser.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
