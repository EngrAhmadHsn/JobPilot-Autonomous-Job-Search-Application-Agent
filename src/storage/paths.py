"""The per-user storage layout (WS-14 · Phase B).

**The rule.** Every file the platform writes *for a person* lives in that
person's own directory:

.. code-block:: text

    data/users/{user_id}/resumes/     the uploaded resumes
    data/users/{user_id}/tailored/    the rendered DOCX files
    data/users/{user_id}/evidence/    the screenshots, traces and archives

Before WS-14 the layout was flat — ``data/resumes``, ``data/tailored``,
``data/evidence`` — and the owner was recorded in the database but not on
the disk. That is the shape of a cross-tenant file read: the database
says the row is Alice's, the disk says the file is ``data/evidence/…``,
and the two can be joined by anybody who can guess a name.

**Why the containment check is per-user, not per-root.** A check that
the path is inside *a* directory the application owns is enough when
there is one user. With several, "inside a directory the application
owns" includes the other users' directories. So the check here is
against the caller's **own** directory, and it is made on the
**resolved** path (after symlinks are followed), because a symlink
pointing out of the directory is as much an escape as a ``../``
sequence.

**The client never names a path.** The download endpoints take an id (and
a bare file name), never a path. A request-supplied path — the
``resume_path`` on the prepare endpoint — is checked against the
caller's own directory, and a path outside it is refused.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "KIND_EVIDENCE",
    "KIND_RESUMES",
    "KIND_TAILORED",
    "USER_KINDS",
    "UserPathNotAllowedError",
    "assert_within_user_root",
    "is_within_user_root",
    "move_into_user_dir",
    "safe_user_segment",
    "user_dir",
    "user_root",
    "users_root",
]

#: The three kinds of file the platform stores for a person.
KIND_RESUMES = "resumes"
KIND_TAILORED = "tailored"
KIND_EVIDENCE = "evidence"

#: Every kind, in one place, so a caller cannot invent a fourth.
USER_KINDS: tuple[str, ...] = (KIND_RESUMES, KIND_TAILORED, KIND_EVIDENCE)

#: A user id becomes one path segment, so it has to be a segment that
#: cannot escape one. The ids this application issues are twelve hex
#: characters; the legacy owner is a word. Anything else is refused
#: rather than sanitised, because a sanitised id would silently write
#: to a *different* user's directory.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class UserPathNotAllowedError(ValueError):
    """The path is not inside the caller's own directory."""


def safe_user_segment(user_id: str) -> str:
    """The path segment for *user_id*, or an error.

    Raises:
        UserPathNotAllowedError: The id is not a safe path segment.
    """
    if not user_id or not _SAFE_SEGMENT.match(user_id) or user_id in {".", ".."}:
        raise UserPathNotAllowedError("The owner id is not a usable directory name")
    return user_id


def users_root() -> Path:
    """The directory that holds every user's own directory."""
    return Path(get_settings().data_dir) / "users"


def user_root(user_id: str) -> Path:
    """The root of one user's files."""
    return users_root() / safe_user_segment(user_id)


def user_dir(user_id: str, kind: str) -> Path:
    """One kind of file for one user.

    The directory is **not** created here: a caller that only wants to
    check a path should not create a directory as a side effect.
    """
    if kind not in USER_KINDS:
        raise UserPathNotAllowedError(f"Unknown kind of user file: {kind!r}")
    return user_root(user_id) / kind


def is_within_user_root(path: str | Path, user_id: str) -> bool:
    """True when *path* resolves inside *user_id*'s own directory."""
    try:
        root = user_root(user_id).resolve()
        candidate = Path(path).resolve()
    except (OSError, RuntimeError, UserPathNotAllowedError):
        return False
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def assert_within_user_root(path: str | Path, user_id: str, *, what: str = "file") -> Path:
    """Return the resolved *path*, or refuse it.

    Args:
        path: The path to check.
        user_id: The owner whose directory the path must be inside.
        what: What the path is for (used in the error message).

    Returns:
        The resolved path.

    Raises:
        UserPathNotAllowedError: The path is outside the owner's own
            directory, or it does not exist.
    """
    try:
        root = user_root(user_id).resolve()
    except UserPathNotAllowedError as exc:
        raise UserPathNotAllowedError(str(exc)) from exc

    try:
        candidate = Path(path).resolve()
    except (OSError, RuntimeError) as exc:
        raise UserPathNotAllowedError(f"The {what} could not be resolved") from exc

    if not candidate.exists():
        raise UserPathNotAllowedError(f"The {what} does not exist")

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UserPathNotAllowedError(
            f"The {what} is not inside the owner's own directory"
        ) from exc
    return candidate


def move_into_user_dir(path: str | Path, user_id: str, kind: str) -> Path | None:
    """Move a file into the owner's own directory, and return the new path.

    Used when the legacy corpus is claimed: the rows change owner, so
    the files they point at have to move with them. A file that cannot
    be moved is left where it is and reported — the row's owner still
    changed, and the file stays readable by nobody, which is the
    fail-closed direction.

    Returns:
        The new path, or ``None`` when the file could not be moved.
    """
    source = Path(path)
    if not source.exists():
        return None
    target_dir = user_dir(user_id, kind)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        shutil.move(str(source), str(target))
        return target
    except OSError as exc:
        logger.warning("Could not move %s into the owner's directory: %s", source, exc)
        return None
