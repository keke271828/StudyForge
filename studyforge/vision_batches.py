"""Small multi-image requests with independently attributable observations.

The original OCR stays in the source. A batch adds corrections and visual
evidence, rather than another transcript or a lesson for every video frame.
"""
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import io
from pathlib import Path

POLICY_VERSION = 2
BATCH_SIZE = 4
VISION_RULES = (
    '你是视觉资料记录员，不是讲解作者。逐张查看原图，仅记录原 OCR 的实质校正、'
    '遗漏的重要文字或代码，以及 OCR 无法表达的公式、图形关系、坐标轴、图表、板书布局和实际预览结果。'
    '原 OCR 另行完整保留：已识别正确的普通文字、重复标题与相同板书不要再抄一遍，不写知识讲解、总结或教程。'
    '不能为追求简短而遗漏新增公式及其条件、数据和关键符号；只需要多少信息就写多少。'
    '没有补充或校正时，简洁说明本图核对范围和“未发现需补记的实质内容”。'
    '忽略地址栏、书签、标签、分享按钮等与课程无关的界面，除非它们是教学对象。'
    '空白预览就记录空白；单帧可能是中间步骤，不据此判断整段课程的结论。'
    '无法辨认处明确说明，不能用 OCR、相邻画面或常识填补看不清的本图内容。'
    '同批图片只是传输合并，每条记录只能引用对应图片；不串图，不跨图补全公式或把推断当视觉事实。'
)


def image_content(path: Path) -> dict:
    from PIL import Image
    with Image.open(path) as original:
        # RGB input can be resized in place: converting RGB to RGB creates a
        # second full-resolution allocation without changing a single pixel.
        image = original if original.mode == 'RGB' else original.convert('RGB')
        image.thumbnail((1280, 1280))
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=82)
    return {'type': 'image_url', 'image_url': {
        'url': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')}}


def image_messages(frames: list[dict], *, structured: bool) -> list[dict]:
    content = []
    for frame in frames:
        content.append({'type': 'text', 'text':
            f"图片ID：{frame['id']}；位置：{frame['locator']}\n"
            f"OCR 参考（不是视觉证据）：\n{frame.get('ocr', '')[:4000]}"})
        content.append(image_content(Path(frame['path'])))
    schema = ('只返回一个 JSON 对象：{"frames":[{"id":"图片ID","observation":"本图的独立核对记录"}]}。'
              '每个输入ID恰好出现一次；observation为非空字符串，不加Markdown围栏。'
              if structured else '只返回本图的核对记录。')
    return [{'role': 'system', 'content': VISION_RULES + schema}, {'role': 'user', 'content': content}]


async def prepare_image_messages(frames, *, structured, runtime=None):
    """Encoding must not block the service event loop or decode in many workers."""
    from .scheduling import run_local
    return await run_local('image_prepare', image_messages, frames, structured=structured,
                           runtime=runtime, label='准备视觉资料（保留原尺寸策略与质量）')


class DeferredImageBody(dict):
    """Queue only paths/OCR, not decoded pixels or base64 request bodies.

    Native transports resolve this inside their existing model lease. A new
    attempt rebuilds the body; no payload is cached on this descriptor. The
    fixed objective request has no agent tools, approvals or shared dialogue.
    """
    def __init__(self, options, frames, *, structured, runtime):
        super().__init__(options)
        self.frames = [dict(id=frame['id'], path=Path(frame['path']),
                            locator=frame['locator'], ocr=frame.get('ocr', '')) for frame in frames]
        self.structured, self.runtime = structured, runtime

    async def resolve(self):
        body = dict(self)
        body['messages'] = await prepare_image_messages(self.frames, structured=self.structured,
                                                        runtime=self.runtime)
        return body


async def image_request_body(client, frames, *, structured):
    from .ai import DeepSeekClient
    from .provider_clients import ServiceClient, GeminiClient
    options = {'model': client.vision_model, 'stream': False, 'messages': []}
    if structured:
        options['response_format'] = {'type': 'json_object'}
    options = client.prepare_body(options)
    # Unknown adapters/subclasses may expect an ordinary fully formed dict.
    # Only reviewed API transports guarantee admission before materialization.
    if type(client) in (DeepSeekClient, ServiceClient, GeminiClient):
        return DeferredImageBody(options, frames, structured=structured, runtime=client.agent_runtime)
    options['messages'] = await prepare_image_messages(frames, structured=structured,
                                                      runtime=client.agent_runtime)
    return client.prepare_body(options)


async def resolve_request_body(body):
    return await body.resolve() if isinstance(body, DeferredImageBody) else body


@asynccontextmanager
async def admitted_request_body(body, provider, runtime=None):
    """Reserve the model before encoding, with a safe pause before sending.

    No nested model acquisition. If paused during native preparation, discard
    that payload, release the model and resume from paths. The existing local
    encoder keeps its own lease until its actual thread finishes on cancel.
    """
    from .scheduling import current_step, model_slot
    step = current_step.get() if isinstance(body, DeferredImageBody) else None
    if step and not step.owned():
        step = None
    waiting = step.waiting if step else False
    if step:
        step.native_image_sent = False
    try:
        while True:
            async with model_slot(provider, runtime):
                prepared = await resolve_request_body(body)
                try:
                    if not (step and step.control.pause_requested):
                        if step:
                            step.native_image_sent = True
                        yield prepared
                        return
                finally:
                    prepared = None
                # Preparing pixels is a finished local step, but a model
                # request has not been sent. Do not occupy its slot on pause.
                step.started = False
                step.set_waiting(True)
            await step.control.checkpoint()
            step.set_waiting(waiting)
    finally:
        if step:
            del step.native_image_sent
            if not step.started:
                step.set_waiting(waiting)


def observations(value: dict, expected: list[str]) -> dict[str, str]:
    """Missing frames can be retried alone; ambiguous IDs cannot be published."""
    if not isinstance(value, dict) or not isinstance(value.get('frames'), list):
        raise ValueError('多图核对没有返回逐图记录')
    result = {}
    seen = set()
    for frame in value['frames']:
        if not isinstance(frame, dict): raise ValueError('图像记录格式无效')
        identifier, text = frame.get('id'), frame.get('observation')
        if not isinstance(identifier, str) or identifier not in expected or identifier in seen:
            raise ValueError('多图核对包含未知或重复图片ID')
        seen.add(identifier)
        if not isinstance(text, str) or not text.strip(): continue
        result[identifier] = text.strip()
    return result
