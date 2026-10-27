"""Freeze the release sources while checking learning and local-help boundaries."""
from scripts import verify_repair_selection as gate

gate.OUT = gate.ROOT / 'build/onboarding-final-20261025-3'
gate.FILES = ['web/help/guide.html', 'web/help/guide.js', 'web/help/guide.css',
    'web/user_guide.js', 'web/user_guide.css', 'web/app.js', 'web/index.html',
    'web/source_scope.js', 'web/library.js', 'web/mobile/sw.js', 'desktop/main.js',
    'package.json', 'package-lock.json']
gate.TESTS = ['user_guide', 'source_scope', 'teaching_review', 'message_focus',
    'message_history_pages', 'library_followup_focus', 'library_models', 'library_foreground',
    'review_versions', 'profile_recency', 'codex_rate_error', 'mobile_access', 'bundle_cuda',
    'desktop_lifecycle', 'update_backup']

if __name__ == '__main__':
    gate.main()
