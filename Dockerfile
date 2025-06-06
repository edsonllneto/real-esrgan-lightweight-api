FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    libvulkan1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/models

RUN wget -q https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases/download/v0.2.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip && \
    unzip realesrgan-ncnn-vulkan-20220424-ubuntu.zip && \
    mv realesrgan-ncnn-vulkan-20220424-ubuntu/realesrgan-ncnn-vulkan /app/ && \
    mv realesrgan-ncnn-vulkan-20220424-ubuntu/models/* /app/models/ && \
    chmod +x /app/realesrgan-ncnn-vulkan && \
    rm -rf realesrgan-ncnn-vulkan-20220424-ubuntu* 

COPY app.py .

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]