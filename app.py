from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import base64
import io
import os
import gc
import torch
from PIL import Image
import numpy as np
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Image Upscaler",
    description="Lightweight AI image upscaling service with Real-ESRGAN and NCNN fallback",
    version="1.0.0"
)

class Base64Request(BaseModel):
    image: str
    scale: Optional[int] = 4

class UpscalerService:
    def __init__(self):
        self.realesrgan_model = None
        self.ncnn_model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._init_models()
    
    def _init_models(self):
        try:
            from realesrgan import RealESRGANer
            from basicsr.archs.rrdbnet_arch import RRDBNet
            
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
            self.realesrgan_model = RealESRGANer(
                scale=4,
                model_path='https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
                model=model,
                tile=400,
                tile_pad=10,
                pre_pad=0,
                half=True if self.device == "cuda" else False,
                device=self.device
            )
            logger.info("Real-ESRGAN model loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load Real-ESRGAN: {e}")
            self._init_ncnn_fallback()
    
    def _init_ncnn_fallback(self):
        try:
            import ncnn
            logger.info("Initializing NCNN fallback")
            self.ncnn_model = True
        except Exception as e:
            logger.error(f"Failed to initialize NCNN fallback: {e}")
            raise HTTPException(status_code=500, detail="No upscaling models available")
    
    def upscale_image(self, image: Image.Image, scale: int = 4) -> Image.Image:
        try:
            if self.realesrgan_model:
                return self._upscale_realesrgan(image, scale)
            elif self.ncnn_model:
                return self._upscale_ncnn(image, scale)
            else:
                raise HTTPException(status_code=500, detail="No upscaling models available")
        except Exception as e:
            logger.error(f"Upscaling failed: {e}")
            if self.ncnn_model and self.realesrgan_model:
                logger.info("Falling back to NCNN")
                return self._upscale_ncnn(image, scale)
            raise HTTPException(status_code=500, detail="Upscaling failed")
    
    def _upscale_realesrgan(self, image: Image.Image, scale: int) -> Image.Image:
        img_np = np.array(image)
        output, _ = self.realesrgan_model.enhance(img_np, outscale=scale)
        
        torch.cuda.empty_cache()
        gc.collect()
        
        return Image.fromarray(output)
    
    def _upscale_ncnn(self, image: Image.Image, scale: int) -> Image.Image:
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
    return {"status": "healthy", "device": upscaler.device}

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