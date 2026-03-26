"""
投资中枢路由 - 读取docs目录下的md文件渲染为网页
零数据库查询，零token消耗，只读文件
"""
import os
import re
import markdown
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

DOCS_DIR = Path("docs")

MD_EXTENSIONS = ["tables", "fenced_code", "nl2br", "sane_lists"]


def render_md(path: Path) -> str:
    """读取md文件并渲染为HTML"""
    text = path.read_text(encoding="utf-8")
    return markdown.markdown(text, extensions=MD_EXTENSIONS)


def get_reports() -> list[dict]:
    """扫描docs目录，找出所有体检报告，按日期倒序"""
    reports = []
    pattern = re.compile(r"持仓体检报告_(\d{8})\.md$")
    for f in DOCS_DIR.glob("持仓体检报告_*.md"):
        m = pattern.match(f.name)
        if m:
            date_str = m.group(1)
            try:
                date = datetime.strptime(date_str, "%Y%m%d")
                reports.append({
                    "filename": f.name,
                    "date_str": date_str,
                    "date_display": date.strftime("%Y年%m月%d日"),
                    "path": f,
                })
            except ValueError:
                continue
    return sorted(reports, key=lambda x: x["date_str"], reverse=True)


@router.get("/")
def investment_report(request: Request):
    """最新体检报告"""
    reports = get_reports()
    if not reports:
        html_content = "<p>暂无体检报告，请先运行五维雷达体检。</p>"
        latest = None
    else:
        latest = reports[0]
        html_content = render_md(latest["path"])

    return templates.TemplateResponse("investment_report.html", {
        "request": request,
        "active_page": "investment",
        "html_content": html_content,
        "latest": latest,
        "reports": reports,
    })


@router.get("/archive")
def investment_archive(request: Request):
    """历史报告列表"""
    reports = get_reports()
    return templates.TemplateResponse("investment_archive.html", {
        "request": request,
        "active_page": "investment",
        "reports": reports,
    })


@router.get("/archive/{date_str}")
def investment_archive_detail(date_str: str, request: Request):
    """查看指定日期的历史报告"""
    filename = f"持仓体检报告_{date_str}.md"
    path = DOCS_DIR / filename
    if not path.exists():
        html_content = "<p>报告不存在。</p>"
        date_display = date_str
    else:
        html_content = render_md(path)
        try:
            date_display = datetime.strptime(date_str, "%Y%m%d").strftime("%Y年%m月%d日")
        except ValueError:
            date_display = date_str

    reports = get_reports()
    return templates.TemplateResponse("investment_report.html", {
        "request": request,
        "active_page": "investment",
        "html_content": html_content,
        "latest": {"date_display": date_display, "date_str": date_str},
        "reports": reports,
        "is_archive": True,
    })


@router.get("/profile")
def investment_profile(request: Request):
    """投资档案 + 系统说明"""
    profile_path = DOCS_DIR / "光剑系统-投资辅助系统说明.md"
    framework_path = DOCS_DIR / "光剑系统-持仓体检框架-五维雷达.md"

    profile_html = render_md(profile_path) if profile_path.exists() else "<p>文件不存在</p>"
    framework_html = render_md(framework_path) if framework_path.exists() else "<p>文件不存在</p>"

    return templates.TemplateResponse("investment_profile.html", {
        "request": request,
        "active_page": "investment",
        "profile_html": profile_html,
        "framework_html": framework_html,
    })
