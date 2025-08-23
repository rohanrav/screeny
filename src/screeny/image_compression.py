"""
Image compression utilities for Screeny MCP server.

Provides intelligent image compression that tries multiple strategies
to achieve target file sizes while maintaining quality.
"""

import io
from base64 import b64encode
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
            ("JPEG_Q90_S1.0", 1.0, "JPEG", 90),
            ("JPEG_Q85_S1.0", 1.0, "JPEG", 85),
            ("JPEG_Q80_S1.0", 1.0, "JPEG", 80),
            ("JPEG_Q75_S1.0", 1.0, "JPEG", 75),
            ("JPEG_Q70_S1.0", 1.0, "JPEG", 70),
            ("JPEG_Q85_S0.9", 0.9, "JPEG", 85),
            ("JPEG_Q80_S0.9", 0.9, "JPEG", 80),
            ("JPEG_Q75_S0.9", 0.9, "JPEG", 75),
            ("JPEG_Q70_S0.9", 0.9, "JPEG", 70),
            ("JPEG_Q80_S0.8", 0.8, "JPEG", 80),
            ("JPEG_Q75_S0.8", 0.8, "JPEG", 75),
            ("JPEG_Q70_S0.8", 0.8, "JPEG", 70),
            ("JPEG_Q70_S0.7", 0.7, "JPEG", 70),
            ("JPEG_Q65_S0.6", 0.6, "JPEG", 65),
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


def compress_to_base64_cap(image_path: str, base64_max_bytes: int) -> Tuple[str, str, int, float, int, bool]:
    """Compress to JPEG under a base64 cap preferring quality over scale.

    Strategy:
    - Try larger scales first, but enforce a quality floor (start high) at each scale
    - If no fit at a given floor across all scales, lower the floor and retry
    - Within each (scale, floor), binary search quality in [floor, 95] to find highest that fits
    - Return first valid result. If none, return empty so caller can surface a clear error.

    Returns: (base64_data, mime_type, base64_size_bytes, chosen_scale, chosen_quality, used_fallback)
    """

    def ensure_rgb(image: Image.Image) -> Image.Image:
        if image.mode in ("RGBA", "LA", "P"):
            base = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            base.paste(image, mask=image.split()
                       [-1] if image.mode == "RGBA" else None)
            return base
        if image.mode != "RGB":
            return image.convert("RGB")
        return image

    def encode_jpeg_bytes(image: Image.Image, quality: int) -> bytes:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    # Prefer minimal resizing: attempt larger scales first; extend to smaller scales
    scale_candidates = (
        1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6,
        0.55, 0.5, 0.45, 0.4, 0.35, 0.3, 0.25, 0.2
    )
    # Quality floors, highest-first to prefer quality over scale
    quality_floors = (80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30)

    with Image.open(image_path) as src:
        src = ensure_rgb(src)

        for floor in quality_floors:
            for scale in scale_candidates:
                if scale != 1.0:
                    new_w = max(1, int(src.width * scale))
                    new_h = max(1, int(src.height * scale))
                    img = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
                else:
                    img = src

                # Binary search quality in [floor, 95]
                lo, hi = floor, 95
                best_fit_b64 = None
                best_fit_quality = None
                while lo <= hi:
                    mid = (lo + hi) // 2
                    try:
                        data = encode_jpeg_bytes(img, mid)
                    except Exception:
                        hi = mid - 1
                        continue

                    b64 = b64encode(data).decode("utf-8")
                    b64_len = len(b64.encode("utf-8"))
                    if b64_len <= base64_max_bytes:
                        best_fit_b64 = b64
                        best_fit_quality = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1

                if best_fit_b64 is not None:
                    return best_fit_b64, "image/jpeg", len(best_fit_b64), scale, int(best_fit_quality or floor), False

    return "", "image/jpeg", 0, -1.0, -1, False
