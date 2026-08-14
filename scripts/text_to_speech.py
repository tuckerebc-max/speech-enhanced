#!/usr/bin/env python3
"""Generate single or batch speech audio with the OpenAI Audio API."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

DEFAULT_MODEL = "gpt-4o-mini-tts-2025-12-15"
DEFAULT_VOICE = "cedar"
DEFAULT_FORMAT = "mp3"
MAX_INPUT_CHARS = 4096
MAX_RPM = 50
VOICES = {"alloy", "ash", "ballad", "cedar", "coral", "echo", "fable", "marin", "nova", "onyx", "sage", "shimmer", "verse"}
FORMATS = {"mp3", "opus", "aac", "flac", "wav", "pcm"}


def die(message: str) -> None:
    raise SystemExit(f"Error: {message}")


def read_value(value: str | None, file_path: str | None, label: str) -> str:
    if value and file_path:
        die(f"Use --{label} or --{label}-file, not both.")
    if file_path:
        path = Path(file_path)
        if not path.is_file():
            die(f"{label} file not found: {path}")
        return path.read_text(encoding="utf-8").strip()
    if value is not None:
        return value.strip()
    die(f"Missing {label} input.")


def validate_text(text: str) -> None:
    if not text:
        die("Input text is empty.")
    if len(text) > MAX_INPUT_CHARS:
        die(f"Input text exceeds {MAX_INPUT_CHARS} characters; split it at a sentence boundary.")


def voice(value: str | None) -> str:
    result = (value or DEFAULT_VOICE).strip().lower()
    if result not in VOICES:
        die(f"voice must be one of: {', '.join(sorted(VOICES))}")
    return result


def response_format(value: str | None) -> str:
    result = (value or DEFAULT_FORMAT).strip().lower()
    if result not in FORMATS:
        die(f"response-format must be one of: {', '.join(sorted(FORMATS))}")
    return result


def speed(value: float | None) -> float | None:
    if value is None:
        return None
    if not 0.25 <= value <= 4.0:
        die("speed must be between 0.25 and 4.0")
    return value


def output_path(value: str | None, fmt: str) -> Path:
    path = Path(value or f"speech.{fmt}")
    if path.exists() and path.is_dir():
        return path / f"speech.{fmt}"
    if path.suffix == "":
        return path.with_suffix(f".{fmt}")
    return path


def load_client() -> Any:
    if not os.getenv("OPENAI_API_KEY"):
        die("OPENAI_API_KEY is not set. Set it locally before a live call; do not paste it into chat.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        die("The openai package is missing. Install it with `uv pip install openai`.")
        raise exc
    return OpenAI()


def effective_instructions(model: str, instructions: str | None) -> str | None:
    if instructions and model in {"tts-1", "tts-1-hd"}:
        print("Warning: instructions are unsupported for this model and will be ignored.", file=sys.stderr)
        return None
    return instructions or None


def payload_for(text: str, args: argparse.Namespace, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    model = str(overrides.get("model", args.model)).strip()
    fmt = response_format(overrides.get("response_format", overrides.get("format", args.response_format)))
    result: dict[str, Any] = {"model": model, "voice": voice(overrides.get("voice", args.voice)), "input": text, "response_format": fmt}
    rate = overrides.get("speed", args.speed)
    if speed(rate) is not None:
        result["speed"] = speed(rate)
    instruction = effective_instructions(model, overrides.get("instructions", args.instructions))
    if instruction:
        result["instructions"] = instruction
    return result


def write_audio(client: Any, payload: dict[str, Any], path: Path, force: bool, attempts: int = 3) -> None:
    if path.exists() and not force:
        die(f"Output already exists: {path} (use --force only when overwrite is authorized)")
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, attempts + 1):
        try:
            with client.audio.speech.with_streaming_response.create(**payload) as response:
                response.stream_to_file(path)
            print(f"Wrote {path}")
            return
        except Exception as exc:  # SDK exception classes vary by version.
            transient = any(word in str(exc).lower() for word in ("timeout", "429", "rate limit", "tempor"))
            if attempt == attempts or not transient:
                raise
            delay = min(30.0, 2.0 ** attempt)
            print(f"Transient error; retrying in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)


def dry_run(payload: dict[str, Any], path: Path) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Would write {path}")


def run_single(args: argparse.Namespace) -> int:
    text = read_value(args.input, args.input_file, "input")
    validate_text(text)
    args.instructions = read_value(args.instructions, args.instructions_file, "instructions") if (args.instructions or args.instructions_file) else None
    path = output_path(args.out, response_format(args.response_format))
    payload = payload_for(text, args)
    if args.dry_run:
        dry_run(payload, path)
        return 0
    write_audio(load_client(), payload, path, args.force, args.attempts)
    return 0


def read_jobs(path: str) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        die(f"Batch input not found: {source}")
    jobs: list[dict[str, Any]] = []
    for line_number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            try:
                job = json.loads(line)
            except json.JSONDecodeError as exc:
                die(f"Invalid JSON on line {line_number}: {exc}")
            if not isinstance(job, dict):
                die(f"Batch line {line_number} must contain a JSON object.")
        else:
            job = {"input": line}
        jobs.append(job)
    if not jobs:
        die("Batch input contains no jobs.")
    return jobs


def job_text(job: dict[str, Any]) -> str:
    for key in ("input", "text", "prompt"):
        if str(job.get(key, "")).strip():
            return str(job[key]).strip()
    die("Each batch job needs an input field.")
    return ""


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:60] or "job"


def run_batch(args: argparse.Namespace) -> int:
    jobs = read_jobs(args.input)
    if args.rpm <= 0 or args.rpm > MAX_RPM:
        die(f"rpm must be between 1 and {MAX_RPM}")
    args.instructions = read_value(args.instructions, args.instructions_file, "instructions") if (args.instructions or args.instructions_file) else None
    client = None if args.dry_run else load_client()
    last_time: float | None = None
    for index, job in enumerate(jobs, start=1):
        text = job_text(job)
        validate_text(text)
        payload = payload_for(text, args, job)
        requested = job.get("out")
        path = output_path(str(requested), payload["response_format"]) if requested else Path(args.out_dir) / f"{index:03d}-{slug(text[:80])}.{payload['response_format']}"
        if requested and not path.is_absolute():
            path = Path(args.out_dir) / path
        if args.dry_run:
            dry_run(payload, path)
            continue
        now = time.monotonic()
        if last_time is not None:
            time.sleep(max(0.0, 60.0 / args.rpm - (now - last_time)))
        last_time = time.monotonic()
        write_audio(client, payload, path, args.force, args.attempts)
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--response-format", default=DEFAULT_FORMAT)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--instructions")
    parser.add_argument("--instructions-file")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate speech with the OpenAI Audio API.")
    sub = parser.add_subparsers(dest="command", required=True)
    voices = sub.add_parser("list-voices")
    voices.set_defaults(func=lambda _args: print("\n".join(sorted(VOICES))) or 0)
    single = sub.add_parser("speak")
    single.add_argument("--input")
    single.add_argument("--input-file")
    single.add_argument("--out")
    add_common(single)
    single.set_defaults(func=run_single)
    batch = sub.add_parser("speak-batch")
    batch.add_argument("--input", required=True)
    batch.add_argument("--out-dir", default="output/speech")
    batch.add_argument("--rpm", type=int, default=50)
    add_common(batch)
    batch.set_defaults(func=run_batch)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
