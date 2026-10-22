"""Filesystem path containment (WS-12).

The application takes a filesystem path from an untrusted request
(``resume_path`` on the prepare endpoint) and hands it to the browser
layer, which uploads that file to a third-party job site. A path that is
not contained is therefore an **exfiltration channel**: point it at
``.env``, at ``id_rsa``, or at any file the process can read, and the
browser sends it to an employer.

The rule is a **containment** rule, not a blocklist. The path must resolve
to a location inside one of the directories this application owns:

- the resume upload directory (the files a candidate uploaded);
- the tailored-resume directory (the files this application generated);
- the data directory (the parent of both).

Containment is checked on the **resolved** path, after symlinks are
followed, because the attack is a symlink pointing out of the directory
just as much as it is a ``../`` sequence. A prefix comparison on the
*unresolved* string would accept ``/data/uploads/../../etc/passwd`` and a
symlink named ``resume.docx``.

The check is done once, at the API boundary, so the browser layer can
trust the path it receives.

**One more thing this module decides: what "absolute" means.** ``pathlib``
judges absoluteness with the rules of the **host**: on Linux, a Windows
drive path such as ``C:/evidence/x.png`` is a *relative* path, so joining
it onto the evidence directory produces the nonsense
``data/evidence/C:/evidence/x.png``.

A stored path may have been written on a Windows host and read on a
Linux one — a database moved between machines, a shared volume, a
container on a different platform. So the **convention** has to be
recognised, not only the host's own notion of absolute. That is what
:func:`is_absolute_path` is for, and every module that has to judge a
stored path uses it.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "PathNotAllowedError",
    "allowed_roots",
    "assert_within_allowed_roots",
    "is_absolute_path",
    "is_foreign_absolute_path",
    "is_within_allowed_roots",
]

#: A Windows drive path: ``C:evidence/x.png`` with a separator after the
#: colon, in either slash convention.
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")

#: A Windows UNC path: a leading double separator and a host name.
_WINDOWS_UNC = re.compile(r"^[\\/]{2}[^\\/]+[\\/]")


def is_foreign_absolute_path(path: str | Path) -> bool:
    """True when *path* is absolute in a convention **this host does not share**.

    The question is host-relative, and each host has exactly one foreign
    convention:

    - on **POSIX**, the foreign one is the **Windows** convention: a
      drive path (``C:/evidence/x.png``) and a UNC path
      (``//server/share/x.png``) are relative there;
    - on **Windows**, the foreign one is the **POSIX** convention: a
      rooted path (``/evidence/x.png``) is rooted on the current drive,
      which ``pathlib`` does not call absolute either.

    A path like this may have been written on a different host and read
    on this one, and joining it onto a directory produces a path that
    looks plausible and points at nothing.
    """
    text = str(path)
    if os.name == "nt":
        return text.startswith(("/", "\\"))
    return bool(_WINDOWS_DRIVE.match(text) or _WINDOWS_UNC.match(text))


def is_absolute_path(path: str | Path) -> bool:
    """True when *path* is absolute in **any** convention.

    Host-independent, and the question the rest of the code asks: "is
    this a whole path, or is it a name to be joined onto a directory?"
    """
    return Path(path).is_absolute() or is_foreign_absolute_path(path)


class PathNotAllowedError(ValueError):
    """The path is not inside a directory this application owns."""


def allowed_roots() -> list[Path]:
    """The directories a request-supplied path may point into.

    Every root is resolved, so the comparison below is between two
    resolved paths and a symlink cannot smuggle the check.
    """
    settings = get_settings()
    roots: list[Path] = []
    for candidate in (
        settings.resume_upload_dir,
        settings.tailored_dir,
        settings.data_dir,
    ):
        if not candidate:
            continue
        try:
            roots.append(Path(candidate).resolve())
        except OSError:
            logger.warning("Could not resolve the allowed root %r", candidate)
    # Deduplicate while keeping the order stable.
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def is_within_allowed_roots(path: str | Path) -> bool:
    """True when *path* resolves inside one of the allowed roots."""
    try:
        candidate = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    for root in allowed_roots():
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def assert_within_allowed_roots(path: str | Path, *, what: str = "path") -> Path:
    """Return the resolved *path*, or refuse it.

    Args:
        path: The request-supplied path.
        what: What the path is for (used in the error message).

    Returns:
        The resolved path.

    Raises:
        PathNotAllowedError: The path is outside every allowed root, or it
            does not exist.
    """
    try:
        candidate = Path(path).resolve()
    except (OSError, RuntimeError) as exc:
        raise PathNotAllowedError(f"The {what} could not be resolved") from exc

    if not candidate.exists():
        raise PathNotAllowedError(f"The {what} does not exist")

    if not is_within_allowed_roots(candidate):
        raise PathNotAllowedError(f"The {what} is not inside a directory this application owns")
    return candidate
