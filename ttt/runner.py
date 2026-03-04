import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
import logging
logging.getLogger().setLevel(logging.ERROR)

import argparse
import json
import os
import sys

TTT_ENGINE = None


def _get_engine(model):
    global TTT_ENGINE
    if TTT_ENGINE is None:
        from .ollama_processor import OllamaTTTProcessor as TTTEngine
        TTT_ENGINE = TTTEngine(model_name=model)
    return TTT_ENGINE


def initiate(args, progress_callback=None):
    """Load engine (once) and run generation.

    Args:
        args: dict or argparse.Namespace with keys:
              'text'/'input', 'model', 'system_prompt' (opt),
              'max_new_tokens' (opt), 'temperature' (opt), 'top_p' (opt)
        progress_callback: callable(percent: int, text: str)

    Returns:
        dict result from generate(), or False on failure
    """
    if isinstance(args, dict):
        model = args.get('model', 'qwen3.5:4b')
    else:
        model = getattr(args, 'model', 'qwen3.5:4b') or 'qwen3.5:4b'

    if model == "qwen":
        model = "qwen3.5:4b"
            
    engine = _get_engine(model)
    return engine.generate(args if isinstance(args, dict) else vars(args),
                           progress_callback=progress_callback)


def server_mode(args):
    """Long-running server: read JSON prompts from stdin, write results to file.

    Input line format (JSON):
        {"text": "...", "system_prompt": "...", "model": "qwen"}

    Output lines:
        PROGRESS:<pct>:<text>
        SUCCESS or ERROR:<message>
    """
    # Pre-load the engine once
    _get_engine(args.model or 'qwen')

    print("SERVER_READY", flush=True)

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"ERROR:Invalid JSON: {e}", flush=True)
            continue

        def _cb(pct, msg):
            print(f"PROGRESS:{pct}:{msg}", flush=True)

        try:
            result = initiate(req, progress_callback=_cb)
            if result:
                print("SUCCESS", flush=True)
            else:
                print("ERROR:Generation returned empty result", flush=True)
        except Exception as e:
            print(f"ERROR:{e}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Text-to-Text processor using Qwen"
    )
    parser.add_argument(
        "--server-mode",
        action="store_true",
        help="Run in server mode (read JSON prompts from stdin, keep model loaded)"
    )
    parser.add_argument(
        "--input", "--text",
        dest="text",
        help="Input text / prompt"
    )
    parser.add_argument(
        "--model",
        default="qwen",
        help="Model name (default: qwen)"
    )
    parser.add_argument(
        "--system-prompt",
        dest="system_prompt",
        default="You are a helpful assistant.",
        help="System prompt"
    )
    parser.add_argument(
        "--max-new-tokens",
        dest="max_new_tokens",
        type=int,
        default=int(os.environ.get("MAX_NEW_TOKENS", 2048)),
        help="Maximum tokens to generate (default: 2048)"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Sampling temperature (default: 0.7)"
    )
    parser.add_argument(
        "--top-p",
        dest="top_p",
        type=float,
        default=0.9,
        help="Top-p sampling (default: 0.9)"
    )

    args = parser.parse_args()

    if args.server_mode:
        server_mode(args)
    else:
        if not args.text:
            print("Error: --input is required when not in server mode")
            return 1

        result = initiate(vars(args))
        if result:
            print(f"\n{'='*60}")
            print("OUTPUT:")
            print(result.get("text", ""))
            print(f"{'='*60}")
            return 0
        return 1


if __name__ == "__main__":
    sys.exit(main())
