"""Local presentation assets, kept separate from learning materials and AI context."""
from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import data_dir


BACKGROUND_DEFAULTS = {
    'ui_background': 'none', 'ui_background_asset': '', 'ui_background_name': '',
    'ui_background_transparency': 35, 'ui_background_blur': 8,
    'ui_background_x': 50, 'ui_background_y': 50,
    'ui_background_quiet_focus': True,
}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000


def background_path(asset_id: str) -> Path:
    if not isinstance(asset_id, str) or not re.fullmatch(r'[a-f0-9]{64}', asset_id):
        raise ValueError('背景图片标识无效')
    folder = data_dir() / 'appearance'
    path = folder / (asset_id + '.png')
    # A folder authorization must never turn a background URL into a file reader.
    if folder.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(data_dir()):
        raise ValueError('背景文件位置无效')
    return path


def validate_background_settings(value: dict) -> None:
    if 'ui_background' in value and (not isinstance(value['ui_background'], str)
            or value['ui_background'] not in {'none', 'mist', 'dusk', 'aurora', 'image'}):
        raise ValueError('背景方案无效')
    for key, low, high in [('ui_background_transparency', 0, 100), ('ui_background_blur', 0, 24),
                          ('ui_background_x', 0, 100), ('ui_background_y', 0, 100),
                          ('ui_surface_opacity', 0, 100)]:
        if key in value and (type(value[key]) is not int or not low <= value[key] <= high):
            raise ValueError(f'{key} 必须是 {low} 到 {high} 之间的整数')
    if 'ui_background_quiet_focus' in value and type(value['ui_background_quiet_focus']) is not bool:
        raise ValueError('专注模式淡化背景必须是开关值')
    if 'ui_background_asset' in value and value['ui_background_asset']:
        if not background_path(value['ui_background_asset']).is_file():
            raise ValueError('背景图片不存在，请重新上传')
    elif 'ui_background_asset' in value and value['ui_background_asset'] != '':
        raise ValueError('背景图片标识无效')
    if 'ui_background_name' in value:
        name = value['ui_background_name']
        if not isinstance(name, str) or len(name) > 180 or any(ord(char) < 32 for char in name):
            raise ValueError('背景图片名称无效')


def normalize_image(raw: bytes) -> bytes:
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError('请选择不超过 20 MB 的 PNG、JPEG 或 WebP 图片')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise ValueError('背景只支持 PNG、JPEG 和 WebP 静态图片')
                if getattr(source, 'is_animated', False):
                    raise ValueError('请选择静态背景，动画图片会影响长时间阅读')
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError('图片分辨率过大，请使用不超过 3200 万像素的图片')
                image = ImageOps.exif_transpose(source)
                image.thumbnail((3840, 3840), Image.Resampling.LANCZOS)
                image = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
                # Save freshly decoded pixels: metadata/EXIF and embedded files are not copied.
                clean = Image.new(image.mode, image.size)
                clean.paste(image)
                output = io.BytesIO()
                clean.save(output, format='PNG')
                return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('图片无法读取，请换一张完整的 PNG、JPEG 或 WebP 图片') from exc


def _remove_asset(asset_id: str) -> None:
    if not asset_id:
        return
    try:
        background_path(asset_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass  # Never remove an unchecked path; a locked old file can remain harmlessly.


def install_background(raw: bytes, filename: str) -> dict:
    from .ai import _SETTINGS_LOCK, save_settings, settings

    pixels = normalize_image(raw)
    asset_id = hashlib.sha256(pixels).hexdigest()
    name = re.split(r'[/\\]', filename or '背景图片')[-1]
    name = ''.join(char for char in name if ord(char) >= 32)[:180] or '背景图片'
    with _SETTINGS_LOCK:
        path = background_path(asset_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.is_file()
        old_asset = settings().get('ui_background_asset', '')
        descriptor, pending_name = tempfile.mkstemp(prefix='.background-', suffix='.tmp', dir=path.parent)
        pending = Path(pending_name)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(pixels)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(pending, path)
            result = save_settings({'ui_background': 'image', 'ui_background_asset': asset_id,
                                    'ui_background_name': name})
        except Exception:
            if not existed:
                _remove_asset(asset_id)
            raise
        finally:
            pending.unlink(missing_ok=True)
        if old_asset != asset_id:
            _remove_asset(old_asset)
        return result


def remove_background(reset: bool = False) -> dict:
    from .ai import _SETTINGS_LOCK, save_settings, settings

    with _SETTINGS_LOCK:
        current = settings()
        values = BACKGROUND_DEFAULTS.copy() if reset else {'ui_background_asset': '', 'ui_background_name': ''}
        if not reset and current.get('ui_background') == 'image':
            values['ui_background'] = 'none'
        result = save_settings(values)
        _remove_asset(current.get('ui_background_asset', ''))
        return result


MAX_FONT_BYTES = 50 * 1024 * 1024


def font_path(asset_id):
    if not isinstance(asset_id,str) or not re.fullmatch(r'[a-f0-9]{64}',asset_id):
        raise ValueError('字体标识无效')
    folder=data_dir()/'appearance'/'fonts';path=folder/(asset_id+'.font')
    if folder.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(data_dir()):
        raise ValueError('字体文件位置无效')
    return path


def normalize_font(raw):
    """Parse and reserialize tables; arbitrary renamed files are not served as fonts."""
    from fontTools.ttLib import TTFont
    if not raw or len(raw)>MAX_FONT_BYTES or raw[:4] not in (b'\x00\x01\x00\x00',b'OTTO',b'wOFF',b'wOF2'):
        raise ValueError('请选择不超过 50 MB 的 TTF、OTF、WOFF 或 WOFF2 字体')
    if raw[:4] in (b'wOFF',b'wOF2') and len(raw)>=20 and int.from_bytes(raw[16:20],'big')>MAX_FONT_BYTES:
        raise ValueError('解码后的字体超过 50 MB，请选择其他字体')
    try:
        with TTFont(io.BytesIO(raw),lazy=False) as font:
            if not {'head','maxp','cmap','name'} <= set(font.keys()): raise ValueError('字体缺少必要表')
            if font['maxp'].numGlyphs<1 or not font.getBestCmap(): raise ValueError('字体没有可用字符')
            # Resolve every table before saving; truncated directory offsets cannot pass.
            for tag in font.keys(): font[tag]
            font.flavor=None
            buffer=io.BytesIO();font.save(buffer)
            result=buffer.getvalue()
            if len(result)>MAX_FONT_BYTES: raise ValueError('解码后的字体超过 50 MB')
            return result
    except (ImportError,ModuleNotFoundError) as exc:
        raise ValueError('本机缺少 WOFF2 解码组件，请选择 TTF 或 OTF 字体') from exc
    except Exception as exc:
        raise ValueError('字体文件无法解析，请使用完整的 TTF、OTF、WOFF 或 WOFF2 字体') from exc


def install_font(raw,filename):
    from .ai import _SETTINGS_LOCK,save_settings,settings
    content=normalize_font(raw);asset=hashlib.sha256(content).hexdigest()
    name=''.join(char for char in re.split(r'[/\\]',filename or '自定义字体')[-1] if ord(char)>=32)[:180]
    with _SETTINGS_LOCK:
        path=font_path(asset);path.parent.mkdir(parents=True,exist_ok=True)
        old=settings().get('ui_font_asset','');existed=path.is_file()
        descriptor,pending_name=tempfile.mkstemp(prefix='.font-',suffix='.tmp',dir=path.parent);pending=Path(pending_name)
        try:
            with os.fdopen(descriptor,'wb') as handle:
                handle.write(content);handle.flush();os.fsync(handle.fileno())
            os.replace(pending,path)
            result=save_settings({'ui_font_family':'custom','ui_font_asset':asset,'ui_font_name':name})
        except Exception:
            if not existed:path.unlink(missing_ok=True)
            raise
        finally:pending.unlink(missing_ok=True)
        if old and old!=asset:
            try:font_path(old).unlink(missing_ok=True)
            except (OSError,ValueError):pass
        return result


def remove_font():
    from .ai import _SETTINGS_LOCK,save_settings,settings
    with _SETTINGS_LOCK:
        current=settings();values={'ui_font_asset':'','ui_font_name':''}
        if current['ui_font_family']=='custom':values['ui_font_family']='system'
        result=save_settings(values)
        if current['ui_font_asset']:
            try:font_path(current['ui_font_asset']).unlink(missing_ok=True)
            except (OSError,ValueError):pass
        return result
