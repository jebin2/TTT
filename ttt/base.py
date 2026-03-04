import os
import json
import gc
from . import common

from dotenv import load_dotenv
if os.path.exists(".env"):
    print("Loaded .env")
    load_dotenv()


class BaseTTT:
    """Base class for text-to-text implementations."""

    def __init__(self, type):
        self.device = common.get_device()
        if self.device == "cuda":
            os.environ["TORCH_USE_CUDA_DSA"] = "1"
            os.environ["CUDA_LAUNCH_BLOCKING"] = "1"
        os.environ["HF_HUB_TIMEOUT"] = "120"
        self.type = type
        self.temp_dir = "./temp_dir"
        self.output_json_file = f"{self.temp_dir}/output_generation.json"
        self.model = None
        self.tokenizer = None

    def reset(self):
        if self.device == "cuda":
            common.clear_gpu_cache()
        os.makedirs(self.temp_dir, exist_ok=True)

    def save_result(self, result):
        """Save generation result to JSON file."""
        with open(self.output_json_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=4, ensure_ascii=False)
        print(f"Result saved to {self.output_json_file}")
        return True

    def generate(self, args, progress_callback=None):
        """Main generation method.

        Args:
            args: dict with keys: 'text', 'system_prompt' (optional),
                  'max_new_tokens' (optional), 'temperature' (optional),
                  'top_p' (optional)
            progress_callback: callable(percent: int, text: str) for progress updates

        Returns:
            dict with generation results, or False on failure
        """
        self.reset()

        input_text = args.get('text') or args.get('input', '')
        if not input_text or not input_text.strip():
            raise ValueError("No input text provided")

        system_prompt = args.get('system_prompt') or "You are a helpful assistant. Always respond in English."

        result = self.generate_text(
            input_text=input_text.strip(),
            system_prompt=system_prompt,
            max_new_tokens=int(args.get('max_new_tokens', os.environ.get('MAX_NEW_TOKENS', 2048))),
            temperature=float(args.get('temperature', 0.7)),
            top_p=float(args.get('top_p', 0.9)),
            progress_callback=progress_callback,
        )

        if not result:
            print("Error: No output generated")
            return False

        self.save_result(result)
        return result

    def generate_text(self, input_text, system_prompt, max_new_tokens=2048,
                      temperature=0.7, top_p=0.9, progress_callback=None):
        """Run inference — implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement generate_text()")

    def cleanup(self):
        """Release model resources."""
        for attr in ('model', 'tokenizer'):
            obj = getattr(self, attr, None)
            if obj is not None:
                print(f"Cleaning up {attr}...")
                try:
                    delattr(self, attr)
                    setattr(self, attr, None)
                    gc.collect()
                    common.clear_gpu_cache()
                    print(f"{attr} memory cleaned.")
                except Exception as e:
                    print(f"Error during {attr} cleanup: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def __del__(self):
        self.cleanup()
