from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / ".config" / "zhuque.json"
DEFAULT_CACHE_PATH = ROOT / ".local" / "zhuque_aigc_cache.json"


@dataclass(frozen=True)
class ZhuqueConfig:
    gateway: str
    api_key: str
    timeout_seconds: int = 60
    hard_reject_ai_ratio: float = 0.98
    downrank_ratio: float = 0.50
    downrank_points: float = 35.0
    max_cost_yuan_per_run: float = 5.0


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ZhuqueConfig | None:
    values: dict[str, Any] = {}
    if path.exists():
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("朱雀配置必须是 JSON 对象")
        values = parsed

    gateway = os.getenv("ZHUQUE_GATEWAY", "").strip() or str(values.get("gateway", "")).strip()
    api_key = os.getenv("ZHUQUE_API_KEY", "").strip() or str(values.get("api_key", "")).strip()
    if not gateway and not api_key:
        return None
    if not gateway or not api_key:
        raise ValueError("朱雀配置不完整：gateway 与 api_key 必须同时提供")
    gateway = gateway.rstrip("/")
    parsed_gateway = urlparse(gateway)
    if parsed_gateway.scheme != "https" or not parsed_gateway.netloc:
        raise ValueError("朱雀 gateway 必须是有效的 HTTPS 地址")

    return ZhuqueConfig(
        gateway=gateway,
        api_key=api_key,
        timeout_seconds=int(values.get("timeout_seconds", 60)),
        hard_reject_ai_ratio=float(values.get("hard_reject_ai_ratio", 0.98)),
        downrank_ratio=float(values.get("downrank_ratio", 0.50)),
        downrank_points=float(values.get("downrank_points", 35)),
        max_cost_yuan_per_run=float(values.get("max_cost_yuan_per_run", 5)),
    )


def estimate_text_cost_yuan(text: str) -> float:
    return round(max(1, math.ceil(len(text) / 1000)) * 40 * 0.001, 2)


def normalize_result(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "success":
        raise RuntimeError(f"朱雀检测失败: {payload.get('msg') or payload.get('message') or '未知错误'}")
    ratios = payload.get("labels_ratio")
    segments = payload.get("segment_labels")
    if not isinstance(ratios, dict) or not isinstance(segments, list):
        raise ValueError("朱雀返回缺少 labels_ratio 或 segment_labels")

    normalized_ratios = {
        "human": float(ratios.get("0", 0)),
        "ai": float(ratios.get("1", 0)),
        "suspected_ai": float(ratios.get("2", 0)),
    }
    if any(value < 0 or value > 1 for value in normalized_ratios.values()):
        raise ValueError("朱雀返回的内容占比不在 [0, 1] 范围内")

    normalized_segments = []
    for row in segments:
        if not isinstance(row, dict):
            continue
        label = int(row.get("label", -1))
        if label not in {0, 1, 2}:
            continue
        normalized_segments.append(
            {
                "text": str(row.get("text", "")),
                "label": label,
                "confidence": float(row.get("conf", 0)),
                "order": int(row.get("order", len(normalized_segments) + 1)),
                "position": row.get("position", []),
            }
        )

    return {
        "status": "success",
        "ratios": normalized_ratios,
        "ratio_confidence": float(payload.get("ratio_confidence", 0)),
        "softmax_confidence": float(payload.get("softmax_confidence", 0)),
        "segments": normalized_segments,
    }


class ZhuqueClient:
    def __init__(self, config: ZhuqueConfig, cache_path: Path = DEFAULT_CACHE_PATH) -> None:
        self.config = config
        self.cache_path = cache_path

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            parsed = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self, cache: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.cache_path)

    @staticmethod
    def content_digest(text: str) -> str:
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def has_cached_text(self, text: str) -> bool:
        return self.content_digest(text) in self._load_cache()

    def classify_text(self, text: str, use_cache: bool = True) -> dict[str, Any]:
        clean = text.strip()
        if not clean:
            raise ValueError("朱雀检测文本不能为空")
        digest = self.content_digest(clean)
        cache = self._load_cache() if use_cache else {}
        if digest in cache:
            return {**cache[digest], "cached": True}

        response = requests.post(
            f"{self.config.gateway}/v1/providers/zhuque-text/classify",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={"text": clean, "is_merge": False},
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        result = normalize_result(response.json())
        result["content_sha256"] = digest
        if use_cache:
            cache[digest] = result
            self._save_cache(cache)
        return {**result, "cached": False}


def apply_policy(item: dict[str, Any], detection: dict[str, Any], config: ZhuqueConfig) -> dict[str, Any]:
    ratios = detection["ratios"]
    ai_ratio = float(ratios["ai"])
    suspected_ratio = float(ratios["suspected_ai"])
    updated = {**item, "aigc_detection": detection}
    penalties = [part for part in str(updated.get("penalty", "")).split("；") if part]

    if ai_ratio >= config.hard_reject_ai_ratio:
        updated["recommended"] = False
        updated["score"] = round(float(updated.get("score", 0)) - 100, 1)
        penalties.append(f"朱雀判定 AI 内容占比 {ai_ratio:.0%}，达到硬淘汰线")
        updated["aigc_policy"] = "rejected"
    elif ai_ratio > config.downrank_ratio or suspected_ratio > config.downrank_ratio:
        updated["score"] = round(float(updated.get("score", 0)) - config.downrank_points, 1)
        dominant = "AI" if ai_ratio > config.downrank_ratio else "疑似 AI"
        ratio = ai_ratio if dominant == "AI" else suspected_ratio
        penalties.append(f"朱雀判定{dominant}内容占比 {ratio:.0%}，候选优先级降低")
        updated["aigc_policy"] = "downranked"
    else:
        updated["aigc_policy"] = "passed"

    updated["penalty"] = "；".join(penalties)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="检查或调用朱雀 AIGC 文本检测")
    parser.add_argument("action", choices=["status", "test"])
    parser.add_argument("--text", default="这是一次朱雀 AIGC 检测连接测试。")
    parser.add_argument("--file", type=Path, help="检测 UTF-8 文本文件；提供后优先于 --text")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()

    config = load_config(args.config)
    if not config:
        print("未配置：请设置 ZHUQUE_GATEWAY/ZHUQUE_API_KEY，或创建 .config/zhuque.json")
        raise SystemExit(2 if args.action == "test" else 0)
    print(f"已配置：{urlparse(config.gateway).netloc}（API Key 已隐藏）")
    if args.action == "test":
        text = args.file.read_text(encoding="utf-8") if args.file else args.text
        result = ZhuqueClient(config).classify_text(text, use_cache=False)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
