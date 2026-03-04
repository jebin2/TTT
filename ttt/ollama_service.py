"""
Isolated Ollama Service Manager
Handles: Configuration, Startup, Wait, Retry, Health Checks

To run ollama service without GPU access (CPU only), set the following environment variables:

# Create override directory
sudo mkdir -p /etc/systemd/system/ollama.service.d

# Create override file
sudo nano /etc/systemd/system/ollama.service.d/override.conf

[Service]
Environment="CUDA_VISIBLE_DEVICES="

"""
import os
import subprocess
import time
import requests
from dataclasses import dataclass
from typing import Optional

from custom_logger import logger_config

@dataclass
class OllamaConfig:
    """Configuration for Ollama service"""
    host: str = os.environ.get("OLLAMA_REQ_URL", "http://localhost:11434")
    startup_timeout: int = 30  # seconds to wait for service startup
    startup_retry_interval: int = 1  # seconds between startup checks
    pull_timeout: int = 300  # seconds to wait for model pull
    health_check_timeout: int = 3  # seconds for health check request
    max_retries: int = 3  # max retries for operations
    retry_delay: int = 2  # seconds between retries


class OllamaService:
    """
    Isolated Ollama service manager.
    Handles all Ollama lifecycle: config, start, wait, retry, health checks.
    """

    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()
        self._client = None
        self._setup_environment()

    def _setup_environment(self):
        """Configure CPU-only environment and thread limits"""
        os.environ["OLLAMA_NO_GPU"] = "1"
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        os.environ["NVIDIA_VISIBLE_DEVICES"] = "none"
        os.environ["NVIDIA_DRIVER_CAPABILITIES"] = "none"
        # Reserve 2 cores for the OS; let run_app.sh override if already set
        reserved = 2
        threads = str(max(1, (os.cpu_count() or 4) - reserved))
        os.environ.setdefault("OMP_NUM_THREADS", threads)
        logger_config.debug(f"Ollama configured for CPU-only mode ({os.environ['OMP_NUM_THREADS']} threads)")

    @property
    def client(self):
        """Lazy-load Ollama client"""
        if self._client is None:
            import ollama
            self._client = ollama.Client(host=self.config.host)
        return self._client

    # ==================== Health Checks ====================

    def is_running(self) -> bool:
        """Check if Ollama service is running"""
        try:
            response = requests.get(
                f"{self.config.host}/api/tags",
                timeout=self.config.health_check_timeout
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def is_model_available(self, model: str) -> bool:
        """Check if a model is already available locally"""
        try:
            models = self.client.list()
            model_names = [m.get('name', '') for m in models.get('models', [])]
            base_model = model.split(':')[0]
            return any(
                name == model or name.startswith(f"{base_model}:")
                for name in model_names
            )
        except Exception as e:
            logger_config.warning(f"Could not check model availability: {e}")
            return False

    # ==================== Service Control ====================

    def start(self) -> bool:
        """Start Ollama service with retry logic"""
        for attempt in range(1, self.config.max_retries + 1):
            logger_config.info(f"Starting Ollama service (attempt {attempt}/{self.config.max_retries})...")
            
            if self._try_start():
                return True
            
            if attempt < self.config.max_retries:
                logger_config.warning(f"Retrying in {self.config.retry_delay} seconds...")
                time.sleep(self.config.retry_delay)
        
        logger_config.error("Failed to start Ollama service after all retries")
        return False

    def _install_ollama(self) -> bool:
        """Install Ollama using the official install script"""
        try:
            logger_config.info("Downloading and installing Ollama (this may take a moment)...")
            result = subprocess.run(
                "curl -fsSL https://ollama.com/install.sh | sh",
                shell=True,
                timeout=300
            )
            if result.returncode == 0:
                logger_config.info("Ollama installed successfully")
                return True
            logger_config.error("Ollama installation script returned a non-zero exit code")
            return False
        except subprocess.TimeoutExpired:
            logger_config.error("Ollama installation timed out after 300 seconds")
            return False
        except Exception as e:
            logger_config.error(f"Error installing Ollama: {e}")
            return False

    def _try_start(self) -> bool:
        """Single attempt to start Ollama service"""
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return self._wait_for_startup()
        except FileNotFoundError:
            logger_config.warning("Ollama not found. Installing automatically...")
            if not self._install_ollama():
                logger_config.error("Automatic Ollama installation failed")
                return False
            try:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return self._wait_for_startup()
            except Exception as e:
                logger_config.error(f"Error starting Ollama after installation: {e}")
                return False
        except Exception as e:
            logger_config.error(f"Error starting Ollama: {e}")
            return False

    def _wait_for_startup(self) -> bool:
        """Wait for Ollama service to become ready"""
        logger_config.debug(f"Waiting up to {self.config.startup_timeout}s for Ollama to start...")
        
        for _ in range(self.config.startup_timeout // self.config.startup_retry_interval):
            time.sleep(self.config.startup_retry_interval)
            if self.is_running():
                logger_config.info("Ollama service started successfully")
                return True
        
        logger_config.error(f"Ollama failed to start within {self.config.startup_timeout} seconds")
        return False

    def restart(self) -> bool:
        """Restart Ollama service by killing and restarting the process"""
        try:
            logger_config.info("Restarting Ollama service...")
            subprocess.run(["pkill", "-f", "ollama serve"], check=False, timeout=10)
            time.sleep(2)
            return self.start()
        except Exception as e:
            logger_config.error(f"Error restarting Ollama: {e}")
            return False

    def ensure_running(self) -> bool:
        """Ensure Ollama is running, start if necessary"""
        if self.is_running():
            logger_config.debug("Ollama service is already running")
            return True
        
        logger_config.warning("Ollama is not running. Attempting to start...")
        return self.start()

    def stop_model(self, model: str) -> bool:
        """Unload/stop a specific model"""
        try:
            logger_config.info(f"Unloading model {model}...")
            result = subprocess.run(
                ["ollama", "stop", model],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30
            )
            if result.returncode == 0:
                logger_config.info(f"Model {model} unloaded successfully")
                return True
            else:
                logger_config.warning(f"Model {model} may not have been loaded")
                return True  # Not a failure if model wasn't loaded
        except subprocess.TimeoutExpired:
            logger_config.error(f"Timeout while unloading model {model}")
            return False
        except Exception as e:
            logger_config.error(f"Failed to unload model {model}: {e}")
            return False

    # ==================== Model Management ====================

    def pull_model(self, model: str, force: bool = False) -> bool:
        """Pull a model with progress tracking"""
        if not force and self.is_model_available(model):
            logger_config.info(f"Model {model} is already available")
            return True

        for attempt in range(1, self.config.max_retries + 1):
            logger_config.info(f"Pulling model {model} (attempt {attempt}/{self.config.max_retries})...")
            
            if self._try_pull_model(model):
                return True
            
            if attempt < self.config.max_retries:
                logger_config.warning(f"Retrying pull in {self.config.retry_delay} seconds...")
                time.sleep(self.config.retry_delay)
        
        logger_config.error(f"Failed to pull model {model} after all retries")
        return False

    def _try_pull_model(self, model: str) -> bool:
        """Single attempt to pull a model"""
        try:
            for progress in self.client.pull(model, stream=True):
                if 'status' in progress:
                    status = progress['status']
                    completed = progress.get('completed') or 0
                    total = progress.get('total') or 0
                    
                    if total and total > 0:
                        pct = (completed / total) * 100
                        print(f"\r{status}: {pct:.1f}%", end="", flush=True)
                    else:
                        print(f"\r{status}", end="", flush=True)
            
            print()  # New line after progress
            logger_config.info(f"Model {model} pulled successfully")
            return True
        except Exception as e:
            logger_config.error(f"Error pulling model {model}: {e}")
            return False

    # ==================== Initialization ====================

    def initialize(self, model: str) -> bool:
        """
        Full initialization sequence:
        1. Configure environment
        2. Ensure service is running
        3. Pull model if needed
        """
        logger_config.info(f"Initializing Ollama with model {model}...")
        
        # Step 1: Ensure service is running
        if not self.ensure_running():
            raise RuntimeError("Failed to start Ollama service")
        
        # Step 2: Pull model if not available
        if not self.pull_model(model):
            raise RuntimeError(f"Failed to pull model {model}")
        
        logger_config.info(f"Ollama initialized successfully with model {model}")
        return True


# Singleton instance for convenience
_default_service: Optional[OllamaService] = None


def get_ollama_service(config: Optional[OllamaConfig] = None) -> OllamaService:
    """Get or create the default Ollama service instance"""
    global _default_service
    if _default_service is None or config is not None:
        _default_service = OllamaService(config)
    return _default_service
