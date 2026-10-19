import os
import logging
from typing import Optional, Union, BinaryIO
import cloudinary
import cloudinary.uploader
from ..core.config import settings

logger = logging.getLogger("ai-service.cloudinary")

class CloudinaryStorageService:
    def __init__(self):
        self._configured = False
        self._init_cloudinary()

    def _init_cloudinary(self):
        # Support either CLOUDINARY_URL or explicit keys
        if settings.cloudinary_url:
            cloudinary.config(
                cloudinary_url=settings.cloudinary_url,
                secure=True
            )
            self._configured = True
            logger.info("[Cloudinary] Initialized storage via CLOUDINARY_URL connection string.")
        elif settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret:
            cloudinary.config(
                cloud_name=settings.cloudinary_cloud_name,
                api_key=settings.cloudinary_api_key,
                api_secret=settings.cloudinary_api_secret,
                secure=True
            )
            self._configured = True
            logger.info(f"[Cloudinary] Initialized storage for cloud: {settings.cloudinary_cloud_name}")
        else:
            self._configured = False

    def is_configured(self) -> bool:
        return self._configured

    def upload_image(
        self,
        file_input: Union[str, bytes, BinaryIO],
        folder: Optional[str] = None,
        public_id: Optional[str] = None,
        tags: Optional[list[str]] = None
    ) -> Optional[str]:
        """
        Uploads an image to Cloudinary and returns the HTTPS secure CDN URL.
        Falls back cleanly to None if not configured or if upload errors, allowing zero downtime.
        """
        if not self.is_configured():
            return None

        target_folder = folder or settings.cloudinary_folder
        upload_options = {
            "folder": target_folder,
            "resource_type": "image",
            "overwrite": True,
        }
        if public_id:
            upload_options["public_id"] = public_id
        if tags:
            upload_options["tags"] = tags

        try:
            result = cloudinary.uploader.upload(file_input, **upload_options)
            secure_url = result.get("secure_url") or result.get("url")
            logger.info(f"[Cloudinary] Successfully uploaded image -> {secure_url}")
            return secure_url
        except Exception as exc:
            logger.warning(f"[Cloudinary] Upload failed ({exc}), falling back to local file storage.")
            return None

cloudinary_service = CloudinaryStorageService()
