"""Preserve timed recognition and frames before disposing of downloaded media."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path

from .config import files_dir, temp_dir

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.avi'}
INVALID = re.compile(r'[\ufffd\ud800-\udfff\ufffe\uffff\x00-\x08\x0b\x0e-\x1f]')


def recognized_parts(parts):
    """Keep the usable text and exact evidence of recognition failures."""
    result = copy.deepcopy(parts)
    for part in result:
        if isinstance(part.get('locator'),str):part['locator']=INVALID.sub('[无法辨认]',part['locator'])
        value = str(part.get('text', '')).replace('\x0c', '\n')
        problems = [{'offset': match.start(), 'codepoint': f'U+{ord(match[0]):04X}'} for match in INVALID.finditer(value)]
        if problems:
            meta = part.setdefault('meta', {})
            meta.update(recognition_issue_count=len(problems), recognition_issues=problems[:50],
                        recognition_text_sha256=hashlib.sha256(value.encode('utf-8', errors='surrogatepass')).hexdigest())
            part['text'] = INVALID.sub('[无法辨认]', value)
        else:
            part['text'] = value
    return result


def record_frames_dir(path):
    return path.with_suffix('.frames')


def write_record(path, parts, *, url='', title='', metadata=None):
    path = Path(path).resolve()
    if path.suffix != '.sfvideo' or not path.is_relative_to(files_dir()) and not path.is_relative_to(temp_dir()):
        raise ValueError('视频记录必须保存到软件的资料或临时目录')
    asset_dir = record_frames_dir(path)
    asset_dir.mkdir(exist_ok=True)
    prepared = recognized_parts(parts)
    for index, part in enumerate(prepared):
        meta = part.setdefault('meta', {})
        image = meta.pop('image_path', None)
        if image and Path(image).is_file():
            source = Path(image).resolve()
            if source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise ValueError('视频记录中的画面格式无效')
            name = f'{index:05d}{source.suffix.lower()}'
            target = asset_dir / name
            if source != target: shutil.copyfile(source, target)
            meta['frame_file'] = name
            meta['frame_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        # The live file hash binds the capsule when it is reopened; not its removed video.
        meta.pop('original_media_sha256', None)
    payload = {'schema': 'studyforge.video/1', 'title': INVALID.sub('[无法辨认]',title), 'source_url': url,
               'metadata': metadata or {}, 'segments': prepared}
    temporary = path.with_suffix('.sfvideo.tmp')
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def read_record(path):
    path = Path(path).resolve()
    if path.stat().st_size > 100 * 1024 * 1024: raise ValueError('视频记录过大')
    payload = json.loads(path.read_text(encoding='utf-8'))
    parts = payload.get('segments')
    if payload.get('schema') != 'studyforge.video/1' or not isinstance(parts, list) or not parts:
        raise ValueError('视频记录不完整，请重新导入视频网址')
    if any(not isinstance(p, dict) or not isinstance(p.get('text'), str) or not isinstance(p.get('locator'), str) or not isinstance(p.get('meta', {}), dict) for p in parts):
        raise ValueError('视频记录的来源结构无效')
    parts = recognized_parts(parts)
    for part in parts:
        meta = part.setdefault('meta', {})
        meta.pop('image_path', None)
        name = meta.get('frame_file')
        if name:
            if not isinstance(name, str) or not re.fullmatch(r'\d{5}\.(?:png|jpg|jpeg|webp)', name):
                raise ValueError('视频记录的画面路径无效')
            image = (record_frames_dir(path) / name).resolve()
            if not image.is_relative_to(record_frames_dir(path).resolve()): raise ValueError('视频画面超出资料范围')
            if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != meta.get('frame_sha256'):
                raise ValueError(f"{part['locator']}的关键画面缺失或已变更，请重新导入视频")
            meta['image_path'] = str(image)
    parts[0]['meta'].update(original_media_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           source_url=payload.get('source_url', ''), video_record=True,
                           video_record_metadata=payload.get('metadata', {}))
    return parts


def archive_remote_video(path, source_id, parts, url, title):
    original = Path(path).resolve()
    # Only the copy made by the URL importer is eligible, never the user's local original.
    if original.parent != files_dir() or original.stem != source_id or original.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError('只能清理本次网址导入创建的视频副本')
    from .materials import file_sha256
    checksum = file_sha256(original)
    target = files_dir() / f'{source_id}.sfvideo'
    write_record(target, parts, url=url, title=title,
                 metadata={'original_media_sha256': checksum, 'original_media_bytes': original.stat().st_size,
                           'mode': 'full', 'temporary_media_removed': True,
                           'limitation': '保留字幕／转录与采样画面；未逐帧观看，自动识别处需核对原视频'})
    return target, read_record(target)


def clean_download(path):
    """Delete one owned UUID download directory, checking its final resolved path."""
    original = Path(path).resolve()
    root = (temp_dir() / 'downloads').resolve()
    folder = original.parent
    if folder.parent == root and re.fullmatch('[a-f0-9]{32}', folder.name) and folder.is_dir():
        shutil.rmtree(folder)
    elif original.parent == temp_dir() and re.fullmatch('[a-f0-9]{32}', original.stem):
        original.unlink(missing_ok=True)


def remove_owned_media(path):
    """Remove an owned remote video and its derived audio/frame cache after archiving."""
    original=Path(path).resolve()
    if not original.is_file() or original.suffix.lower() not in VIDEO_EXTENSIONS:return
    is_library=original.parent==files_dir() and re.fullmatch('[a-f0-9]{32}',original.stem)
    is_download=original.parent.parent==(temp_dir()/'downloads').resolve() and re.fullmatch('[a-f0-9]{32}',original.parent.name)
    is_temporary=original.parent==temp_dir() and re.fullmatch('[a-f0-9]{32}',original.stem)
    if not(is_library or is_download or is_temporary):return
    stat=original.stat();identity=f'{original}\0{stat.st_size}\0{stat.st_mtime_ns}'
    token=hashlib.sha256(identity.encode()).hexdigest()[:24]
    for kind in ('frames','audio'):
        folder=(temp_dir()/f'{kind}-{token}').resolve()
        if folder.parent==temp_dir() and folder.is_dir():shutil.rmtree(folder)
    original.unlink(missing_ok=True)
    original.with_suffix(original.suffix+'.video.json').unlink(missing_ok=True)


def owned_frame(image, original):
    image, original = Path(image).resolve(), Path(original).resolve()
    return original.suffix == '.sfvideo' and image.parent == record_frames_dir(original).resolve()
