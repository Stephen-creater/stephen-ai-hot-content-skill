"""把播客音频转成逐字稿，全程在本机跑。

播客源之前整类空转：小宇宙网页只有节目介绍，BestBlogs 只覆盖约三十档节目，
其余节目没有逐字稿就永远进不了候选。本机有 whisper.cpp 和 ffmpeg，转写约 27 倍速，
154 分钟的节目六分钟左右能转完，够用。

    .venv/bin/python3 scripts/transcribe_audio.py <音频或节目链接> --title "<节目标题>"

模型默认在 ~/.cache/whisper-cpp/ggml-large-v3-turbo.bin，用 --model 换别的。
转写是机器稿：专名会错、没有说话人，交付前必须校对，不能直接当成品。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = ROOT / ".local" / "transcripts"
DEFAULT_MODEL = Path.home() / ".cache" / "whisper-cpp" / "ggml-large-v3-turbo.bin"
# 没有提示词时 whisper 的中文输出不带标点，整段读不下去。
PUNCTUATION_PROMPT = "以下是一段普通话播客对话，请按正常中文书写习惯加上标点符号。"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def download(url: str, target: Path) -> Path:
    with requests.get(url, headers=HEADERS, stream=True, timeout=120) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(1 << 20):
                handle.write(chunk)
    return target


def to_wav(source: Path, target: Path, max_minutes: int = 0) -> Path:
    command = ["ffmpeg", "-v", "error", "-i", str(source)]
    if max_minutes:
        command += ["-t", str(max_minutes * 60)]
    command += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target), "-y"]
    subprocess.run(command, check=True, capture_output=True, timeout=1800)
    return target


def run_whisper(wav: Path, model: Path, language: str = "zh") -> str:
    stem = wav.with_suffix("")
    subprocess.run(
        ["whisper-cli", "-m", str(model), "-l", language, "-nt", "-np", "--prompt", PUNCTUATION_PROMPT,
         "-otxt", "-of", str(stem), str(wav)],
        check=True, capture_output=True, text=True, timeout=7200,
    )
    text = stem.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def transcribe(url: str, model: Path = DEFAULT_MODEL, language: str = "zh", max_minutes: int = 0) -> str:
    if not shutil.which("whisper-cli"):
        raise RuntimeError("未找到 whisper-cli（brew install whisper-cpp）")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("未找到 ffmpeg")
    if not model.is_file():
        raise RuntimeError(f"缺少模型 {model}；从 huggingface.co/ggerganov/whisper.cpp 下载 ggml-large-v3-turbo.bin")
    with tempfile.TemporaryDirectory(prefix="stephen-asr-") as raw:
        directory = Path(raw)
        audio = download(url, directory / "audio.bin")
        wav = to_wav(audio, directory / "audio.wav", max_minutes)
        return run_whisper(wav, model, language)


def save(text: str, title: str, directory: Path = TRANSCRIPTS) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|\n]', "_", title)[:80] or "transcript"
    path = directory / f"{name}.md"
    path.write_text(f"# {title}（本机机器转写，未校对）\n\n{text}\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="音频直链；节目页链接请先取出音频地址")
    parser.add_argument("--title", default="播客转写")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--max-minutes", type=int, default=0, help="只转前 N 分钟，0 表示整期")
    args = parser.parse_args()
    try:
        text = transcribe(args.url, args.model, args.language, args.max_minutes)
    except Exception as exc:
        raise SystemExit(f"转写失败：{exc}")
    path = save(text, args.title)
    print(f"{len(text)} 字 → {path}")
    print("机器稿：专名可能错、没有说话人，交付前必须校对。")


if __name__ == "__main__":
    main()
