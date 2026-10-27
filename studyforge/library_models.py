"""Library model preferences contain no dialogue, credentials or learner state."""
from __future__ import annotations

from .db import connect, j, now, one, unj

KEY = 'library_reading_models'
DEFAULTS = {'mode': 'follow', 'provider': 'deepseek', 'model': None, 'effort': None,
            'vision_mode': 'configured', 'vision_model': None}


class ModelPreferenceConflict(ValueError):
    pass


def selection():
    row = one('SELECT value FROM workspace_state WHERE key=?', (KEY,))
    saved = unj(row['value'], {}) if row else {}
    return DEFAULTS | saved | {'revision': saved.get('revision', 0)}


def public():
    from .ai import settings
    from .providers import _read
    config = settings()
    # This endpoint is also available to paired phones. Never include keys,
    # account diagnostics, base URLs or unrelated settings in this registry.
    services = [{'id': 'codex', 'name': 'Codex', 'enabled': True,
                 'default_model': config.get('codex_model'), 'models': [], 'supports_vision': True},
                {'id': 'deepseek', 'name': 'DeepSeek', 'enabled': True,
                 'default_model': config.get('deepseek_model') or 'deepseek-flash', 'models': [], 'supports_vision': True}]
    services += [{**{k: r[k] for k in ('id', 'name', 'enabled', 'default_model', 'models')},
                  'supports_vision': bool(r.get('supports_vision'))} for r in _read()]
    return {'selection': selection(), 'services': services,
            'deepseek_vision_model': config.get('deepseek_vision_model') or 'deepseek-flash'}


def validate(value):
    from .providers import model_name, require_provider
    result = {k: value[k] for k in DEFAULTS}
    if result['mode'] == 'independent':
        require_provider(result['provider'])
    for key in ('model', 'vision_model'):
        if result[key] is not None:
            result[key] = model_name(result[key]) if result[key].strip() else None
    if result['effort'] not in (None, 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise ValueError('未知推理强度')
    if result['mode'] == 'independent':
        if result['provider'] == 'deepseek' and result['effort']:
            from .deepseek_protocol import thinking_parameters
            thinking_parameters(result['effort'])
        elif result['provider'] != 'codex' and result['effort']:
            raise ValueError('此服务尚未适配推理强度，请选择自动')
        if result['provider'] != 'deepseek' and result['vision_mode'] != 'configured':
            raise ValueError('独立画面模型目前仅适配 DeepSeek；其他服务使用阅读模型核对原图')
    if result['vision_mode'] == 'custom' and not result['vision_model']:
        raise ValueError('请填写扫描页核对模型')
    return result


def save(value, revision):
    validated = validate(value)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM workspace_state WHERE key=?', (KEY,)).fetchone()
        previous = unj(row['value'], {}) if row else {}
        if previous.get('revision', 0) != revision:
            raise ModelPreferenceConflict('书库模型已在其他窗口更新；请重新载入设置后再保存。当前选择未覆盖。')
        saved = validated | {'revision': revision + 1, 'updated_at': now()}
        db.execute('INSERT INTO workspace_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (KEY, j(saved)))
    return saved


def snapshot(provider, model=None, effort=None, vision_model=None):
    from .ai import settings
    from .providers import default_model, model_name
    # Direct internal fixtures can supply their own provider; public routes
    # validate provider/effort before reaching this function.
    if not model and provider in ('codex', 'deepseek'):
        model = default_model(provider)
    if provider == 'deepseek':
        vision_model = model_name(vision_model) if vision_model else settings().get('deepseek_vision_model') or 'deepseek-flash'
    else:
        if vision_model and vision_model != model:
            raise ValueError('此服务的原图核对使用阅读模型，不支持单独指定画面模型')
        vision_model = model
    return {'provider': provider, 'model': model, 'effort': effort, 'vision_model': vision_model}
