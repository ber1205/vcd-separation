FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu124

RUN pip install --no-cache-dir "audio-separator[gpu]" runpod boto3 requests

COPY handler.py /app/handler.py

ARG MODEL_NAME=vocals_mel_band_roformer.ckpt
ENV MODEL_FILE_DIR=/app/models \
    MODEL_NAME=${MODEL_NAME}

# 烘焙模型权重进镜像（冷启动只做显存加载，不再联网下载）
RUN mkdir -p /app/models && python -c "from audio_separator.separator import Separator; s = Separator(model_file_dir='/app/models'); s.load_model(model_filename='${MODEL_NAME}')"

CMD ["python", "-u", "/app/handler.py"]
