import io
import uuid
import warnings

from PIL import Image, UnidentifiedImageError

from config import UPLOAD_DIR

MAX_SIDE = 800  # px по большей стороне
MAX_PIXELS = 16_000_000
PUBLIC_PREFIX = "/api/media"


class InvalidImage(Exception):
    pass


def save_image(raw: bytes) -> str:
    """Проверяет, что это картинка, ужимает и сохраняет как JPEG.

    Возвращает публичный URL вида /api/media/<uuid>.jpg
    """
    try:
        # verify() «расходует» файл, поэтому потом открываем заново.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.width * probe.height > MAX_PIXELS:
                    raise InvalidImage("Слишком высокое разрешение фото. Выбери изображение поменьше.")
                if probe.format not in {"JPEG", "PNG", "WEBP"}:
                    raise InvalidImage("Подойдут JPG, PNG или WebP.")
                probe.verify()
            with Image.open(io.BytesIO(raw)) as source:
                img = source.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise InvalidImage("Файл не похож на изображение")

    img.thumbnail((MAX_SIDE, MAX_SIDE))

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    img.save(UPLOAD_DIR / name, format="JPEG", quality=85, optimize=True)
    return f"{PUBLIC_PREFIX}/{name}"
