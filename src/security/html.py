"""HTML neutralization for untrusted web text (WS-12).

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
"""

from __future__ import annotations

import html
import re

__all__ = ["escape_for_html", "neutralize_html", "strip_dangerous_html"]

#: Elements whose **content** is code, style, or embedded foreign content.
#: The content between the opening and closing tag is dropped entirely.
_DANGEROUS_BLOCKS = (
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
)

#: A dangerous block with its content: ``<script ...> ... </script>``.
_BLOCK_RE = re.compile(
    r"<(?P<tag>" + "|".join(_DANGEROUS_BLOCKS) + r")\b[^>]*>.*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)

#: A self-closing or unclosed dangerous tag: ``<script src="...">``.
_VOID_DANGEROUS_RE = re.compile(
    r"<(?:" + "|".join(_DANGEROUS_BLOCKS) + r")\b[^>]*/?>",
    re.IGNORECASE,
)

#: Any remaining tag.
_TAG_RE = re.compile(r"<[^>]*>")

#: An HTML comment.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: A processing instruction or a CDATA section.
_PI_RE = re.compile(r"<\?.*?\?>", re.DOTALL)
_CDATA_RE = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)

#: Whitespace runs.
_WHITESPACE_RE = re.compile(r"\s+")

#: Control characters that are never legitimate in a job description and can
#: confuse a terminal, a log line, or a downstream parser.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_dangerous_html(raw: str | None) -> str:
    """Remove the elements whose content is code or style, content included.

    The text that is left is safe to keep as text: no script body, no CSS
    body, no embedded object.
    """
    if not raw:
        return ""
    text = raw
    # Comments can hide markup from a naive reader; CDATA and processing
    # instructions are not content at all.
    text = _COMMENT_RE.sub(" ", text)
    text = _CDATA_RE.sub(" ", text)
    text = _PI_RE.sub(" ", text)
    # The block forms first (they carry content), then the leftover tags.
    text = _BLOCK_RE.sub(" ", text)
    text = _VOID_DANGEROUS_RE.sub(" ", text)
    return text


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
    text = strip_dangerous_html(raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    # A decode can reveal a tag (``&lt;script&gt;``); remove it again.
    text = _TAG_RE.sub(" ", text)
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
