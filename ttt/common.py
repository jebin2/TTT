import os
import gc
import time


def is_gpu_available(verbose=True):
    import torch
    if not torch.cuda.is_available():
        if verbose:
            print("CUDA not available.")
    return False

    try:
        torch.empty(1, device="cuda")
        if verbose:
            print(f"CUDA available. Using device: {torch.cuda.get_device_name(0)}")
        return True
    except RuntimeError as e:
        if "CUDA-capable device(s) is/are busy or unavailable" in str(e) or \
           "CUDA error" in str(e):
            if verbose:
                print("CUDA detected but busy/unavailable. Using CPU.")
            return False
        raise


def get_device():
    import torch
    if os.getenv("USE_CPU_IF_POSSIBLE", None):
        torch.cuda.is_available = lambda: False
        return "cpu"

    device = "cuda" if is_gpu_available() else "cpu"

    if device == "cpu":
        torch.cuda.is_available = lambda: False

    return device


def clear_gpu_cache():
    try:
        gc.collect()
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception as e:
        print(f"⚠️  GPU cache clear error: {e}")
