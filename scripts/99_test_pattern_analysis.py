"""
形态分析服务测试脚本

用法:
    cd lightsaber && source venv/bin/activate && python scripts/99_test_pattern_analysis.py [股票代码]

示例:
    python scripts/99_test_pattern_analysis.py HK:00700
    python scripts/99_test_pattern_analysis.py US:MSFT

不传参数则测试微软(MSFT)的已缓存数据（不依赖OpenD）。
"""
import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from datetime import date

from app.core.database import SessionLocal
from app.services.pattern_analysis_service import PatternAnalysisService


def test_with_cached_msft():
    """用已缓存的微软K线数据测试（不依赖OpenD）"""
    print("=" * 60)
    print("测试1: 使用缓存的微软K线数据测试 Prompt 构建和 API 调用")
    print("=" * 60)

    db = SessionLocal()
    try:
        service = PatternAnalysisService(db)

        # 读取之前保存的微软K线数据
        with open("/tmp/msft_kline_formatted.txt", "r") as f:
            kline_text = f.read()

        # 构建Prompt
        prompt = service._build_prompt(
            stock_name="微软",
            symbol="US:MSFT",
            kline_text=kline_text,
            position_info="- 底仓: 100股 @ 400.00\n- 波段: 50股 @ 380.00",
            current_price=421.92,
        )

        print(f"\nPrompt 长度: {len(prompt)} 字符")
        print(f"Prompt 前500字符:\n{prompt[:500]}...")

        # 调用 Claude API
        print("\n正在调用 Claude API (Opus 4.7)...")
        raw = service._call_claude_api(prompt)

        if not raw:
            print("❌ API 调用失败")
            return

        print(f"✅ API 调用成功，响应长度: {len(raw)} 字符")
        print(f"\n原始响应:\n{'-' * 60}")
        print(raw)
        print("-" * 60)

        # 解析JSON
        parsed = service._parse_json_response(raw)
        print(f"\n解析结果:")
        print(f"  形态: {parsed.get('pattern_name', 'N/A')}")
        print(f"  状态: {parsed.get('pattern_state', 'N/A')}")
        print(f"  置信度: {parsed.get('confidence', 'N/A')}")
        print(f"  摘要: {parsed.get('summary', 'N/A')[:100]}...")

        # 保存到数据库
        analysis = service._save_analysis("US:MSFT", date.today(), parsed, raw)
        print(f"\n✅ 已保存到数据库: id={analysis.id}")

    finally:
        db.close()


def test_with_futu(symbol: str):
    """通过富途拉取K线并分析（需要OpenD运行）"""
    print("=" * 60)
    print(f"测试2: 通过富途拉取K线分析 {symbol}")
    print("=" * 60)

    db = SessionLocal()
    try:
        service = PatternAnalysisService(db)

        # 获取股票名称
        from app.models.stock import Stock
        stock = db.get(Stock, symbol)
        stock_name = stock.name if stock else symbol

        print(f"\n分析股票: {stock_name} ({symbol})")
        print("正在拉取K线数据...")

        result = service.analyze_single_stock(symbol, stock_name)

        if result:
            print(f"\n✅ 分析成功!")
            print(f"  形态: {result.pattern_name}")
            print(f"  状态: {result.pattern_state}")
            print(f"  置信度: {result.confidence}")
            print(f"  摘要: {result.summary}")
        else:
            print("\n❌ 分析失败（查看日志了解原因）")

    finally:
        db.close()


def main():
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
        test_with_futu(symbol)
    else:
        # 默认用微软缓存数据测试
        test_with_cached_msft()


if __name__ == "__main__":
    main()
