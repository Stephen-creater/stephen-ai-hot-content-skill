"""Use a reading copy only for punctuation; preserve publisher caption wording."""
from __future__ import annotations

import argparse
import difflib
import re
from pathlib import Path


def caption_text(vtt: str) -> str:
    lines = []
    previous = ""
    raw_lines = vtt.splitlines()
    for index, line in enumerate(raw_lines):
        line = re.sub(r"<[^>]+>", "", line).strip()
        cue_number = line.isdigit() and index + 1 < len(raw_lines) and "-->" in raw_lines[index + 1]
        if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or cue_number:
            continue
        if line != previous:
            lines.append(line)
        previous = line
    return " ".join(lines)


def restore_readability(vtt: str, reading_copy: str) -> str:
    source = caption_text(vtt)
    # Matching ignores punctuation, but the output always takes words from source.
    positions = [i for i, c in enumerate(source) if c.isalnum()]
    original = "".join(source[i] for i in positions)
    reference_positions = [i for i, c in enumerate(reading_copy) if c.isalnum()]
    reference = "".join(reading_copy[i] for i in reference_positions)
    source_for_reference = {}
    matcher = difflib.SequenceMatcher(None, reference, original, autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        if size >= 5:
            source_for_reference.update((a + n, b + n) for n in range(size))
    insertions = {}
    for n in range(len(reference_positions) - 1):
        left, right = source_for_reference.get(n), source_for_reference.get(n + 1)
        if left is None or right != left + 1:
            continue
        gap = reading_copy[reference_positions[n] + 1:reference_positions[n + 1]]
        punctuation = "".join(c for c in gap if c in "，。？！；：、")
        newline = "\n\n" if "\n\n" in gap else ""
        source_gap = source[positions[left] + 1:positions[right]]
        insertion_position = positions[left] + 1
        while insertion_position < positions[right] and source[insertion_position] in "》〉”’）)]}":
            insertion_position += 1
        if punctuation and not any(c in source_gap for c in "，。？！；：、,.?!;:"):
            insertions[insertion_position] = punctuation[:1] + newline
        elif newline:
            insertions[insertion_position] = newline
    result = "".join(insertions.get(i, "") + c for i, c in enumerate(source))
    result = re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", "", result)
    result = re.sub(r" *\n\n *", "\n\n", result).strip()
    result = re.sub(r"(?<=[，。？！；：、]) +", "", result)
    paragraphs = []
    for paragraph in result.split("\n\n"):
        while len(paragraph) > 600:
            candidates = [paragraph.rfind(mark, 150, 500) for mark in "。？！；"]
            boundary = max(candidates)
            if boundary < 0:
                boundary = max(paragraph.rfind("，", 150, 500), paragraph.rfind(" ", 150, 500))
            if boundary < 0:
                boundary = 499
                while boundary + 1 < len(paragraph) and paragraph[boundary].isascii() and paragraph[boundary].isalnum():
                    boundary += 1
            paragraphs.append(paragraph[:boundary + 1].strip())
            paragraph = paragraph[boundary + 1:].strip()
        if paragraph:
            paragraphs.append(paragraph)
    result = "\n\n".join(paragraphs)
    # Never publish an accidental lexical rewrite from a third-party reading copy.
    if "".join(c for c in result if c.isalnum()) != original:
        raise ValueError("Caption wording changed during formatting")
    return result + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captions", type=Path)
    parser.add_argument("reading_copy", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(restore_readability(args.captions.read_text(), args.reading_copy.read_text()), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
