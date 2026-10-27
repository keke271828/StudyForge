"""Identify the main video without treating surrounding page text as material."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urljoin, urlparse

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m3u8', '.mpd', '.flv'}


def canonical_video_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('http', 'https'):
        return None
    query = parse_qs(parsed.query)
    if host == 'b23.tv':
        return url
    if host == 'bilibili.com' or host.endswith('.bilibili.com'):
        match = re.search(r'/video/((?:BV|av)[A-Za-z0-9]+)', parsed.path, re.I)
        video_id = match[1] if match else query.get('bvid', [''])[0]
        if not video_id and host == 'player.bilibili.com':
            aid = query.get('aid', [''])[0]
            video_id = 'av' + aid if aid.isdigit() else ''
        if re.fullmatch(r'(?:BV[A-Za-z0-9]+|av\d+)', video_id, re.I):
            page = query.get('p', query.get('page', ['1']))[0]
            page = page if page.isdigit() and int(page) > 0 else '1'
            return f'https://www.bilibili.com/video/{video_id}?p={page}'
        return None  # Bilibili articles and user pages are not videos.
    if host == 'youtu.be' and parsed.path.strip('/'):
        return url
    if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'www.youtube-nocookie.com'):
        match = re.match(r'/(?:embed|shorts|live)/([\w-]+)', parsed.path)
        video_id = match[1] if match else query.get('v', [''])[0]
        if video_id:
            return 'https://www.youtube.com/watch?v=' + video_id
    if host in ('vimeo.com', 'www.vimeo.com', 'player.vimeo.com') and re.search(r'/\d+(?:/|$)', parsed.path):
        return url
    if any(parsed.path.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
        return url
    return None


def embedded_video_url(markup: str, page_url: str) -> tuple[bool, str | None]:
    """Return (video present, usable URL). Never extract comments or page prose."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(markup, 'html.parser')
    for node in soup.select('nav, aside, footer, .ad, .advertisement, [data-ad], .recommend, .comments, #comments'):
        node.decompose()
    root = soup.select_one('main, article') or soup
    present = False
    for video in root.find_all('video'):
        present = True
        candidates = [video.get('src', ''), *[s.get('src', '') for s in video.find_all('source')]]
        for candidate in candidates:
            target = urljoin(page_url, candidate)
            if candidate and urlparse(target).scheme in ('http', 'https'):
                return True, canonical_video_url(target) or target
    for frame in root.find_all('iframe', src=True):
        target = canonical_video_url(urljoin(page_url, frame['src']))
        if target:
            return True, target
    for node in soup.select('meta[property="og:video"], meta[property="og:video:url"], meta[property="og:video:secure_url"]'):
        candidate = node.get('content', '')
        target = urljoin(page_url, candidate)
        if candidate and urlparse(target).scheme in ('http', 'https'):
            return True, canonical_video_url(target) or target
    def videos(value):
        if isinstance(value, list):
            for item in value:
                yield from videos(item)
        elif isinstance(value, dict):
            kinds = value.get('@type', [])
            if 'VideoObject' in (kinds if isinstance(kinds, list) else [kinds]):
                yield value
            yield from videos(value.get('@graph', []))
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for video in videos(data):
            present = True
            for key in ('contentUrl', 'embedUrl'):
                candidate = video.get(key)
                if isinstance(candidate, str) and urlparse(urljoin(page_url, candidate)).scheme in ('http', 'https'):
                    target = urljoin(page_url, candidate)
                    return True, canonical_video_url(target) or target
    return present, None
