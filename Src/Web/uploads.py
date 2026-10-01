"""Validating and storing uploaded or pasted screenshots."""

import logging
import os
import re
import time

logger = logging.getLogger(__name__)


def cleanup_uploads(folder, max_age=3600):
    """Remove uploads older than `max_age` seconds so the disk cannot fill up.

    Uploads are deleted right after processing; this catches any left behind
    by a crash.
    """
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) and os.path.getmtime(file_path) < time.time() - max_age:
                os.unlink(file_path)
        except OSError:
            logger.exception("Could not remove old upload %s", file_path)


# MIME subtype of a pasted data: URL -> file extension we save it under.
PASTED_IMAGE_EXTENSIONS = {
    'png': 'png',
    'jpeg': 'jpg',
    'jpg': 'jpg',
    'webp': 'webp',
    'bmp': 'bmp',
    # OpenCV cannot read GIF, so a pasted GIF is re-encoded as PNG.
    'gif': 'png',
}

# Formats cv2.imread can read, as Pillow names them -> extension to save under.
CV2_READABLE_FORMATS = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp', 'BMP': 'bmp'}

# The only formats Pillow may even try to open. Without this list Image.open
# probes every plugin it has, and loading an EPS/PS file runs Ghostscript on
# the uploaded PostScript when it is installed (it is on most Linux hosts).
ALLOWED_IMAGE_FORMATS = ('PNG', 'JPEG', 'WEBP', 'BMP', 'GIF')

# Largest image accepted, in pixels. An 8K screenshot is ~33 MP. Pillow only
# refuses images over ~179 MP, so a 20 MB upload could otherwise be a 13000 x
# 13000 PNG that decodes to hundreds of MB in Pillow and again in OpenCV.
MAX_IMAGE_PIXELS = 40_000_000


def decode_pasted_image(image_data):
    """Split a pasted image into (extension, bytes).

    Accepts a `data:image/<type>;base64,...` URL or bare base64 (assumed PNG).
    The subtype used to be copied straight from the request into the saved
    file name, so a crafted header such as `data:image/..\\..\\app.py;base64,`
    chose the path and extension of the written file on Windows, and bytes PIL
    could not parse were then written there verbatim. Now the type must be a
    known image format and the payload must actually decode as an image.

    Raises ValueError for anything else.
    """
    import base64
    import binascii

    if not image_data:
        raise ValueError('no image data received')

    extension = 'png'
    if image_data.startswith('data:'):
        header, sep, image_data = image_data.partition(',')
        match = re.fullmatch(r'data:image/([a-z0-9.+-]+)(;base64)?', header.strip().lower())
        if not sep or not match or not match.group(2):
            raise ValueError('expected a base64 data:image URL')
        subtype = match.group(1)
        if subtype not in PASTED_IMAGE_EXTENSIONS:
            raise ValueError(f'unsupported image type {subtype!r}')
        extension = PASTED_IMAGE_EXTENSIONS[subtype]

    try:
        binary_data = base64.b64decode(image_data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('image data is not valid base64')

    image_format(binary_data)
    return extension, binary_data


def image_format(binary_data):
    """Pillow's format name (e.g. 'PNG') for bytes that decode as an image.

    Only ALLOWED_IMAGE_FORMATS are considered. Raises ValueError for anything
    else, including decompression bombs and images over MAX_IMAGE_PIXELS.
    """
    from io import BytesIO
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(binary_data), formats=ALLOWED_IMAGE_FORMATS) as img:
            fmt = img.format
            pixels = img.width * img.height
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            ImportError) as e:
        # ImportError: once ultralytics is imported, Image.open is its wrapper,
        # which tries to import pi_heif when Pillow fails. With autoinstall off
        # (Src/ImageDetector/modified_detect_text.py) that raises
        # ModuleNotFoundError instead of UnidentifiedImageError.
        raise ValueError(f'not a readable image ({e.__class__.__name__})')
    if pixels > MAX_IMAGE_PIXELS:
        raise ValueError(f'image is too large ({pixels / 1e6:.0f} megapixels, '
                         f'limit {MAX_IMAGE_PIXELS / 1e6:.0f})')
    return fmt


def save_uploaded_image(binary_data, path_stem):
    """Validate an uploaded file and write it as `<path_stem>.<ext>`.

    Uploaded files used to be saved under the client's own file name and
    extension without any check, so anything at all could be written into
    UPLOAD_FOLDER and was then handed to OpenCV. Now the bytes must decode as
    an image; formats OpenCV reads are stored unchanged (no re-encode, so OCR
    sees the original pixels) and anything else is converted to PNG.

    Returns the path written. Raises ValueError if it is not an image.
    """
    from io import BytesIO
    from PIL import Image

    extension = CV2_READABLE_FORMATS.get(image_format(binary_data))
    if extension:
        filepath = f'{path_stem}.{extension}'
        with open(filepath, 'wb') as f:
            f.write(binary_data)
        return filepath

    filepath = f'{path_stem}.png'
    with Image.open(BytesIO(binary_data), formats=ALLOWED_IMAGE_FORMATS) as img:
        if img.mode not in ('RGB', 'RGBA', 'L'):
            img = img.convert('RGBA')
        img.save(filepath)
    return filepath


def save_pasted_image(binary_data, filepath, max_dimension=2048):
    """Write a decoded pasted image, downscaling very large ones."""
    from io import BytesIO
    from PIL import Image

    img = Image.open(BytesIO(binary_data), formats=ALLOWED_IMAGE_FORMATS)
    if img.width > max_dimension or img.height > max_dimension:
        # Preserve aspect ratio; thumbnail() never upscales.
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
        logger.info("Resized pasted image to %dx%d", img.width, img.height)
    if filepath.endswith('.jpg'):
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
    elif img.mode not in ('RGB', 'RGBA', 'L', 'P'):
        # e.g. a CMYK JPEG pasted with a data:image/png header
        img = img.convert('RGBA')
    img.save(filepath, optimize=True, quality=85)
