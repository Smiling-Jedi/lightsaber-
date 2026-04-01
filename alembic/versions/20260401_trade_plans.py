:

"""add trade_plans table

Revision ID: 20260401_add_trade_plans
Revises: 20260324_add_batch_position_fields
Create Date: 2026-04-01

"""
from alembic import op
import sqlalchemy as sa


revision = '20260401_add_trade_plans'
down_revision = '20260324_add_batch_position_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('trade_plans',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=True),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('market', sa.String(length=10), nullable=False),
        sa.Column('strategy_type', sa.String(length=20), nullable=False),
        sa.Column('planned_shares', sa.Integer(), nullable=False),
        sa.Column('planned_price', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('target_price', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('stop_loss_method', sa.String(length=20), nullable=False),
        sa.Column('stop_loss_param', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('stop_loss_price', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('risk_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('risk_reward_ratio', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('buy_reason', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='计划中', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('review_result', sa.String(length=20), nullable=True),
        sa.Column('planned_vs_actual', sa.Text(), nullable=True),
        sa.Column('lesson_learned', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_trade_plans_symbol', 'trade_plans', ['symbol'])
    op.create_index('ix_trade_plans_status', 'trade_plans', ['status'])
    op.create_index('ix_trade_plans_created', 'trade_plans', ['created_at'])
    op.create_index('ix_trade_plans_trade_id', 'trade_plans', ['trade_id'])


def downgrade():
    op.drop_index('ix_trade_plans_trade_id', table_name='trade_plans')
    op.drop_index('ix_trade_plans_created', table_name='trade_plans')
    op.drop_index('ix_trade_plans_status', table_name='trade_plans')
    op.drop_index('ix_trade_plans_symbol', table_name='trade_plans')
    op.drop_table('trade_plans')
