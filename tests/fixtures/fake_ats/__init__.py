"""The fake ATS: the local stand-in for a real applicant-tracking system.

Two servers live here:

``serve_fake_ats()``
    the WS-06 server — a form, a confirmation page and a CAPTCHA page, served
    by the standard library. It is the one the WS-06 and WS-07 live scripts
    drive, and it is unchanged in behaviour.
``serve_fake_ats_variants()``
    the WS-08 variant server — the same idea extended to the page variants
    the browser layer has to survive: a wizard, widget controls, an unknown
    question, a rejected form, a challenge and a required upload.

Both yield a base URL on a free localhost port.
"""

from __future__ import annotations

from .variants import create_app, serve_fake_ats_variants
from .ws06 import serve_fake_ats

__all__ = [
    "create_app",
    "serve_fake_ats",
    "serve_fake_ats_variants",
]
