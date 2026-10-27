"""Explicit reading scopes. Storing a file never authorizes reading its text."""
from __future__ import annotations
import json
from pathlib import Path
import re

from fastapi import HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from .config import files_dir
from .db import connect, execute, j, now, one, uid
from .parsers import PARSERS, parse_image, segment


def parsing_policy(row: dict) -> dict:
    """Original URLs and images have their own whole-resource reading entry."""
    kind = str(row.get('kind') or '').lower()
    if row.get('origin_url') or kind in ('url', 'video_url'):
        source_type = 'url'
    elif kind in PARSERS and PARSERS[kind] is parse_image:
        source_type = 'image'
    else:
        source_type = 'document'
    return {'parse_type': source_type, 'partial_parse_supported': source_type == 'document'}


class ParseIn(BaseModel):
    mode: Literal['full', 'pages', 'text']
    page_spec: str = Field(default='', max_length=300)
    selected_text: str = Field(default='', max_length=160000)
    locator: str = Field(default='', max_length=200)


def page_numbers(spec: str, count: int) -> list[int]:
    values = set()
    for item in re.sub(r'[，、;；\s]+', ',', spec.strip()).split(','):
        if not item:
            continue
        match = re.fullmatch(r'(\d+)(?:\s*[-–—~至]\s*(\d+))?', item)
        if not match:
            raise ValueError('页码格式例如 3 或 3-5,8；使用 PDF 文件页码，从 1 开始')
        start, end = int(match[1]), int(match[2] or match[1])
        if start < 1 or end < start or end > count:
            raise ValueError(f'页码超出范围或顺序错误；此 PDF 共 {count} 页')
        if end - start > 59:
            raise ValueError('一次最多选择 60 页；整本阅读请明确选择全文解析')
        values.update(range(start, end + 1))
    if not values or len(values) > 60:
        raise ValueError('请选择 1 至 60 页')
    return sorted(values)


def natural_pages(text: str) -> str | None:
    # Deliberately narrow: ambiguous chapter/printed-page references are asked
    # back to the learner rather than silently expanded to a whole book.
    match = re.search(r'第\s*(\d+)\s*(?:页)?\s*[-–—~到至]\s*(?:第\s*)?(\d+)\s*页', text)
    if match:
        return match[1] + '-' + match[2]
    match = re.search(r'第\s*(\d+)\s*页', text)
    return match[1] if match else None


def explicit_full(text: str) -> bool:
    if re.search(r'(不要|不必|不用|不需要|禁止|别|仅|只).{0,10}(全文|整本|通读|全部内容)', text):
        return False
    return bool(re.search(r'全文|整本|通读|全部内容|完整阅读|完整解析', text))


def needs_excerpt(text: str) -> bool:
    # Text blocks do not reliably equal logical book paragraphs. Ask for an
    # exact selection instead of silently expanding to a page or chapter.
    return bool(re.search(r'第\s*[\d一二三四五六七八九十百]+\s*(段|章|节)|'
                          r'(只|仅).{0,12}(这段|那段|某段|选中.{0,4}(文字|原文)|一段文字)', text))


def request_scope(text: str) -> dict:
    """A compact authority discriminator; not the student's raw question."""
    return {'version':1, 'page_spec':natural_pages(text),
            'excerpt_requested':needs_excerpt(text), 'full_read_requested':explicit_full(text)}


def read_pdf_pages(path: Path, spec: str) -> list[dict]:
    """Render/OCR only selected pages, never parse other pages first."""
    import fitz
    from .parsers import _ocr
    from .config import derived_dir
    parts = []
    with fitz.open(path) as document:
        pages = page_numbers(spec, len(document))
        for number in pages:
            page = document[number - 1]
            text = page.get_text('text')
            image_path = None
            if page.get_images(full=True) or page.get_drawings() or len(text.strip()) < 30:
                image = derived_dir(path, 'selected-pdf-pages') / f'page-{number}.png'
                page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(image)
                image_path = str(image)
            if len(text.strip()) < 30:
                text = _ocr(Path(image_path))
            parts.append(segment(f'第 {number} 页', text, 'page', image_path=image_path,
                original_page=number, reading_scope='selected_pages'))
    return parts


def preview_page(row: dict, number: int) -> dict:
    if not parsing_policy(row)['partial_parse_supported']:
        raise ValueError('网址和图片使用独立解析入口，不提供部分解析或页码预览')
    if row['kind'].lower() != '.pdf':
        raise ValueError('页码预览目前支持 PDF；其他格式可以粘贴选中的原文或明确选择全文')
    import fitz
    with fitz.open(row['original_path']) as document:
        if number < 1 or number > len(document):
            raise ValueError(f'页码超出范围；此 PDF 共 {len(document)} 页')
        return {'page': number, 'page_count': len(document), 'text': document[number - 1].get_text('text'),
                'locator': f'第 {number} 页', 'note': '只读取了这一页；扫描页可以按页解析识别'}


def derived_source(row: dict, value: ParseIn) -> dict:
    if not parsing_policy(row)['partial_parse_supported']:
        raise ValueError('网址和图片不参与部分解析，请使用“解析网址”或“解析图片”')
    if value.mode == 'pages':
        if row['kind'].lower() != '.pdf':
            raise ValueError('按页解析目前支持 PDF；其他格式请选择选中文字或全文解析')
        parts = read_pdf_pages(Path(row['original_path']), value.page_spec)
        label = f'第 {value.page_spec} 页'
    elif value.mode == 'text':
        text = value.selected_text.strip()
        if not text:
            raise ValueError('请先选中文字或粘贴需要讲解的原文')
        verified = False
        if row['kind'].lower() == '.pdf' and value.page_spec:
            # Text-only verification does not render/OCR even this page.
            import fitz
            with fitz.open(row['original_path']) as document:
                pages = page_numbers(value.page_spec, len(document))
                selected = '\n'.join(document[number - 1].get_text('text') for number in pages)
            normalized = lambda string: re.sub(r'\s+', ' ', string).strip()
            if normalized(text) not in normalized(selected):
                raise ValueError('选中文字未能在指定 PDF 页中精确核对；请重新选取，或清空页码并注明为手动提供的原文')
            verified = True
        label = value.locator.strip() or (f'第 {value.page_spec} 页选段' if value.page_spec else '用户选段')
        parts = [segment(label, text, 'text', reading_scope='selected_text', source_text_verified=verified)]
    else:
        raise ValueError('全文解析使用原文件，不创建选段')
    if not any(str(part['text']).strip() for part in parts):
        raise ValueError('所选范围没有识别到文字，请核对原页或选段')
    ident, path = uid(), files_dir() / (uid() + '.sfscope')
    record = {'schema': 'studyforge-selected-source-v1', 'origin_name': row['name'], 'origin_id': row['id'], 'segments': parts}
    path.write_text(j(record), encoding='utf-8')
    timestamp = now()
    try:
        with connect() as database:
            database.execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at,category_id) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (ident, row['project_id'], row['name'] + ' · ' + label, '.sfscope', str(path), j(parts), 'ready', None, timestamp, row.get('category_id')))
            database.execute('INSERT INTO source_scopes VALUES (?,?,?,?,?)',
                (ident, row['id'], value.mode, j({'page_spec': value.page_spec, 'locator': label}), timestamp))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'source_id': ident, 'original_source_id': row['id'], 'status': 'ready', 'scope': value.mode, 'job_id': None}


def parse_scope_file(path: Path) -> list[dict]:
    # The internal format can carry image paths. Only app-created, registered
    # selections may use it; an uploaded lookalike is never trusted.
    trusted = one('SELECT s.id FROM sources s JOIN source_scopes sc ON sc.source_id=s.id WHERE s.original_path=?', (str(path),))
    if not trusted or not path.resolve().is_relative_to(files_dir().resolve()):
        raise ValueError('这是软件内部的选段格式，不能作为外部资料导入；原文件已保留')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema') != 'studyforge-selected-source-v1' or not isinstance(value.get('segments'), list):
        raise ValueError('选段文件格式无效')
    if len(value['segments']) > 60:
        raise ValueError('选段文件超过范围限制')
    return [segment(str(item['locator']), str(item['text']), str(item.get('kind', 'text')),
                    **dict(item.get('meta', {}))) for item in value['segments']]


PARSERS['.sfscope'] = parse_scope_file


def register_routes(app):
    from . import server

    def source(ident):
        row = one('SELECT * FROM sources WHERE id=?', (ident,))
        if not row:
            raise HTTPException(404, '资料不存在')
        server.require_project(row['project_id'])
        if row['status'] == 'pending':
            raise HTTPException(409, '这份资料正在解析；其他资料和对话仍可使用')
        return row

    @app.get('/api/sources/{ident}/page')
    async def page(ident: str, page: int = 1):
        try:
            return await __import__('asyncio').to_thread(preview_page, source(ident), page)
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/sources/{ident}/parse')
    async def parse(ident: str, value: ParseIn):
        row = source(ident)
        if value.mode != 'full':
            try:
                from .local_compute import run_source_io
                return await run_source_io(derived_source, row, value,
                    paths=[row['original_path']] if value.mode == 'pages' else [], label='解析所选页 · 本地重任务限流')
            except (ValueError, OSError, RuntimeError) as exc:
                raise HTTPException(400, str(exc)) from exc
        if row['status'] == 'ready':
            return {'source_id': ident, 'status': 'ready', 'job_id': None, 'cached': True, 'scope': 'full'}
        # Claim the source atomically so repeated clicks cannot start duplicate
        # full-book parsers while other uploads and chats remain independent.
        from .db import connect, create_job
        with connect() as database:
            changed = database.execute("UPDATE sources SET status='pending',error=NULL WHERE id=? AND status IN ('stored','error')", (ident,)).rowcount
        if not changed:
            raise HTTPException(409, '这份资料已开始解析，请查看任务进度')
        from .job_control import start_job
        url = row.get('origin_url') or (row['original_path'] if row['kind'] in ('url', 'video_url') else None)
        if url:
            job_id = create_job(row['project_id'], 'import_url', {'source_id': ident, 'url': url})
            operation = server._url_job(job_id, ident, url)
        else:
            job_id = create_job(row['project_id'], 'import', {'source_id': ident})
            operation = server._import_job(job_id, ident, Path(row['original_path']))
        start_job(job_id, operation)
        return {'source_id': ident, 'job_id': job_id, 'scope': 'full'}
