# CLI reference

Run the bundled script from the skill directory or by absolute path. A dry run does not call the API and does not require the OpenAI package.

```text
python scripts/text_to_speech.py list-voices
python scripts/text_to_speech.py speak --input "Welcome to the demo." --dry-run
python scripts/text_to_speech.py speak --input-file narration.txt --voice cedar --out output/speech/demo.mp3
python scripts/text_to_speech.py speak-batch --input tmp/speech/jobs.jsonl --out-dir output/speech --rpm 30
```

Live calls require `OPENAI_API_KEY`, the `openai` Python package, network access, and an output path. Use `--force` only when the user authorizes replacing an existing file. Batch JSONL accepts one object per line with `input` plus optional `model`, `voice`, `response_format`/`format`, `speed`, `instructions`, and `out` fields. Blank lines and `#` comments are ignored.
