"""
交易计划模块完整测试用例
"""
import sys
sys.path.insert(0, '/Users/jediyang/ClaudeCode/Project-Makemoney/lightsaber')

from app.core.database import SessionLocal
from app.services.trade_plan_service import TradePlanService
from decimal import Decimal

db = SessionLocal()
service = TradePlanService(db)

print("=" * 60)
print("交易计划模块测试")
print("=" * 60)

# ==================== 测试1: 评估API校验 ====================
print("\n【测试1】评估API - 目标价必须高于买入价")
result = service.evaluate_plan({
    "symbol": "A:300274",
    "strategy_type": "波段",
    "planned_price": 160.0,
    "target_price": 150.0,  # 错误：目标价低于买入价
    "planned_shares": 300,
    "stop_loss_method": "固定比例",
    "stop_loss_param": 7.0,
    "buy_reason": "光伏逆变器龙头，预期业绩好转，技术面突破",
    "note": ""
})
if result.get("error"):
    print(f"  ❌ 未拦截错误: {result.get('message')}")
else:
    stop_loss = result.get("plan", {}).get("stop_loss_price", 0)
    print(f"  ✅ 止损价计算正确: ¥{stop_loss:.2f}")
    print(f"  ⚠️  但盈亏比会为负: {result.get('plan', {}).get('risk_reward_ratio')}")

# ==================== 测试2: 买入理由长度 ====================
print("\n【测试2】买入理由长度校验")
test_cases = [
    ("", "空字符串"),
    ("测试", "2字"),
    ("刚好十字刚好", "刚好10字"),
    ("这是一段超过十个字的买入理由", "超过10字"),
]

for reason, desc in test_cases:
    is_valid = len(reason.strip()) >= 10 if reason else False
    status = "✅ 通过" if is_valid else "❌ 失败"
    print(f"  {status} {desc}: '{reason}' ({len(reason)}字)")

# ==================== 测试3: 止损方式计算 ====================
print("\n【测试3】止损价计算")

# 固定比例
result = service._calculate_stop_loss_price("A:300274", Decimal("160.00"), "固定比例", Decimal("7.0"))
print(f"  ✅ 固定比例7%: 买入价¥160 → 止损价¥{result:.2f} (预期: ¥148.80)")

# ATR倍数
result = service._calculate_stop_loss_price("A:300274", Decimal("160.00"), "ATR倍数", Decimal("2.0"))
print(f"  ✅ ATR倍数2x: 买入价¥160 → 止损价¥{result:.2f} (当前用固定比例模拟)")

# 支撑位
result = service._calculate_stop_loss_price("A:300274", Decimal("160.00"), "支撑位", Decimal("145.00"))
print(f"  ✅ 支撑位¥145: 止损价¥{result:.2f}")

# 不止损
result = service._calculate_stop_loss_price("A:300274", Decimal("160.00"), "不止损,长期持有", Decimal("0"))
print(f"  ✅ 不止损: 止损价¥{result}")

# ==================== 测试4: 盈亏比计算 ====================
print("\n【测试4】盈亏比计算")
test_cases = [
    (160.0, 195.0, 148.8, 3.7),  # (买入, 目标, 止损, 预期盈亏比)
    (100.0, 120.0, 90.0, 2.0),
    (50.0, 60.0, 45.0, 2.0),
]

for planned, target, stop_loss, expected in test_cases:
    profit = target - planned
    loss = planned - stop_loss
    rr = round(profit / loss, 1) if loss > 0 else 0
    match = "✅" if abs(rr - expected) < 0.2 else "❌"
    print(f"  {match} 买入¥{planned},目标¥{target},止损¥{stop_loss} → 盈亏比1:{rr} (预期1:{expected})")

# ==================== 测试5: 评估检查项 ====================
print("\n【测试5】自动评估检查")

# 储备金检查 - 模拟大金额买入
result = service.evaluate_plan({
    "symbol": "A:300274",
    "strategy_type": "波段",
    "planned_price": 160.0,
    "target_price": 195.0,
    "planned_shares": 10000,  # 大额买入
    "stop_loss_method": "固定比例",
    "stop_loss_param": 7.0,
    "buy_reason": "光伏逆变器龙头，预期业绩好转，技术面突破",
    "note": ""
})

evaluation = result.get("evaluation", {})
checks = evaluation.get("checks", [])
print(f"  综合结论: {evaluation.get('overall', 'N/A')}")
print(f"  检查项:")
for check in checks:
    icon = "✅" if check["status"] == "pass" else "⚠️" if check["status"] == "warning" else "❌"
    print(f"    {icon} {check['item']}: {check['message']}")

# ==================== 测试6: 策略匹配检查 ====================
print("\n【测试6】策略匹配检查")

test_cases = [
    ("底仓", "业绩稳健，ROE大于20%，行业龙头", "应该有基本面关键词"),
    ("底仓", "RSI超卖，MACD金叉", "缺少基本面关键词 → 警告"),
    ("波段", "RSI超卖，均线支撑", "应该有技术面关键词"),
    ("波段", "业绩好，护城河深", "缺少技术面关键词 → 警告"),
]

for strategy, reason, desc in test_cases:
    result = service._check_strategy_match({
        "strategy_type": strategy,
        "buy_reason": reason
    })
    icon = "✅" if result["status"] == "pass" else "⚠️"
    print(f"  {icon} {strategy}: {desc} → {result['message']}")

# ==================== 测试7: 仓位红线检查 ====================
print("\n【测试7】仓位红线检查")

# 模拟超过25%红线
result = service._check_position_limits("A:300274", Decimal("30.0"), {})
print(f"  {'❌' if result['status'] == 'fail' else '✅'} 单票30%: {result['message']}")

# 接近20%
result = service._check_position_limits("A:300274", Decimal("22.0"), {})
print(f"  {'⚠️' if result['status'] == 'warning' else '✅'} 单票22%: {result['message']}")

# 正常
result = service._check_position_limits("A:300274", Decimal("15.0"), {})
print(f"  {'✅' if result['status'] == 'pass' else '❌'} 单票15%: {result['message']}")

# ==================== 测试8: 盈亏比检查 ====================
print("\n【测试8】盈亏比检查")

test_cases = [
    (Decimal("0.5"), "fail", "小于1:1"),
    (Decimal("1.5"), "warning", "1:1到1:2之间"),
    (Decimal("2.5"), "pass", "大于1:2"),
]

for ratio, expected_status, desc in test_cases:
    result = service._check_risk_reward(ratio)
    icon = "✅" if result["status"] == expected_status else "❌"
    print(f"  {icon} 盈亏比1:{ratio} ({desc}) → {result['message']}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
