"""Local Apple Silicon ASR fallback; no account, remote upload or API key.

Run with: uv run --with mlx-whisper==0.4.3 python scripts/local_transcribe.py ...
The model must already exist locally. Samples are explicitly labelled and may
not be presented as complete transcripts.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--language', default='zh')
    parser.add_argument('--sample', action='store_true')
    parser.add_argument('--initial-prompt', default='', help='发布者提供的人名和术语，不得填入猜测的发言')
    args = parser.parse_args()
    if not args.audio.is_file() or not args.model.is_dir():
        parser.error('音频和模型必须为已有本地文件/目录')
    if args.output.exists():
        parser.error('输出已存在，请指定新路径，避免覆盖已有转录')
    import mlx_whisper
    result = mlx_whisper.transcribe(str(args.audio), path_or_hf_repo=str(args.model),
                                   language=args.language, word_timestamps=True, verbose=False,
                                   initial_prompt=args.initial_prompt or None,
                                   condition_on_previous_text=False)
    if not result.get('text', '').strip():
        raise ValueError('转写返回空文本')
    with args.audio.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    payload = {'provider': 'local-mlx-whisper', 'model': args.model.name,
               'input_sha256': digest,
               'initial_prompt': args.initial_prompt,
               'scope': 'sample' if args.sample else 'provided_audio_only',
               'source_completeness_verified': False,
               'text': result['text'], 'segments': result.get('segments', []),
               'language': result.get('language', args.language)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps({'output': str(args.output), 'scope': payload['scope'],
                      'characters': len(result['text']), 'segments': len(payload['segments'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
