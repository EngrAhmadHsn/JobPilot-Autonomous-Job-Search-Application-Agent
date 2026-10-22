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
from src.security.paths import is_foreign_absolute_path

logger = logging.getLogger(__name__)

__all__ = [
    "KIND_EVIDENCE",
    "KIND_RESUMES",
    "KIND_TAILORED",
    "USER_KINDS",
    "UserPathNotAllowedError",
    "assert_within_owned_storage",
    "assert_within_user_root",
    "is_within_user_root",
    "legacy_roots",
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

    # A path in a foreign convention (a Windows drive path read on a
    # Linux host) cannot be inside this host's directory, so it is
    # refused outright rather than resolved against the working
    # directory — where it would land somewhere plausible and wrong.
    if is_foreign_absolute_path(path):
        raise UserPathNotAllowedError(f"The {what} is an absolute path in a foreign convention")

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


def legacy_roots() -> list[Path]:
    """The shared directories that pre-date the per-user storage.

    WS-15: the files written before the per-user layout (``data/resumes``,
    ``data/tailored``) still exist, and the rows that point at them are
    claimed by the **first** account to register. They are therefore part
    of that account's own storage — but they are shared directories, so
    they have to be listed explicitly.

    The data directory is deliberately **not** in this list: it is the
    *parent* of the per-user directories, so including it would make every
    user's files "shared" again — the mistake this module exists to fix.
    """
    settings = get_settings()
    roots: list[Path] = []
    for candidate in (settings.resume_upload_dir, settings.tailored_dir):
        if not candidate:
            continue
        try:
            roots.append(Path(candidate).resolve())
        except OSError:
            logger.warning("Could not resolve the legacy root %r", candidate)
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def assert_within_owned_storage(path: str | Path, user_id: str, *, what: str = "file") -> Path:
    """The resolved *path*, if the caller may read it.

    WS-15: two places are the caller's own — their per-user directory, and
    the legacy shared directories whose files their account claimed. Any
    other path, **including another user's directory**, is refused.

    The previous check on the document download was the *shared* roots
    (``src.security.paths.allowed_roots``), which include the data
    directory and therefore every user's directory. The path was never
    request-supplied there, so it was not exploitable — but it was one
    refactor away from being a cross-tenant file read, and the check
    should be the right one rather than the one that happens to work.

    Raises:
        UserPathNotAllowedError: The path belongs to nobody the caller
            can claim, or it does not exist.
    """
    try:
        return assert_within_user_root(path, user_id, what=what)
    except UserPathNotAllowedError:
        pass

    try:
        candidate = Path(path).resolve()
    except (OSError, RuntimeError) as exc:
        raise UserPathNotAllowedError(f"The {what} could not be resolved") from exc

    if not candidate.exists():
        raise UserPathNotAllowedError(f"The {what} does not exist")

    for root in legacy_roots():
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        return candidate

    raise UserPathNotAllowedError(f"The {what} is not inside the owner's own directory")


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
