import os
import threading
from .base import BaseTTT


class QwenTTTProcessor(BaseTTT):
    """Text-to-text processor using Qwen/Qwen3.5-4B."""

    def __init__(self):
        super().__init__("qwen")
        self.model_name = "Qwen/Qwen3.5-4B"
        self._load_model()

    def _load_model(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print(f"Loading tokenizer: {self.model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            trust_remote_code=True
        )

        print(f"Loading model: {self.model_name} on {self.device}")
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype="auto",
            device_map="auto",
            trust_remote_code=True
        )
        self.model.eval()
        print(f"✅ Model loaded on {self.device.upper()}")

    def generate_text(self, input_text, system_prompt, max_new_tokens=2048,
                      temperature=0.7, top_p=0.9, progress_callback=None):
        """Run Qwen inference with optional streaming progress.

        Args:
            input_text: user prompt string
            system_prompt: system message string
            max_new_tokens: maximum tokens to generate
            temperature: sampling temperature
            top_p: nucleus sampling probability
            progress_callback: callable(percent: int, text: str)

        Returns:
            dict: {"text": str, "model": str, "input_tokens": int, "output_tokens": int}
        """
        import torch
        from transformers import TextIteratorStreamer

        def _cb(percent, msg):
            print(f"PROGRESS:{percent}:{msg}")
            if progress_callback:
                progress_callback(percent, msg)

        _cb(10, "Building prompt...")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ]

        # Qwen3 supports enable_thinking; set False for direct answers
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )

        _cb(20, "Tokenizing...")
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        input_token_count = model_inputs["input_ids"].shape[1]

        _cb(30, "Generating...")

        streamer = TextIteratorStreamer(
            self.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        generate_kwargs = {
            **model_inputs,
            "streamer": streamer,
            "max_new_tokens": max_new_tokens,
            "do_sample": temperature > 0,
            "temperature": temperature,
            "top_p": top_p,
        }

        def _generate():
            try:
                self.model.generate(**generate_kwargs)
            except Exception as e:
                print(f"Exception in generation thread: {e}", flush=True)
                import traceback
                traceback.print_exc()
                # Stop the streamer to unblock the main thread
                try:
                    streamer.text_queue.put(streamer.stop_signal, timeout=1)
                except:
                    pass

        gen_thread = threading.Thread(target=_generate)
        gen_thread.start()

        # Collect streamed tokens and report progress
        generated_tokens = []
        token_count = 0
        for token_text in streamer:
            generated_tokens.append(token_text)
            token_count += 1
            if token_count % 20 == 0:
                pct = min(30 + int((token_count / max_new_tokens) * 65), 95)
                _cb(pct, f"Generating... ({token_count} tokens)")

        gen_thread.join()

        result_text = "".join(generated_tokens).strip()

        _cb(100, "Done")
        print(f"✅ Generation complete — {token_count} output tokens")

        return {
            "text": result_text,
            "model": self.model_name,
            "input_tokens": input_token_count,
            "output_tokens": token_count,
        }
