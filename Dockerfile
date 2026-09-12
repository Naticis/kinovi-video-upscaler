# Kinovi Real-ESRGAN RunPod Serverless worker
# Uses the official xinntao/Real-ESRGAN project as the inference engine.

FROM pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    REAL_ESRGAN_DIR=/app/Real-ESRGAN

# Install system dependencies, including Ubuntu FFmpeg with libx264 support.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The PyTorch/Conda base image can contain its own limited FFmpeg build.
# Replace those binaries with Ubuntu's FFmpeg/ffprobe so Real-ESRGAN
# gets libx264 and the full codec set.
RUN rm -f /opt/conda/bin/ffmpeg /opt/conda/bin/ffprobe \
    && ln -s /usr/bin/ffmpeg /opt/conda/bin/ffmpeg \
    && ln -s /usr/bin/ffprobe /opt/conda/bin/ffprobe

# Fail the Docker build immediately if H.264 encoding is unavailable.
RUN ffmpeg -hide_banner -encoders | grep -q libx264

WORKDIR /app

# Official Real-ESRGAN source.
RUN git clone --depth 1 \
    https://github.com/xinntao/Real-ESRGAN.git \
    /app/Real-ESRGAN

WORKDIR /app/Real-ESRGAN

# Pin versions compatible with the older BasicSR / Real-ESRGAN stack.
# NumPy must remain below 2.x for this PyTorch/BasicSR combination.
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

# Preload the RealESRGAN_x2plus model so workers do not need
# to download the model during every cold start.
RUN mkdir -p /app/Real-ESRGAN/weights \
    && curl -L --fail --retry 3 \
        https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth \
        -o /app/Real-ESRGAN/weights/RealESRGAN_x2plus.pth

# Install RunPod worker dependencies.
COPY requirements.txt /app/requirements-runpod.txt

RUN pip install -r /app/requirements-runpod.txt

# Copy our RunPod handler.
COPY handler.py /app/handler.py

WORKDIR /app

CMD ["python", "-u", "/app/handler.py"]
