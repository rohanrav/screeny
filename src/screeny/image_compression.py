"""
Image compression utilities for Screeny MCP server.

Provides intelligent image compression that tries multiple strategies
to achieve target file sizes while maintaining quality.
"""

import io
from pathlib import Path
from typing import Tuple
from PIL import Image


def compress_image(image_path: str, target_size_bytes: int) -> Tuple[bytes, str]:
    """
    Compress image to JPEG format for smaller file sizes.

    Args:
        image_path: Path to the image file
        target_size_bytes: Target size in bytes for the compressed image

    Returns:
        Tuple of (compressed image data as bytes, format used)

    Strategy:
        Try JPEG compression with decreasing quality levels until target is met,
        or return the best compression achieved.
    """
    with Image.open(image_path) as img:
        strategies = [
            ("JPEG_HIGH", 1.0, "JPEG", 90),
            ("JPEG_MEDIUM", 1.0, "JPEG", 80),
            ("JPEG_LOW", 1.0, "JPEG", 70),
            ("JPEG_SMALL", 0.9, "JPEG", 85),
        ]

        best_data = None
        best_format = "JPEG"

        for _, scale_factor, format_type, quality in strategies:
            try:
                if scale_factor == 1.0:
                    resized_img = img
                else:
                    new_width = max(1, int(img.width * scale_factor))
                    new_height = max(1, int(img.height * scale_factor))
                    resized_img = img.resize(
                        (new_width, new_height), Image.Resampling.LANCZOS)

                buffer = io.BytesIO()

                # Convert RGBA to RGB for JPEG
                if resized_img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new(
                        'RGB', resized_img.size, (255, 255, 255))
                    if resized_img.mode == 'P':
                        resized_img = resized_img.convert('RGBA')
                    rgb_img.paste(resized_img, mask=resized_img.split(
                    )[-1] if resized_img.mode == 'RGBA' else None)
                    resized_img = rgb_img

                resized_img.save(buffer, format='JPEG',
                                 quality=quality, optimize=True)
                result_data = buffer.getvalue()

                # Use first result that fits, or keep the best one
                if len(result_data) <= target_size_bytes:
                    return result_data, format_type

                if best_data is None or len(result_data) < len(best_data):
                    best_data = result_data
                    best_format = format_type

            except Exception:
                continue

        # Return best attempt or original if all failed
        if best_data is not None:
            return best_data, best_format
        else:
            return Path(image_path).read_bytes(), "PNG"


def get_mime_type(format_name: str) -> str:
    """
    Get MIME type for image format.
    """
    return "image/png" if format_name == "PNG" else "image/jpeg"
