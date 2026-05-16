"""日记只读接口
GET /diary/list  — 返回日记列表（不含正文）
GET /diary/{date} — 返回单篇日记（含正文）
"""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from admin.auth import verify_token

router = APIRouter()

DIARY_DIR = Path(__file__).parent.parent.parent / "data" / "yexuan_inner" / "diary"
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_FILE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')
_STOP_CHARS = '。！？'


def _derive_title(content: str) -> str:
    if not content.strip():
        return '(空)'
    lines = content.split('\n')
    if lines and lines[0].startswith('# '):
        lines = lines[1:]
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('## '):
            continue
        sentence = ''
        for ch in stripped:
            sentence += ch
            if ch in _STOP_CHARS:
                break
        if sentence:
            return sentence[:20] + '…' if len(sentence) > 20 else sentence
    return '(空)'


def _strip_body(content: str) -> str:
    lines = content.split('\n')
    if lines and lines[0].startswith('# '):
        lines = lines[1:]
    return '\n'.join(lines).lstrip('\n')


@router.get("/list", summary="获取日记列表")
async def list_diary(auth=Depends(verify_token)):
    entries = []
    if DIARY_DIR.exists():
        for f in DIARY_DIR.iterdir():
            if not _FILE_RE.match(f.name):
                continue
            content = f.read_text(encoding='utf-8')
            entries.append({
                "date": f.stem,
                "title": _derive_title(content),
                "emotion": None,
            })
    entries.sort(key=lambda e: e["date"], reverse=True)
    return {"entries": entries, "count": len(entries)}


@router.get("/{date}", summary="获取单篇日记")
async def get_diary(date: str, auth=Depends(verify_token)):
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="date format must be YYYY-MM-DD")
    path = DIARY_DIR / f"{date}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="diary not found")
    content = path.read_text(encoding='utf-8')
    return {
        "date": date,
        "title": _derive_title(content),
        "emotion": None,
        "body": _strip_body(content),
    }
