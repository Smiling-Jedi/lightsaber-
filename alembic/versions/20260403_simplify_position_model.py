"""
简化持仓模型，分离审计日志，添加汇率历史

Revision ID: 20260403_simplify_position_model
Revises: 20260401_sell_plans
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = '20260403_simplify_position_model'
down_revision = '20260401_sell_plans'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 创建持仓变更审计日志表
    op.create_table(
        'position_audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('position_id', sa.Integer(), sa.ForeignKey('positions.id'), nullable=False, index=True),
        sa.Column('stock_symbol', sa.String(20), nullable=False, index=True),
        sa.Column('field_name', sa.String(50), nullable=False, comment='变更字段名'),
        sa.Column('old_value', sa.String(500), nullable=True, comment='原值'),
        sa.Column('new_value', sa.String(500), nullable=True, comment='新值'),
        sa.Column('change_reason', sa.String(50), nullable=False, comment='变更原因: SYNC/MANUAL/TRADE'),
        sa.Column('source', sa.String(50), nullable=False, comment='来源: FUTU/USER/SCRIPT'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # 2. 创建汇率历史表
    op.create_table(
        'exchange_rate_history',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('date', sa.Date(), nullable=False, index=True),
        sa.Column('hkd_rate', sa.Numeric(10, 6), nullable=False, comment='1 HKD = ? CNY'),
        sa.Column('usd_rate', sa.Numeric(10, 6), nullable=False, comment='1 USD = ? CNY'),
        sa.Column('source', sa.String(50), nullable=False, default='API', comment='API/MANUAL'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('date', name='uix_rate_date')
    )

    # 3. 为positions表添加source字段和last_sync_at字段
    op.add_column('positions', sa.Column('source', sa.String(50), nullable=True, server_default='MIXED', comment='数据来源: FUTU_AUTO/MANUAL/MIXED'))
    op.add_column('positions', sa.Column('last_sync_at', sa.DateTime(), nullable=True))

    # 4. 创建索引优化查询
    op.create_index('ix_positions_source', 'positions', ['source'])
    op.create_index('ix_positions_last_sync', 'positions', ['last_sync_at'])

    # 5. 为portfolio_snapshots表添加汇率字段（如果还不存在）
    # 先检查字段是否存在
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('portfolio_snapshots')]

    if 'hkd_rate' not in columns:
        op.add_column('portfolio_snapshots', sa.Column('hkd_rate', sa.Numeric(10, 6), nullable=True))
    if 'usd_rate' not in columns:
        op.add_column('portfolio_snapshots', sa.Column('usd_rate', sa.Numeric(10, 6), nullable=True))

    print("✅ 简化持仓模型迁移完成")


def downgrade():
    # 删除新创建的表
    op.drop_table('position_audit_logs')
    op.drop_table('exchange_rate_history')

    # 删除添加的字段
    op.drop_column('positions', 'source')
    op.drop_column('positions', 'last_sync_at')
    op.drop_index('ix_positions_source', table_name='positions')
    op.drop_index('ix_positions_last_sync', table_name='positions')

    print("⬇️ 已回滚迁移")
