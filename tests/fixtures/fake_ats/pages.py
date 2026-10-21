"""The HTML of the fake-ATS pages (WS-08).

Every page is **semantic**: the controls carry real ``<label for>``
associations, the radio group is a ``<fieldset>`` with a ``<legend>``, the
buttons are real ``<button>`` elements and the errors are ``role="alert"``
boxes. The adapter is expected to find everything here through the
accessibility tree — with exactly two documented exceptions (the file input
and the error sweep).

The canonical labels are the ones the field map knows:

===========================  ==========================
Control                      Label
===========================  ==========================
candidate name               Full name
email                        Email address
phone                        Phone number
cover letter                 Cover letter
resume file                  Resume
country                      Country (a select)
years of experience          Years of experience
work authorization           I am authorized to work (a checkbox)
work mode                    Work mode (a radio group)
===========================  ==========================
"""

from __future__ import annotations

_STYLE = """
  body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 40rem; }
  label { display: block; margin-top: 0.75rem; font-weight: 600; }
  input, select, textarea { display: block; margin-top: 0.25rem; padding: 0.35rem; }
  fieldset { margin-top: 1rem; }
  button { margin-top: 1.25rem; padding: 0.5rem 1rem; }
  [role="alert"] { color: #b00020; font-weight: 600; }
"""

_PAGE = """<!doctype html>
<html lang="en">
  <head><title>{title}</title><style>{style}</style></head>
  <body>
{body}
  </body>
</html>
"""


def _page(title: str, body: str) -> str:
    """One HTML document."""
    return _PAGE.format(title=title, style=_STYLE, body=body)


def _text_field(
    field_id: str,
    label: str,
    *,
    kind: str = "text",
    required: bool = False,
    value: str = "",
) -> str:
    """A labelled single-line control."""
    required_attr = " required" if required else ""
    value_attr = f' value="{value}"' if value else ""
    return (
        f'      <label for="{field_id}">{label}</label>\n'
        f'      <input type="{kind}" id="{field_id}" name="{field_id}"'
        f"{value_attr}{required_attr}>\n"
    )


def _hidden(field_id: str, value: str) -> str:
    """A hidden field, used to carry a value between the pages of a wizard."""
    return f'      <input type="hidden" name="{field_id}" value="{value}">\n'


def _textarea(field_id: str, label: str, *, required: bool = False, value: str = "") -> str:
    """A labelled multi-line control."""
    required_attr = " required" if required else ""
    return (
        f'      <label for="{field_id}">{label}</label>\n'
        f'      <textarea id="{field_id}" name="{field_id}"{required_attr}>{value}</textarea>\n'
    )


def _file_field(field_id: str, label: str, *, required: bool = False) -> str:
    """A labelled file control."""
    required_attr = " required" if required else ""
    return (
        f'      <label for="{field_id}">{label}</label>\n'
        f'      <input type="file" id="{field_id}" name="{field_id}"{required_attr}>\n'
    )


def _alert(message: str) -> str:
    """An inline validation error."""
    return f'    <p role="alert">{message}</p>\n'


# ---------------------------------------------------------------------------
# The pages
# ---------------------------------------------------------------------------


def basic_form(**values: str) -> str:
    """The single-page form — the regression baseline."""
    body = (
        "    <h1>Apply for Backend Engineer</h1>\n"
        '    <form method="post" action="/basic" enctype="multipart/form-data">\n'
        + _text_field(
            "candidate_name", "Full name", required=True, value=values.get("candidate_name", "")
        )
        + _text_field(
            "email", "Email address", kind="email", required=True, value=values.get("email", "")
        )
        + _text_field("phone", "Phone number", kind="tel", value=values.get("phone", ""))
        + _textarea("cover_letter", "Cover letter", value=values.get("cover_letter", ""))
        + _file_field("resume", "Resume")
        + '      <button type="submit">Submit application</button>\n'
        "    </form>\n"
    )
    return _page("Apply — Acme Labs", body)


def multipage_step1(**values: str) -> str:
    """Step 1 of the wizard: the personal details."""
    body = (
        "    <h1>Apply for Backend Engineer — Step 1 of 3</h1>\n"
        '    <form method="post" action="/multipage/step2">\n'
        + _text_field(
            "candidate_name", "Full name", required=True, value=values.get("candidate_name", "")
        )
        + _text_field(
            "email", "Email address", kind="email", required=True, value=values.get("email", "")
        )
        + _text_field("phone", "Phone number", kind="tel", value=values.get("phone", ""))
        + '      <button type="submit">Next</button>\n'
        "    </form>\n"
    )
    return _page("Apply — Step 1", body)


def multipage_step2(**values: str) -> str:
    """Step 2 of the wizard: the experience questions."""
    body = (
        "    <h1>Apply for Backend Engineer — Step 2 of 3</h1>\n"
        '    <form method="post" action="/multipage/step3">\n'
        + _hidden("candidate_name", values.get("candidate_name", ""))
        + _hidden("email", values.get("email", ""))
        + _hidden("phone", values.get("phone", ""))
        + _text_field("years_of_experience", "Years of experience", kind="number", required=True)
        + _text_field("work_authorization", "I am authorized to work", kind="text", required=True)
        + '      <button type="submit">Next</button>\n'
        "    </form>\n"
    )
    return _page("Apply — Step 2", body)


def multipage_step3(**values: str) -> str:
    """Step 3 of the wizard: the review and the final submit."""
    body = (
        "    <h1>Apply for Backend Engineer — Step 3 of 3</h1>\n"
        "    <dl>\n"
        f"      <dt>Full name</dt><dd>{values.get('candidate_name', '')}</dd>\n"
        f"      <dt>Email address</dt><dd>{values.get('email', '')}</dd>\n"
        f"      <dt>Phone number</dt><dd>{values.get('phone', '')}</dd>\n"
        f"      <dt>Years of experience</dt><dd>{values.get('years_of_experience', '')}</dd>\n"
        f"      <dt>I am authorized to work</dt><dd>{values.get('work_authorization', '')}</dd>\n"
        "    </dl>\n"
        '    <form method="post" action="/multipage/submit">\n'
        + _hidden("candidate_name", values.get("candidate_name", ""))
        + _hidden("email", values.get("email", ""))
        + _hidden("phone", values.get("phone", ""))
        + _hidden("years_of_experience", values.get("years_of_experience", ""))
        + _hidden("work_authorization", values.get("work_authorization", ""))
        + '      <button type="submit">Submit application</button>\n'
        "    </form>\n"
    )
    return _page("Apply — Step 3", body)


def widgets_form(**values: str) -> str:
    """The widget page: a select, a checkbox and a radio group."""
    body = (
        "    <h1>Apply for Backend Engineer</h1>\n"
        '    <form method="post" action="/widgets" enctype="multipart/form-data">\n'
        + _text_field(
            "candidate_name", "Full name", required=True, value=values.get("candidate_name", "")
        )
        + _text_field(
            "email", "Email address", kind="email", required=True, value=values.get("email", "")
        )
        + '      <label for="country">Country</label>\n'
        '      <select id="country" name="country">\n'
        '        <option value="">Select a country</option>\n'
        '        <option value="Germany">Germany</option>\n'
        '        <option value="Canada">Canada</option>\n'
        '        <option value="United Kingdom">United Kingdom</option>\n'
        "      </select>\n"
        + _text_field("years_of_experience", "Years of experience", kind="number")
        + '      <label for="work_authorization">I am authorized to work</label>\n'
        '      <input type="checkbox" id="work_authorization" name="work_authorization" value="yes">\n'
        "      <fieldset>\n"
        "        <legend>Work mode</legend>\n"
        '        <label for="work_mode_remote">Remote</label>\n'
        '        <input type="radio" id="work_mode_remote" name="work_mode" value="remote">\n'
        '        <label for="work_mode_hybrid">Hybrid</label>\n'
        '        <input type="radio" id="work_mode_hybrid" name="work_mode" value="hybrid">\n'
        '        <label for="work_mode_onsite">Onsite</label>\n'
        '        <input type="radio" id="work_mode_onsite" name="work_mode" value="onsite">\n'
        "      </fieldset>\n"
        + _file_field("resume", "Resume")
        + '      <button type="submit">Submit application</button>\n'
        "    </form>\n"
    )
    return _page("Apply — Acme Labs", body)


def unknown_form(**values: str) -> str:
    """The page with a question the field map does not know."""
    body = (
        "    <h1>Apply for Backend Engineer</h1>\n"
        '    <form method="post" action="/unknown">\n'
        + _text_field(
            "candidate_name", "Full name", required=True, value=values.get("candidate_name", "")
        )
        + _text_field(
            "email", "Email address", kind="email", required=True, value=values.get("email", "")
        )
        + _text_field("phone", "Phone number", kind="tel", value=values.get("phone", ""))
        + _text_field("submarine", "Have you served on a submarine?")
        + '      <button type="submit">Submit application</button>\n'
        "    </form>\n"
    )
    return _page("Apply — Acme Labs", body)


def validation_form(message: str | None = None, action: str = "/validation", **values: str) -> str:
    """The page whose submission the server rejects."""
    body = ""
    if message:
        body += _alert(message)
    body += (
        "    <h1>Apply for Backend Engineer</h1>\n"
        f'    <form method="post" action="{action}">\n'
        + _text_field(
            "candidate_name", "Full name", required=True, value=values.get("candidate_name", "")
        )
        + _text_field(
            "email", "Email address", kind="email", required=True, value=values.get("email", "")
        )
        + _text_field("phone", "Phone number", kind="tel", value=values.get("phone", ""))
        + '      <button type="submit">Submit application</button>\n'
        "    </form>\n"
    )
    return _page("Apply — Acme Labs", body)


def upload_required_form(message: str | None = None, **values: str) -> str:
    """The page whose file input is required."""
    body = ""
    if message:
        body += _alert(message)
    body += (
        "    <h1>Apply for Backend Engineer</h1>\n"
        '    <form method="post" action="/upload-required" enctype="multipart/form-data">\n'
        + _text_field(
            "candidate_name", "Full name", required=True, value=values.get("candidate_name", "")
        )
        + _text_field(
            "email", "Email address", kind="email", required=True, value=values.get("email", "")
        )
        + _file_field("resume", "Resume", required=True)
        + '      <button type="submit">Submit application</button>\n'
        "    </form>\n"
    )
    return _page("Apply — Acme Labs", body)


def captcha_page() -> str:
    """The challenge page. The flow must stop here and never touch the widget."""
    body = (
        "    <h1>Verify you are human</h1>\n"
        "    <p>Please complete the CAPTCHA to continue.</p>\n"
        '    <div class="g-recaptcha" data-sitekey="fake-ats-key">reCAPTCHA</div>\n'
        '    <iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>\n'
    )
    return _page("Just a moment...", body)


def confirmation_page(reference: str = "FAKE-ATS-0001", marker: str | None = None) -> str:
    """The confirmation page — the only page that means "submitted"."""
    body = (
        "    <h1>Application Submitted</h1>\n"
        "    <p>Thanks for applying. We received your application.</p>\n"
        f"    <p>Confirmation id: {reference}</p>\n"
    )
    if marker is not None:
        body += f"    <p>Marker: {marker}</p>\n"
    return _page("Application received", body)


def failure_page() -> str:
    """A page that looks like an outcome but confirms nothing."""
    body = (
        "    <h1>Something went wrong</h1>\n"
        "    <p>We could not process your application. Please try again later.</p>\n"
    )
    return _page("Application error", body)


def session_page(received_cookie: str | None) -> str:
    """The session probe.

    It reports the cookie it was given, and it reports what the browser's
    **storage** held when the page loaded. The marker is written into a
    hidden field and posted back, so the isolation test can read it out of
    the adapter's own confirmation text.
    """
    body = (
        "    <h1>Session probe</h1>\n"
        f"    <p>Cookie received: {received_cookie or 'none'}</p>\n"
        '    <form method="post" action="/session">\n'
        '      <input type="hidden" name="marker" id="marker" value="none">\n'
        "      <script>\n"
        "        (function () {\n"
        "          var previous = window.localStorage.getItem('ats-marker');\n"
        "          document.getElementById('marker').value =\n"
        "            previous === null ? 'none' : previous;\n"
        "          window.localStorage.setItem('ats-marker', 'set-by-this-run');\n"
        "        })();\n"
        "      </script>\n"
        '      <button type="submit">Submit application</button>\n'
        "    </form>\n"
    )
    return _page("Session probe", body)
