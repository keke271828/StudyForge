from __future__ import annotations

import ipaddress
import socket
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .config import temp_dir
from .media import download_public_video
from .parsers import PARSERS
from .video_links import canonical_video_url, embedded_video_url

MAX_URL_BYTES = 200 * 1024 * 1024
MIME_EXTENSIONS = {
    "text/html": ".html", "text/plain": ".txt", "text/markdown": ".md",
    "application/pdf": ".pdf", "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/mp4": ".m4a",
    "video/mp4": ".mp4", "video/webm": ".webm",
}


class BrowserImportRequired(ValueError):
    pass


@contextmanager
def public_response(client, url):
    """Explain transport failures without confusing them with scope errors."""
    try:
        with client.stream('GET', url) as response:
            yield response
    except httpx.RequestError as exc:
        host = urlparse(url).hostname or '该网站'
        if isinstance(exc, httpx.TimeoutException):
            reason = f'连接 {host} 超时，尚未读取到完整内容'
        elif any(word in str(exc).lower() for word in ('ssl', 'tls', 'certificate')):
            reason = f'{host} 的 HTTPS 加密连接失败，可能与网络代理或证书有关'
        else:
            reason = f'无法连接 {host}，请检查网络、代理或网站访问限制'
        raise BrowserImportRequired(reason + '。可以在桌面使用“浏览器导入”读取，或检查网络后点击“重试网址”。') from exc


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("请输入公开的 HTTP/HTTPS 网址")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("不能导入本机或内网网址")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("不能导入本机或内网网址")
    except ValueError as exc:
        if "不能导入" in str(exc):
            raise
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"网址域名解析失败：{host}") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("网址解析到了本机或内网地址")
    return url


def download_public_resource(url: str, stem: str, *, cookies: list[dict] | None = None,
                             video_url: str | None = None, on_progress=None, allow_video: bool = True) -> Path:
    validate_public_url(url)
    def video(target: str) -> Path:
        if not allow_video: raise PermissionError('“是否允许 AI 读取网页视频”未勾选')
        validate_public_url(target)
        try:
            return download_public_video(target, referer=url, cookies=cookies, on_progress=on_progress)
        except (RuntimeError, OSError) as exc:
            raise BrowserImportRequired('视频读取未完成，请用“浏览器导入”，确认视频能够播放后点击“导入视频内容”。'
                                        '不会改用评论、简介或推荐内容生成讲解。若仍无法读取，可上传本地视频。') from exc
    if video_url:
        return video(canonical_video_url(video_url) or video_url)
    with httpx.Client(timeout=30, follow_redirects=False,
                      headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36',
                               'Accept': 'text/html,application/xhtml+xml,application/pdf,*/*;q=0.8',
                               'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.6'}) as client:
        current = url
        for _ in range(6):
            validate_public_url(current)
            detected = canonical_video_url(current)
            # Resolve b23.tv through checked redirects before invoking yt-dlp.
            if detected and (urlparse(current).hostname or '').lower() != 'b23.tv':
                return video(detected)
            with public_response(client, current) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("网址跳转缺少目标地址")
                    current = urljoin(current, location)
                    continue
                if response.status_code in (401, 403, 429):
                    raise BrowserImportRequired('网站拒绝后台读取，可能需要登录或验证。请使用“浏览器导入”，打开文章后点击“导入当前页面”；也可保存为 PDF/HTML 后导入')
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ValueError(f'网站返回 HTTP {response.status_code}，暂时无法读取；请在浏览器确认网址是否可访问') from exc
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                suffix = MIME_EXTENSIONS.get(mime, "")
                if suffix not in PARSERS:
                    suffix = Path(urlparse(current).path).suffix.lower()
                if suffix not in PARSERS:
                    raise ValueError(f"网址内容格式暂不支持：{mime or '未知格式'}；请下载后作为本地文件导入")
                if not allow_video and (mime.startswith('video/') or suffix in ('.mp4', '.webm', '.mov', '.mkv', '.avi')):
                    raise PermissionError('“是否允许 AI 读取网页视频”未勾选')
                target = temp_dir() / f"url-{stem}{suffix}"
                size = 0
                try:
                    with target.open("wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_URL_BYTES:
                                raise ValueError("网址文件超过 200 MB，请先下载后从本地导入")
                            output.write(chunk)
                    if size == 0:
                        raise ValueError("网址没有返回可解析的内容")
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                if suffix in ('.html', '.htm'):
                    from .parsers import decode_text
                    present, embedded = embedded_video_url(decode_text(target.read_bytes())[0], current)
                    if present:
                        target.unlink(missing_ok=True)
                        if embedded:
                            return video(embedded)
                        raise BrowserImportRequired('页面含动态视频，后台未取得视频地址。请使用“浏览器导入”，'
                                                    '播放视频后点击“导入视频内容”；不会读取页面的无关文字')
                return target
    raise ValueError("网址跳转次数过多")
