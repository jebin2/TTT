FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV OLLAMA_HOST=0.0.0.0

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    zstd \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Copy project files
COPY pyproject.toml .
COPY . .

# Install dependencies and project
RUN pip install --no-cache-dir .

# Create necessary directories
RUN mkdir -p uploads temp_dir

# Expose port
EXPOSE 7860

# Run the FastAPI app (worker starts automatically on first task)
CMD ["python", "run.py"]
