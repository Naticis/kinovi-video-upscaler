# Kinovi Video Upscaler — RunPod Serverless

A small RunPod Serverless wrapper around the official `xinntao/Real-ESRGAN` project.

## First milestone

- MP4 input by public/presigned URL
- `RealESRGAN_x2plus` by default
- 2x upscale by default
- Original frame rate retained by the official video inference script
- Original audio retained when compatible
- Optional exact 720p / 1080p / 2160p post-resize without stretching the image
- Optional presigned HTTPS PUT URL for delivering larger results
- Base64 return is available only for small test clips

## Recommended first test

Use a 5–10 second 480p MP4.

```json
{
  "input": {
    "video_url": "https://YOUR-PUBLIC-OR-PRESIGNED-URL/test.mp4",
    "model": "RealESRGAN_x2plus",
    "scale": 2,
    "face_enhance": false
  }
}
```

For exact 1080p output after the AI pass:

```json
{
  "input": {
    "video_url": "https://YOUR-PUBLIC-OR-PRESIGNED-URL/test.mp4",
    "model": "RealESRGAN_x2plus",
    "scale": 2,
    "target_resolution": "1080p",
    "face_enhance": false
  }
}
```

The 1080p mode preserves aspect ratio and pads only if necessary; it does not distort the image.

## Production delivery

Returning a video as Base64 is intentionally limited to 20 MiB in this starter worker. For normal video jobs, create a presigned HTTPS PUT URL in your storage service and pass it as `output_upload_url`:

```json
{
  "input": {
    "video_url": "https://storage.example/input.mp4?...",
    "model": "RealESRGAN_x2plus",
    "scale": 2,
    "output_upload_url": "https://storage.example/output.mp4?..."
  }
}
```

The worker uploads the MP4 to that URL and does not echo the signed URL back in its response.

## Build locally

From this folder:

```bash
docker build -t kinovi-video-upscaler:0.1 .
```

Later, tag and push the image to a container registry that RunPod can pull from. GitHub is not required.

## RunPod

Create a new custom Serverless template/endpoint using the built container image. Keep the existing working image-upscaler endpoint unchanged while testing this one.

For video jobs, use RunPod's asynchronous `/run` flow rather than keeping a long `/runsync` request open.

## Useful inputs

- `video_url` — required HTTP/HTTPS video URL
- `model` — default `RealESRGAN_x2plus`
- `scale` — default `2`, allowed 1.0–4.0
- `face_enhance` — default `false`
- `tile` — default `0`; use a positive tile size only if GPU memory becomes an issue
- `num_process_per_gpu` — default `1`; test before increasing
- `target_resolution` — optional: `720p`, `1080p`, `2160p`
- `target_width` + `target_height` — optional custom exact output canvas
- `output_upload_url` — optional presigned HTTPS PUT URL for result delivery

## Notes

The Docker image clones the public official Real-ESRGAN repository during build, so you do not need a GitHub account. The `RealESRGAN_x2plus` weight is also baked into the image to reduce cold-start downloads.

This starter deliberately prioritizes reliability over maximum throughput. Once the first 5–10 second clip works, the next optimization step is benchmarking process count, tile size, and encoding settings on the exact RunPod GPU class you choose.

## Licensing

Real-ESRGAN is maintained by xinntao and is licensed under BSD-3-Clause. Preserve the upstream license and notices when using/distributing its code. This starter wrapper is provided separately; review licensing for your own deployment/distribution needs.
