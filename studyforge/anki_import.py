"""Read Anki package compression and media-map fields without running templates."""
import io
import json

MAX_ENTRY_BYTES = 100 * 1024 * 1024


def decompress(data):
    try:
        import zstandard
    except ImportError as exc:
        raise ValueError('此卡组使用新版 Anki 压缩格式，需安装 zstandard 依赖；也可从 Anki 兼容导出后导入') from exc
    try:
        with zstandard.ZstdDecompressor(max_window_size=max(1024, MAX_ENTRY_BYTES // 1024)).stream_reader(io.BytesIO(data)) as reader:
            decoded = reader.read(MAX_ENTRY_BYTES + 1)
    except zstandard.ZstdError as exc:
        raise ValueError('Anki 压缩内容无法解析或超过解压限制，原卡组已保留') from exc
    if len(decoded) > MAX_ENTRY_BYTES: raise ValueError('Anki 解压内容超过 100 MB，已停止解析')
    return decoded


def _fields(data):
    """Minimal protobuf wire reader, accepting unknown scalar fields."""
    offset = 0

    def varint():
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data): raise ValueError('Anki 媒体索引截断')
            byte = data[offset]
            offset += 1
            value |= (byte & 127) << shift
            if not byte & 128: return value
        raise ValueError('Anki 媒体索引整数无效')

    while offset < len(data):
        tag = varint()
        field, wire = tag >> 3, tag & 7
        if not field: raise ValueError('Anki 媒体索引字段无效')
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            length = varint() if wire == 2 else (8 if wire == 1 else 4)
            if offset + length > len(data): raise ValueError('Anki 媒体索引长度无效')
            value = data[offset:offset + length]
            offset += length
        else: raise ValueError('Anki 媒体索引编码不受支持')
        yield field, wire, value


def media_map(data, modern=False):
    if not modern:
        value = json.loads(data.decode('utf-8-sig'))
        if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
            raise ValueError('Anki 媒体索引无效')
        return value
    # Package schema: repeated entry=1; name=1; optional legacy index=255.
    result = {}
    for field, wire, value in _fields(decompress(data)):
        if field != 1 or wire != 2: continue
        number, name = len(result), None
        for key, kind, part in _fields(value):
            if key == 1 and kind == 2: name = part.decode('utf-8')
            elif key == 255 and kind == 0: number = part
        if name is None: raise ValueError('Anki 媒体索引缺少文件名')
        result[str(number)] = name
    return result
