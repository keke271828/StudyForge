"""Independent presentation surfaces. No learning/model settings are changed."""
from __future__ import annotations

import math
import re


SURFACE_BASES = {'canvas': 0, 'sidebar': 95, 'surface': 96, 'context': 96, 'composer': 100,
                 'topbar': 96, 'toolbar': 100, 'controls': 100, 'messages': 0,
                 'settings': 100, 'dialogs': 100, 'outputs': 100}
SURFACE_DEFAULTS = {f'ui_{region}_{field}': value for region, opacity in SURFACE_BASES.items()
                    for field, value in {'opacity':opacity, 'blur':0, 'text_color':'theme',
                                         'stroke_width':0, 'stroke_color':'auto'}.items()}
FONT_DEFAULTS = {'ui_font_family':'system', 'ui_font_asset':'', 'ui_font_name':''}
READABILITY_DEFAULTS = {'ui_readability': 'auto'}


def validate_surface_settings(value):
    if 'ui_readability' in value and (not isinstance(value['ui_readability'], str)
            or value['ui_readability'] not in {'auto', 'always', 'off'}):
        raise ValueError('文字可读性保护须为有背景时启用、始终启用或关闭')
    for region in SURFACE_BASES:
        for field, high in [('opacity',100), ('blur',40)]:
            key=f'ui_{region}_{field}'
            if key in value and (type(value[key]) is not int or not 0 <= value[key] <= high):
                raise ValueError(f'{key} 必须是 0 到 {high} 之间的整数')
        key=f'ui_{region}_stroke_width'
        if key in value and (type(value[key]) not in (int,float) or not math.isfinite(value[key])
                             or not 0 <= value[key] <= 2):
            raise ValueError(f'{key} 必须是 0 到 2 之间的有限数字')
        for field, keywords in [('text_color',{'theme'}), ('stroke_color',{'auto','theme'})]:
            key=f'ui_{region}_{field}'
            if key in value:
                color=value[key]
                if not isinstance(color,str) or (color not in keywords and not re.fullmatch(r'#[0-9a-fA-F]{6}',color)):
                    raise ValueError(f'{key} 必须是六位十六进制颜色或规定选项')
    if 'ui_font_family' in value and (not isinstance(value['ui_font_family'],str) or
            value['ui_font_family'] not in {'system','sans','serif','kai','custom'}):
        raise ValueError('字体选项无效')
    if 'ui_font_asset' in value:
        from .appearance import font_path
        asset=value['ui_font_asset']
        if asset != '' and not font_path(asset).is_file(): raise ValueError('字体文件不存在，请先上传')
        if not isinstance(asset,str): raise ValueError('字体标识无效')
    if 'ui_font_name' in value:
        name=value['ui_font_name']
        if not isinstance(name,str) or len(name)>180 or any(ord(char)<32 for char in name):
            raise ValueError('字体名称无效')
