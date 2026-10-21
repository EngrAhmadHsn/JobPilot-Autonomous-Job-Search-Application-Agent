"""WS-07: applications + application_events tables

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-21

Adds the application-tracking persistence layer
(docs/implementation/07-application-tracking.md):

- ``applications``        <- src.db.applications.ApplicationDB
- ``application_events``  <- src.db.applications.ApplicationEventDB
- ``application_evidence.application_id`` — the link from a submission's
  evidence to the tracked application it belongs to.

JSON columns are emitted as portable ``sa.JSON()`` (valid on SQLite and
PostgreSQL). Neither new table carries foreign keys by design, matching the
WS-06 convention: a tracking record and its history must outlive the rows they
refer to, so the trail survives the deletion of the object it describes. The
referenced columns are indexed instead.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "applications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=True),
        sa.Column("adapter_name", sa.String(), nullable=False),
        sa.Column("job_url", sa.String(), nullable=False),
        sa.Column("job_title", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("tailored_resume_id", sa.String(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("application_url", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_applications_profile_id"), "applications", ["profile_id"])
    op.create_index(op.f("ix_applications_job_id"), "applications", ["job_id"])
    op.create_index(op.f("ix_applications_workflow_id"), "applications", ["workflow_id"])
    op.create_index(op.f("ix_applications_approval_id"), "applications", ["approval_id"])
    op.create_index(op.f("ix_applications_status"), "applications", ["status"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_application_events_id"), "application_events", ["id"])
    op.create_index(
        op.f("ix_application_events_application_id"), "application_events", ["application_id"]
    )
    op.create_index(op.f("ix_application_events_event_type"), "application_events", ["event_type"])
    op.create_index(op.f("ix_application_events_actor"), "application_events", ["actor"])
    op.create_index(
        op.f("ix_application_events_recorded_at"), "application_events", ["recorded_at"]
    )

    # WS-07: link a submission's evidence to the tracked application.
    op.add_column(
        "application_evidence",
        sa.Column("application_id", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_application_evidence_application_id"),
        "application_evidence",
        ["application_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_application_evidence_application_id"), table_name="application_evidence")
    op.drop_column("application_evidence", "application_id")

    op.drop_index(op.f("ix_application_events_recorded_at"), table_name="application_events")
    op.drop_index(op.f("ix_application_events_actor"), table_name="application_events")
    op.drop_index(op.f("ix_application_events_event_type"), table_name="application_events")
    op.drop_index(op.f("ix_application_events_application_id"), table_name="application_events")
    op.drop_index(op.f("ix_application_events_id"), table_name="application_events")
    op.drop_table("application_events")

    op.drop_index(op.f("ix_applications_status"), table_name="applications")
    op.drop_index(op.f("ix_applications_approval_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_workflow_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_job_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_profile_id"), table_name="applications")
    op.drop_table("applications")
