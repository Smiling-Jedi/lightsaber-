"""
新增形态分析表和关注事项表

Revision ID: 20260516_add_pattern_analysis_and_watch_items
Revises: 20260403_simplify_position_model
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260516_add_pattern_analysis_and_watch_items'
down_revision = '20260403_simplify_position_model'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 创建形态分析结果表
    op.create_table(
        'pattern_analyses',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('stock_symbol', sa.String(20), nullable=False, index=True, comment='股票代码'),
        sa.Column('analysis_date', sa.Date(), nullable=False, index=True, comment='分析日期'),
        sa.Column('period', sa.String(10), nullable=False, default='day', comment='分析周期: day/week/month'),
        # L1: 核心结论
        sa.Column('pattern_name', sa.String(50), nullable=True, comment='形态名称，如"双底"'),
        sa.Column('pattern_state', sa.String(20), nullable=True, comment='形态状态: 构筑中/突破待确认/已确认/失效'),
        sa.Column('summary', sa.String(500), nullable=True, comment='一句话核心结论'),
        # L2: 形态详情
        sa.Column('key_levels_json', sa.String(2000), nullable=True, comment='关键价位JSON'),
        sa.Column('detail_text', sa.String(2000), nullable=True, comment='形态详情自然语言'),
        # L3: 关键价位
        sa.Column('strong_support', sa.Numeric(15, 4), nullable=True, comment='强支撑'),
        sa.Column('neckline', sa.Numeric(15, 4), nullable=True, comment='颈线'),
        sa.Column('target_1', sa.Numeric(15, 4), nullable=True, comment='第一目标'),
        sa.Column('target_2', sa.Numeric(15, 4), nullable=True, comment='第二目标'),
        sa.Column('stop_loss', sa.Numeric(15, 4), nullable=True, comment='止损位'),
        # L4: 多维度验证
        sa.Column('validation_json', sa.String(3000), nullable=True, comment='多维度验证JSON'),
        # L5: 持仓联动
        sa.Column('actionable_json', sa.String(2000), nullable=True, comment='持仓联动建议JSON'),
        sa.Column('confidence', sa.String(10), nullable=True, comment='高/中/低'),
        sa.Column('raw_response', sa.String(8000), nullable=True, comment='原始LLM响应'),
        sa.Column('parse_status', sa.String(10), nullable=True, default='success', comment='解析状态: success/partial/fail'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('stock_symbol', 'analysis_date', 'period', name='uix_pattern_analysis')
    )

    # 2. 创建关注事项表
    op.create_table(
        'watch_items',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('stock_symbol', sa.String(20), nullable=False, index=True, comment='股票代码'),
        sa.Column('content', sa.String(500), nullable=False, comment='事项内容'),
        sa.Column('expected_date', sa.Date(), nullable=True, comment='预计日期'),
        sa.Column('importance', sa.String(10), nullable=True, default='medium', comment='重要性: high/medium/low'),
        sa.Column('status', sa.String(20), nullable=True, default='pending', comment='状态: pending/occurred/handled'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # 3. 创建关注事项联合索引
    op.create_index('ix_watch_items_symbol_status', 'watch_items', ['stock_symbol', 'status'])

    print("✅ 形态分析表和关注事项表创建完成")


def downgrade():
    op.drop_table('pattern_analyses')
    op.drop_table('watch_items')
    print("⬇️ 已回滚迁移")
