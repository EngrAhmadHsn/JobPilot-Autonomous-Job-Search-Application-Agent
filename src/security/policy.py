"""Submission policy (WS-06 · SEC-05, plan §23).

The policy decides what the system is allowed to do with a prepared
application:

- ``PREPARE_ONLY`` — the application may be prepared and reviewed, never
  executed.
- ``REQUIRE_APPROVAL`` — the default. An application is executed only after a
  human approval record exists (see :mod:`src.db.approval`).
- ``AUTO_SUBMIT`` — **defined but unreachable**. The value exists so the
  configuration surface is complete and so a future, separately approved
  decision has a name; no code path may execute a submission under it in this
  version. :func:`assert_execution_allowed` refuses it.

An unknown policy value is a configuration error, not a silent default: the
settings layer refuses to start with a bad ``SUBMISSION_POLICY``, and this
module raises :class:`PolicyError` if it ever sees one.
"""

from __future__ import annotations

from enum import Enum


class SubmissionPolicy(str, Enum):
    """What the system may do with a prepared application."""

    PREPARE_ONLY = "PREPARE_ONLY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    AUTO_SUBMIT = "AUTO_SUBMIT"


VALID_POLICY_VALUES: tuple[str, ...] = tuple(policy.value for policy in SubmissionPolicy)

DEFAULT_POLICY = SubmissionPolicy.REQUIRE_APPROVAL


class PolicyError(RuntimeError):
    """The configured submission policy forbids the attempted action."""


class AutoSubmitNotAllowed(PolicyError):
    """Raised when something asks for an automatic submission."""


def get_submission_policy() -> SubmissionPolicy:
    """The policy configured for this deployment.

    Raises:
        PolicyError: The configured value is not a known policy.
    """
    from src.config.settings import get_settings

    raw = get_settings().submission_policy
    try:
        return SubmissionPolicy(raw)
    except ValueError as exc:
        raise PolicyError(
            f"Unknown submission policy {raw!r}; expected one of {', '.join(VALID_POLICY_VALUES)}"
        ) from exc


def assert_execution_allowed(policy: SubmissionPolicy) -> None:
    """Refuse to execute a submission under a policy that forbids it.

    Raises:
        AutoSubmitNotAllowed: The policy is ``AUTO_SUBMIT`` (unreachable in
            this version by design).
        PolicyError: The policy is ``PREPARE_ONLY``.
    """
    if policy is SubmissionPolicy.AUTO_SUBMIT:
        raise AutoSubmitNotAllowed(
            "AUTO_SUBMIT is defined but not enabled in this version: an application "
            "may only be executed after a recorded human approval."
        )
    if policy is SubmissionPolicy.PREPARE_ONLY:
        raise PolicyError(
            "Submission policy PREPARE_ONLY forbids executing a prepared application."
        )
