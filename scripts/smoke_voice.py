"""Run a local Chinese speech sample through the real transcription pipeline."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pyttsx3

from studyforge.media import transcribe


def main() -> None:
    with TemporaryDirectory() as folder:
        sample = Path(folder) / "chinese-voice.wav"
        engine = pyttsx3.init()
        voice = next((voice for voice in engine.getProperty("voices")
                      if "zh" in str(voice.languages).lower()), None)
        if not voice:
            raise RuntimeError("本机没有中文语音合成声线，无法生成测试音频")
        engine.setProperty("voice", voice.id)
        engine.setProperty("rate", 145)
        engine.save_to_file("牛顿第二定律，力等于质量乘以加速度。", str(sample))
        engine.runAndWait()
        engine.stop()
        if not sample.exists() or sample.stat().st_size < 1000:
            raise RuntimeError("语音合成未生成有效样本")
        result = transcribe(sample, "zh")
        text = " ".join(segment["text"] for segment in result)
        print(text)
        if not text.strip():
            raise RuntimeError("语音识别没有输出文字")


if __name__ == "__main__":
    main()
