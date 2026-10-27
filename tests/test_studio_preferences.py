import pytest

from studyforge.ai import save_settings, settings


def test_appearance_is_saved_without_changing_learning_or_model_preferences():
    save_settings({'learning_mode': 'research', 'deepseek_model': 'chosen-model',
                   'review_mode': 'strict', 'background_learning_enabled': False})
    before = settings()
    values = {'ui_theme': 'night', 'ui_text_size': 'large', 'ui_density': 'compact',
              'ui_motion': 'reduced', 'ui_focus': True, 'ui_send_key': 'ctrl-enter',
              'ui_readability': 'always'}
    save_settings(values)
    after = settings()
    assert all(after[key] == value for key, value in values.items())
    assert all(after[key] == value for key, value in before.items() if key not in values)


@pytest.mark.parametrize('values', [
    {'ui_theme': 'arbitrary'}, {'ui_theme': []}, {'ui_text_size': 'huge'},
    {'ui_density': 'invisible'}, {'ui_motion': 'always'}, {'ui_focus': 'yes'},
    {'ui_send_key': 'any-key'}, {'ui_readability': 'invisible'},
    {'ui_readability': []}, {'ui_readability': True},
])
def test_invalid_appearance_does_not_write_settings(values):
    before = settings()
    with pytest.raises(ValueError):
        save_settings(values)
    assert settings() == before


def test_readability_survives_reload_and_does_not_rewrite_zero_opacity():
    from studyforge import ai
    save_settings({'ui_readability': 'off', 'ui_sidebar_opacity': 0, 'ui_surface_opacity': 0,
                   'ui_background': 'dusk', 'ui_outputs_text_color': '#ffffff'})
    save_settings({'ui_readability': 'always'})
    # Re-read the persisted file, as a fresh process would, without a UI cache.
    current = ai.settings()
    assert current['ui_readability'] == 'always'
    assert current['ui_sidebar_opacity'] == current['ui_surface_opacity'] == 0
    assert current['ui_outputs_text_color'] == '#ffffff'
    assert current['ui_background'] == 'dusk'
