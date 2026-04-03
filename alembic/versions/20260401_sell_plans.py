"""
卖出计划表

Revision ID: 20260401_sell_plans
Revises: 20260401_trade_plans
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260401_sell_plans'
down_revision = '20260401_trade_plans'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sell_plans',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('buy_plan_id', sa.Integer(), sa.ForeignKey('trade_plans.id'), nullable=True, index=True),
        sa.Column('position_id', sa.Integer(), sa.ForeignKey('positions.id'), nullable=True, index=True),
        sa.Column('symbol', sa.String(20), nullable=False, index=True),
        sa.Column('market', sa.String(10), nullable=False),
        sa.Column('planned_shares', sa.Integer(), nullable=False),
        sa.Column('planned_price', sa.Numeric(15, 4), nullable=True),
        sa.Column('original_target_price', sa.Numeric(15, 4), nullable=True),
        sa.Column('sell_trigger_method', sa.String(20), nullable=False),
        sa.Column('sell_trigger_param', sa.Numeric(10, 4), nullable=False),
        sa.Column('sell_type', sa.String(20), default='止盈', nullable=False),
        sa.Column('estimated_profit', sa.Numeric(15, 2), nullable=True),
        sa.Column('estimated_profit_pct', sa.Numeric(5, 2), nullable=True),
        sa.Column('target_achievement_pct', sa.Numeric(5, 2), nullable=True),
        sa.Column('sell_reason', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), default='计划中', nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('executed_price', sa.Numeric(15, 4), nullable=True),
        sa.Column('actual_profit', sa.Numeric(15, 2), nullable=True),
    )


def downgrade():
    op.drop_table('sell_plans')
