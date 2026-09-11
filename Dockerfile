# Kinovi Real-ESRGAN RunPod Serverless worker
# Uses the official xinntao/Real-ESRGAN project as the inference engine.
FROM pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    REAL_ESRGAN_DIR=/app/Real-ESRGAN

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Official Real-ESRGAN source. No GitHub account is required because this is a public repository.
RUN git clone --depth 1 https://github.com/xinntao/Real-ESRGAN.git /app/Real-ESRGAN

WORKDIR /app/Real-ESRGAN

# Pin versions that remain compatible with the older BasicSR/Real-ESRGAN inference stack.
RUN pip install --upgrade pip setuptools wheel \
    && pip install \
      numpy==1.26.4 \
    basicsr==1.4.2 \
    facexlib==0.3.0 \
    gfpgan==1.3.8 \
    ffmpeg-python==0.2.0 \
    opencv-python-headless==4.9.0.80 \
    pillow==10.2.0 \
    tqdm==4.66.2 \
    && python setup.py develop

# Preload the x2 model so cold starts do not have to fetch it.
RUN mkdir -p /app/Real-ESRGAN/weights \
    && curl -L --fail --retry 3 \
       https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth \
       -o /app/Real-ESRGAN/weights/RealESRGAN_x2plus.pth

COPY requirements.txt /app/requirements-runpod.txt
RUN pip install -r /app/requirements-runpod.txt

COPY handler.py /app/handler.py

WORKDIR /app
CMD ["python", "-u", "/app/handler.py"]
