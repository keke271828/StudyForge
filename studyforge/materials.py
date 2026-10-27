"""Read preserved originals for generation; preview text is never the source of truth."""
from __future__ import annotations

import hashlib
import copy
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from .parsers import parse_file
from .json_digest import sha256 as json_sha256

MEDIA = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.mp3', '.wav', '.m4a', '.ogg', '.flac', '.sfvideo'}


async def read_original_sources_async(records):
    """Cached evidence/hash IO stays responsive while another native job runs.

    A cache miss may require OCR; its native inference still shares the process
    gate. Cached originals and archived video capsules do not run inference.
    """
    from .scheduling import run_owned_io
    from .task_timing import timed_call
    return await run_owned_io(timed_call, 'original_read', '原文件读取与版本核对', read_original_sources, records)
_PARSED = OrderedDict()
_CACHE_LOCK = threading.RLock()
_PARSING = {}
_CACHE_CHAR_LIMIT = 2_000_000


def file_sha256(path):
    with Path(path).open('rb') as stream:
        # Small sampled PNGs otherwise each allocate file_digest's 256 KiB
        # buffer, even for a tiny file. Keep the same large-file buffer size.
        buffer=bytearray(min(256*1024,max(4096,os.fstat(stream.fileno()).st_size)))
        view=memoryview(buffer);digest=hashlib.sha256()
        while count:=stream.readinto(buffer):digest.update(view[:count])
        return digest.hexdigest()


def asset_fingerprints(parts):
    paths = sorted({str(Path(item['meta']['image_path']).resolve()) for item in parts
                    if item.get('meta', {}).get('image_path')})
    return [(path, file_sha256(path) if Path(path).is_file() else None) for path in paths]


def clear_original_cache():
    with _CACHE_LOCK:
        _PARSED.clear()


def remember_parsed_original(path, digest, parts):
    """Reuse the actual parser output only while the preserved original matches."""
    if file_sha256(path) != digest:
        raise ValueError(f'原文件在解析期间变更：{path.name}，请重试')
    weight = sum(len(str(item.get('text', ''))) for item in parts)
    if weight > _CACHE_CHAR_LIMIT:
        return
    key = (str(path.resolve()), digest, id(parse_file))
    entry = {'parts': copy.deepcopy(parts), 'assets': asset_fingerprints(parts), 'weight': weight}
    with _CACHE_LOCK:
        _PARSED[key] = entry
        while len(_PARSED) > 8 or sum(x['weight'] for x in _PARSED.values()) > _CACHE_CHAR_LIMIT:
            _PARSED.popitem(last=False)


def parsed_original(path, digest):
    key = (str(path.resolve()), digest, id(parse_file))
    while True:
        with _CACHE_LOCK:
            cached = _PARSED.get(key)
        # A large video's disk verification must not hold the shared cache lock
        # and block an unrelated cached textbook or text file.
        valid = cached and cached['assets'] == asset_fingerprints(cached['parts'])
        with _CACHE_LOCK:
            if valid and _PARSED.get(key) is cached:
                _PARSED.move_to_end(key)
                return copy.deepcopy(cached['parts']), True
            if _PARSED.get(key) is not cached:
                continue
            _PARSED.pop(key, None)
            pending = _PARSING.get(key)
            if pending is None:
                _PARSING[key] = pending = threading.Event()
                break
        pending.wait()
    try:
        parts = parse_file(path)
        remember_parsed_original(path, digest, parts)
        return parts, False
    finally:
        with _CACHE_LOCK:
            _PARSING.pop(key, None)
            pending.set()


def read_original_sources(records: list[dict]) -> list[dict]:
    from .source_origins import identify
    origins=identify(records)
    result = []
    for record in records:
        started = time.perf_counter()
        if record.get('status') == 'stored':
            from .source_scope import parsing_policy
            policy = parsing_policy(record)
            if not policy['partial_parse_supported']:
                action = '解析网址' if policy['parse_type'] == 'url' else '解析图片'
                raise ValueError(f"资料尚未解析：{record['name']}。请先点击“{action}”，无需选择页码或原文选段")
            raise ValueError(f"资料尚未解析：{record['name']}。请先选择全文、PDF 页码或原文选段；入库不等于授权读取全文")
        path = Path(record.get('original_path') or '')
        if not path.is_file():
            raise ValueError(f"原文件不存在：{record['name']}。请重新导入；无法仅凭预览生成讲解")
        digest = file_sha256(path)
        # Media already has a full transcript and sampled frames from the original;
        # repeating speech recognition for every regeneration adds no fidelity.
        media = path.suffix.lower() in MEDIA
        if path.suffix.lower() == '.sfvideo':
            parts, cache_hit = parsed_original(path, digest)
            imported_checksum = digest
        elif media:
            parts, cache_hit = copy.deepcopy(record.get('segments', [])), False
            imported_checksum = parts[0].get('meta', {}).get('original_media_sha256') if parts else None
            if imported_checksum and imported_checksum != digest:
                raise ValueError(f"媒体原文件已变更，原转录和画面不再对应：{record['name']}，请重新导入")
        else:
            parts, cache_hit = parsed_original(path, digest)
        if media:
            from .video_records import recognized_parts
            parts = recognized_parts(parts)
        if not parts:
            raise ValueError(f"原文件没有可读取内容：{record['name']}")
        characters = sum(len(str(part.get('text', ''))) for part in parts)
        if any('\ufffd' in str(part.get('text', '')) for part in parts):
            raise ValueError(f"原文件识别文本存在无法辨认的字符：{record['name']}。请核对编码或 OCR 后重试")
        assets = asset_fingerprints(parts)
        content_hash = json_sha256([parts, assets], sort_keys=True, default=str)
        manifest = {
            'source_id': record['id'], 'name': record['name'], 'original_path': str(path.resolve()),
            'sha256': digest, 'bytes': path.stat().st_size, 'segments': len(parts),
            'characters': characters, 'method': 'full_transcript_and_frames' if media else 'original_file',
            'content_sha256': content_hash, 'parse_cache_hit': cache_hit,
            'read_seconds': round(time.perf_counter() - started, 4),
            'content_origin':origins[record['id']],
            'limitations': [('语音使用站点提供的字幕，画面为抽取帧，须结合原视频核对'
                             if any(part.get('meta', {}).get('method') == 'video_subtitle' for part in parts)
                             else '语音为自动转录，画面为抽取帧，须结合原视频核对')] if media else [],
        }
        for part in parts:
            if part.get('meta', {}).get('recognition_issue_count'):
                manifest['limitations'].append(f"{part['locator']}：{part['meta']['recognition_issue_count']}处识别异常已标为[无法辨认]，不能据此补造文字或公式")
            if '[OCR 未完成：' in str(part.get('text', '')):
                manifest['limitations'].append(f"{part['locator']}：OCR 未成功，须通过原图核对")
        if origins[record['id']].get('artifact_id'):
            manifest['artifact_id'] = origins[record['id']]['artifact_id']
            role=origins[record['id']]['role']
            manifest['limitations'].append('此资料是本项目成果文件；AI讲解和推导仍需核对依据，不自动视作权威原文'
                if role=='ai_generated_artifact' else '此资料是整理的来源记录，可能包含自动识别误差；不代表重新核对了原视频或原资料'
                if role=='derived_source_record' else '此资料是外部附加或类型未知的成果，作者与真实性未认证')
        if path.suffix.lower() == '.sfscope':
            from .db import one
            scope = one('SELECT * FROM source_scopes WHERE source_id=?', (record['id'],))
            if not scope:
                raise ValueError('内部选段文件缺少原资料范围记录；请重新从资料选择范围')
            manifest['method'] = 'explicit_selected_scope'
            manifest['selection_mode'] = scope['mode']
            manifest['original_source_id'] = scope['original_source_id']
            manifest['limitations'].append('只读取用户选择的范围，没有通读其余原资料；不能声称已经理解整本书')
            if not scope['original_source_id']:
                manifest['limitations'].append('原资料已删除，保留的选段仍可阅读，但不能回查已删除的完整原文件')
            if any(part.get('meta', {}).get('source_text_verified') is False for part in parts):
                manifest['limitations'].append('此段原文由用户手动提供，尚未与完整原文件逐字核对')
        if media and not imported_checksum:
            manifest['limitations'].append('此旧资料的转录没有保存原媒体校验绑定；不能确认后续文件变更是否影响转录，重新导入可建立绑定')
        if path.suffix.lower() == '.sfvideo':
            metadata = parts[0].get('meta', {}).get('video_record_metadata', {})
            manifest['limitations'].append(metadata.get('limitation') or '此资料是可复用的视频识别记录；原网址的视频临时副本已清理，重新提取画面需要重新读取原网址')
        for image_path, checksum in assets:
            if checksum is None:
                manifest['limitations'].append(f'抽取图像缺失：{Path(image_path).name}，须核对原文件或重新导入')
        if path.suffix.lower() in ('.html', '.htm') and b'<img' in path.read_bytes().lower():
            manifest['limitations'].append('网页图像仅读取文本标注或公式替代文字，须结合原网页核对图表')
        # Actual originals remain complete; the old preview JSON/list are no
        # longer needed once original validation has succeeded.
        result.append(dict((key, value) for key, value in record.items()
                           if key not in ('segments_json', 'segments')) | dict(segments=parts, read_manifest=manifest))
    return result
