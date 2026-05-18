"""
形态分析结果模型
存储大模型（Claude API）对持仓股票的形态分析结果
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Numeric, Date, UniqueConstraint

from app.core.database import Base


class PatternAnalysis(Base):
    """形态分析结果"""

    __tablename__ = "pattern_analyses"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 股票代码（如 HK:00700）
    stock_symbol = Column(String(20), nullable=False, index=True, comment="股票代码")

    # 分析日期
    analysis_date = Column(Date, nullable=False, index=True, comment="分析日期")

    # 周期（day/week/month）
    period = Column(String(10), nullable=False, default="day", comment="分析周期")

    # ── L1: 核心结论 ──
    pattern_name = Column(String(50), nullable=True, comment="形态名称，如'双底'")
    pattern_state = Column(
        String(20), nullable=True,
        comment="形态状态: 构筑中/突破待确认/已确认/失效"
    )
    summary = Column(String(500), nullable=True, comment="一句话核心结论")

    # ── L2: 形态详情 ──
    key_levels_json = Column(String(2000), nullable=True, comment="关键价位JSON")
    detail_text = Column(String(2000), nullable=True, comment="形态详情自然语言")

    # ── L3: 关键价位 ──
    strong_support = Column(Numeric(15, 4), nullable=True, comment="强支撑")
    neckline = Column(Numeric(15, 4), nullable=True, comment="颈线")
    target_1 = Column(Numeric(15, 4), nullable=True, comment="第一目标")
    target_2 = Column(Numeric(15, 4), nullable=True, comment="第二目标")
    stop_loss = Column(Numeric(15, 4), nullable=True, comment="止损位")

    # ── L4: 多维度验证 ──
    validation_json = Column(String(3000), nullable=True, comment="多维度验证JSON")

    # ── L5: 持仓联动 ──
    actionable_json = Column(String(2000), nullable=True, comment="持仓联动建议JSON")

    # 置信度
    confidence = Column(String(10), nullable=True, comment="总评：高/中/低")

    # 置信度量化（3项10分制）+ 提升触发条件
    confidence_scores_json = Column(
        String(500), nullable=True,
        comment="置信度3项评分JSON: form_completeness/volume_match/key_level_distance"
    )
    confidence_upgrade_hint = Column(
        String(500), nullable=True,
        comment="提升置信度的触发条件，自然语言一句话"
    )

    # 原始LLM响应（调试用）
    raw_response = Column(String(8000), nullable=True, comment="原始LLM响应")

    # JSON解析状态
    parse_status = Column(
        String(10), nullable=True, default="success",
        comment="解析状态: success/partial/fail"
    )

    created_at = Column(
        DateTime, default=datetime.now, nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now,
        nullable=False, comment="更新时间"
    )

    # 联合唯一约束：同一股票同一天同一周期只能有一条记录
    __table_args__ = (
        UniqueConstraint("stock_symbol", "analysis_date", "period", name="uix_pattern_analysis"),
    )

    def __repr__(self) -> str:
        return (
            f"<PatternAnalysis(symbol='{self.stock_symbol}', "
            f"date={self.analysis_date}, pattern='{self.pattern_name}', "
            f"state='{self.pattern_state}')>"
        )
