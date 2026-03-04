import os
from .base import BaseTTT
from .ollama_service import OllamaService, OllamaConfig
from custom_logger import logger_config

class OllamaTTTProcessor(BaseTTT):
    """Text-to-text processor using Ollama."""

    def __init__(self, model_name="qwen3.5:4b"):
        super().__init__("ollama")
        self.model_name = model_name
        self._load_model()

    def _load_model(self):
        logger_config.info(f"Initializing OllamaService for model: {self.model_name}")
        self.ollama_service = OllamaService()
        self.ollama_service.initialize(self.model_name)
        self.client = self.ollama_service.client
        logger_config.info(f"✅ Model ready via Ollama: {self.model_name}")

    def generate_text(self, input_text, system_prompt, max_new_tokens=2048,
                      temperature=0.7, top_p=0.9, progress_callback=None):
        """Run Ollama inference with streaming progress.

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
        def _cb(percent, msg):
            print(f"PROGRESS:{percent}:{msg}")
            if progress_callback:
                progress_callback(percent, msg)

        _cb(10, "Building prompt...")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": input_text})

        _cb(20, "Generating via Ollama...")

        try:
            num_thread = int(os.environ.get("OMP_NUM_THREADS", max(1, (os.cpu_count() or 4) - 2)))

            response = self.client.chat(
                model=self.model_name,
                messages=messages,
                stream=True,
                think=False,
                options={
                    "num_predict": max_new_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                    "num_thread": num_thread
                }
            )

            content = ""
            chunk_count = 0

            for chunk in response:
                if hasattr(chunk, 'message'):
                    current_data = chunk.message.content or ''
                else:
                    current_data = chunk.get('message', {}).get('content', '')
                if current_data:
                    content += current_data
                    chunk_count += 1
                    
                    if chunk_count % 10 == 0:
                        pct = min(20 + int(75 * chunk_count / max_new_tokens), 95)
                        _cb(pct, f"Generating... ({chunk_count} tokens)")

            _cb(100, "Done")
            logger_config.info(f"✅ Generation complete")

            return {
                "text": content,
                "model": self.model_name,
                "input_tokens": 0, # Not easily available in stream
                "output_tokens": chunk_count, # Approximate
            }

        except Exception as e:
            logger_config.error(f"Error during chat response generation: {e}")
            self.ollama_service.restart()
            return None
