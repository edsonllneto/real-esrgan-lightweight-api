from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import base64
import io
import os
import subprocess
import tempfile
from PIL import Image
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Image Upscaler",
    description="Lightweight AI image upscaling service with Real-ESRGAN-ncnn-vulkan",
    version="1.0.0"
)

class Base64Request(BaseModel):
    image: str
    scale: Optional[int] = 4

class UpscalerService:
    def __init__(self):
        self.realesrgan_binary = "/app/realesrgan-ncnn-vulkan"
        self.models_path = "/app/models"
        self.temp_dir = "/tmp"
        self._check_binary()
    
    def _check_binary(self):
        if not os.path.exists(self.realesrgan_binary):
            logger.warning("Real-ESRGAN-ncnn-vulkan binary not found")
            self.realesrgan_binary = None
        else:
            logger.info("Real-ESRGAN-ncnn-vulkan binary found")
    
    def upscale_image(self, image: Image.Image, scale: int = 4) -> Image.Image:
        try:
            if self.realesrgan_binary:
                return self._upscale_ncnn(image, scale)
            else:
                return self._upscale_fallback(image, scale)
        except Exception as e:
            logger.error(f"Real-ESRGAN-ncnn upscaling failed: {e}")
            logger.info("Falling back to simple upscaling")
            return self._upscale_fallback(image, scale)
    
    def _upscale_ncnn(self, image: Image.Image, scale: int) -> Image.Image:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as input_file:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as output_file:
                try:
                    image.save(input_file.name, 'PNG')
                    
                    model_name = self._get_model_name(scale)
                    
                    cmd = [
                        self.realesrgan_binary,
                        "-i", input_file.name,
                        "-o", output_file.name,
                        "-n", model_name,
                        "-s", str(scale),
                        "-f", "png"
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    
                    if result.returncode != 0:
                        logger.error(f"Real-ESRGAN-ncnn failed: {result.stderr}")
                        raise Exception("NCNN processing failed")
                    
                    if os.path.exists(output_file.name):
                        upscaled_image = Image.open(output_file.name)
                        return upscaled_image.copy()
                    else:
                        raise Exception("Output file not created")
                        
                finally:
                    for temp_file in [input_file.name, output_file.name]:
                        if os.path.exists(temp_file):
                            os.unlink(temp_file)
    
    def _get_model_name(self, scale: int) -> str:
        model_map = {
            2: "realesr-animevideov3",
            4: "realesrgan-x4plus",
            8: "realesrgan-x4plus"
        }
        return model_map.get(scale, "realesrgan-x4plus")
    
    def _upscale_fallback(self, image: Image.Image, scale: int) -> Image.Image:
        width, height = image.size
        new_size = (width * scale, height * scale)
        return image.resize(new_size, Image.LANCZOS)

upscaler = UpscalerService()

def process_image(image_data: bytes, scale: int = 4) -> bytes:
    try:
        image = Image.open(io.BytesIO(image_data)).convert('RGB')
        
        max_size = 2048
        if max(image.size) > max_size:
            ratio = max_size / max(image.size)
            new_size = tuple(int(dim * ratio) for dim in image.size)
            image = image.resize(new_size, Image.LANCZOS)
        
        upscaled = upscaler.upscale_image(image, scale)
        
        output_buffer = io.BytesIO()
        upscaled.save(output_buffer, format='PNG', optimize=True)
        output_buffer.seek(0)
        
        return output_buffer.getvalue()
        
    except Exception as e:
        logger.error(f"Image processing failed: {e}")
        raise HTTPException(status_code=400, detail=f"Image processing failed: {str(e)}")

@app.get("/")
async def root():
    return {"message": "AI Image Upscaler API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {
        "status": "healthy", 
        "engine": "Real-ESRGAN-ncnn-vulkan" if upscaler.realesrgan_binary else "Fallback",
        "binary_found": upscaler.realesrgan_binary is not None
    }

@app.post("/upscale/binary")
async def upscale_binary(file: UploadFile = File(...), scale: int = 4):
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    if scale not in [2, 4, 8]:
        raise HTTPException(status_code=400, detail="Scale must be 2, 4, or 8")
    
    image_data = await file.read()
    upscaled_data = process_image(image_data, scale)
    
    return StreamingResponse(
        io.BytesIO(upscaled_data),
        media_type="image/png",
        headers={"Content-Disposition": f"attachment; filename=upscaled_{file.filename}"}
    )

@app.post("/upscale/base64")
async def upscale_base64(request: Base64Request):
    if request.scale not in [2, 4, 8]:
        raise HTTPException(status_code=400, detail="Scale must be 2, 4, or 8")
    
    try:
        image_data = base64.b64decode(request.image)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image data")
    
    upscaled_data = process_image(image_data, request.scale)
    upscaled_base64 = base64.b64encode(upscaled_data).decode('utf-8')
    
    return {"upscaled_image": upscaled_base64}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)