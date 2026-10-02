from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.LargeBinary(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table(
        "drivers",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_drivers_available", "drivers", ["available"])
    op.create_table(
        "invitations",
        sa.Column("code_hash", sa.String(length=64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_table(
        "rides",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("rider_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("driver_id", sa.String(length=36), sa.ForeignKey("drivers.user_id"), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("pickup_latitude", sa.Float(), nullable=False),
        sa.Column("pickup_longitude", sa.Float(), nullable=False),
        sa.Column("dropoff_latitude", sa.Float(), nullable=False),
        sa.Column("dropoff_longitude", sa.Float(), nullable=False),
        sa.Column("distance_miles", sa.Float(), nullable=False),
        sa.Column("duration_minutes", sa.Float(), nullable=False),
        sa.Column("fare_cents", sa.Integer(), nullable=False),
        sa.Column("tip_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.UniqueConstraint("rider_id", "idempotency_key"),
    )
    op.create_index("ix_rides_rider_id", "rides", ["rider_id"])


def downgrade():
    op.drop_index("ix_rides_rider_id", table_name="rides")
    op.drop_table("rides")
    op.drop_table("invitations")
    op.drop_index("ix_drivers_available", table_name="drivers")
    op.drop_table("drivers")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")