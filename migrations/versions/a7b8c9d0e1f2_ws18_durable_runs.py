"""WS-18: durable background execution

Revision ID: a7b8c9d0e1f2
Revises: c3d4e5f6a7b8
Create Date: 2026-11-05

Adds the database-backed work queue that replaces the "the HTTP request is
the job" model:

- ``job_runs`` — one durable execution, its status, lease, counters and
  checkpoint;
- ``job_work_items`` — individually claimable units, each with its own lease
  token and retry schedule, plus the uniqueness constraint that makes an
  identical (job, content version, model, dimension) one piece of work;
- ``job_run_events`` — the append-only lifecycle history;
- ``worker_heartbeats`` — liveness for the separate worker process;
- ``circuit_breakers`` — optional shared breaker state for multi-worker
  deployments.

The DDL is portable: plain ``JSON``/``DateTime``/``Integer``/``String``
columns, no dialect-specific types, and reversible on SQLite and PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable-execution tables."""
    op.create_table(
        "job_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("parent_run_id", sa.String(), nullable=True),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("completed_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("skipped_items", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("last_error_kind", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_runs_job_type"), "job_runs", ["job_type"], unique=False)
    op.create_index(op.f("ix_job_runs_status"), "job_runs", ["status"], unique=False)
    op.create_index(op.f("ix_job_runs_owner_id"), "job_runs", ["owner_id"], unique=False)
    op.create_index(
        op.f("ix_job_runs_correlation_id"), "job_runs", ["correlation_id"], unique=False
    )
    op.create_index(op.f("ix_job_runs_parent_run_id"), "job_runs", ["parent_run_id"], unique=False)
    op.create_index("ix_job_runs_status_priority", "job_runs", ["status", "priority", "created_at"])
    op.create_index("ix_job_runs_type_status", "job_runs", ["job_type", "status"])

    op.create_table(
        "job_work_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("work_type", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("embedding_model", sa.String(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_token", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("last_error_kind", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["job_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "job_id",
            "work_type",
            "content_hash",
            "embedding_model",
            "embedding_dimension",
            name="uq_job_work_items_identity",
        ),
    )
    op.create_index(op.f("ix_job_work_items_run_id"), "job_work_items", ["run_id"], unique=False)
    op.create_index(op.f("ix_job_work_items_job_id"), "job_work_items", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_job_work_items_work_type"), "job_work_items", ["work_type"], unique=False
    )
    op.create_index(op.f("ix_job_work_items_status"), "job_work_items", ["status"], unique=False)
    op.create_index(
        op.f("ix_job_work_items_next_attempt_at"),
        "job_work_items",
        ["next_attempt_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_work_items_lease_token"), "job_work_items", ["lease_token"], unique=False
    )
    op.create_index(
        op.f("ix_job_work_items_lease_expires_at"),
        "job_work_items",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index("ix_job_work_items_claim", "job_work_items", ["status", "next_attempt_at"])
    op.create_index("ix_job_work_items_run_status", "job_work_items", ["run_id", "status"])
    op.create_index("ix_job_work_items_lease", "job_work_items", ["lease_expires_at"])

    op.create_table(
        "job_run_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("work_item_id", sa.String(), nullable=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("actor_kind", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_run_events_run_id"), "job_run_events", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_job_run_events_work_item_id"), "job_run_events", ["work_item_id"], unique=False
    )
    op.create_index(op.f("ix_job_run_events_event"), "job_run_events", ["event"], unique=False)
    op.create_index(
        op.f("ix_job_run_events_owner_id"), "job_run_events", ["owner_id"], unique=False
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("hostname", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("current_run_id", sa.String(), nullable=True),
        sa.Column("processed_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("starts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        op.f("ix_worker_heartbeats_last_heartbeat_at"),
        "worker_heartbeats",
        ["last_heartbeat_at"],
        unique=False,
    )

    op.create_table(
        "circuit_breakers",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    """Remove the durable-execution tables (reverse creation order)."""
    op.drop_table("circuit_breakers")
    op.drop_index(op.f("ix_worker_heartbeats_last_heartbeat_at"), table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
    op.drop_index(op.f("ix_job_run_events_owner_id"), table_name="job_run_events")
    op.drop_index(op.f("ix_job_run_events_event"), table_name="job_run_events")
    op.drop_index(op.f("ix_job_run_events_work_item_id"), table_name="job_run_events")
    op.drop_index(op.f("ix_job_run_events_run_id"), table_name="job_run_events")
    op.drop_table("job_run_events")
    op.drop_index("ix_job_work_items_lease", table_name="job_work_items")
    op.drop_index("ix_job_work_items_run_status", table_name="job_work_items")
    op.drop_index("ix_job_work_items_claim", table_name="job_work_items")
    op.drop_index(op.f("ix_job_work_items_lease_expires_at"), table_name="job_work_items")
    op.drop_index(op.f("ix_job_work_items_lease_token"), table_name="job_work_items")
    op.drop_index(op.f("ix_job_work_items_next_attempt_at"), table_name="job_work_items")
    op.drop_index(op.f("ix_job_work_items_status"), table_name="job_work_items")
    op.drop_index(op.f("ix_job_work_items_work_type"), table_name="job_work_items")
    op.drop_index(op.f("ix_job_work_items_job_id"), table_name="job_work_items")
    op.drop_index(op.f("ix_job_work_items_run_id"), table_name="job_work_items")
    op.drop_table("job_work_items")
    op.drop_index("ix_job_runs_type_status", table_name="job_runs")
    op.drop_index("ix_job_runs_status_priority", table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_parent_run_id"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_correlation_id"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_owner_id"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_status"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_job_type"), table_name="job_runs")
    op.drop_table("job_runs")
