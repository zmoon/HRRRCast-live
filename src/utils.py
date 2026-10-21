import logging
import os
import shutil
from datetime import datetime
from dateutil import parser
from typing import Optional, Tuple, Union
from pathlib import Path
import requests
import time

# Retry / download defaults (can be overridden in callers)
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 2  # seconds
DEFAULT_TIMEOUT = 300    # seconds
DEFAULT_LOCK_POLL_SECONDS = 5
DEFAULT_STALE_LOCK_SECONDS = 6 * 3600

INPUT_CACHE_ENABLED_ENV = "HRRRCAST_USE_INPUT_CACHE"
INPUT_CACHE_ROOT_ENV = "HRRRCAST_INPUT_CACHE_ROOT"
_INPUT_CACHE_LOGGED = False


def validate_datetime(datetime_str: str) -> Tuple[object, str, str, str, str]:
    """Validate and format any datetime string that Python can parse.
    Returns (datetime_object, year, month, day, hour) as strings with proper padding.
    Raises ValueError if parsing fails.
    """
    try:
        dt = parser.parse(datetime_str)
        year = f"{dt.year:04d}"
        month = f"{dt.month:02d}"
        day = f"{dt.day:02d}"
        hour = f"{dt.hour:02d}"
        return dt, year, month, day, hour
    except (ValueError, TypeError, parser.ParserError) as e:
        logging.error(f"Invalid date/time: {e}")
        raise ValueError(f"Invalid date/time: {e}")

def make_directory(path: Union[str, Path]) -> None:
    """
    Create a directory (and any necessary parent directories).
    Accepts either a string or Path object. Does nothing if the directory already exists.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True) 

def setup_logging(log_level: str = 'INFO') -> logging.Logger:
    """Configure root logging (idempotent across modules)."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)

def create_output_directory(base_dir: str, date_str: str) -> Path:
    """Create and return an output directory base_dir/date_str."""
    out = Path(base_dir) / date_str
    make_directory(out)
    return out

def download_file_with_retry(url: str, output_path: Union[str, Path], max_retries: int = DEFAULT_MAX_RETRIES,
                              retry_delay: int = DEFAULT_RETRY_DELAY, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Download a file with retries and basic progress logging.

    Args:
        url: Source URL
        output_path: Destination path
        max_retries: Attempts before failing
        retry_delay: Delay between attempts (s)
        timeout: Per-request timeout (s)
    Returns:
        True on success, False on failure.
    """
    logger = logging.getLogger(__name__)
    output_path = Path(output_path)
    for attempt in range(max_retries):
        try:
            logger.info(f"Downloading {url} (attempt {attempt+1}/{max_retries})")
            resp = requests.get(url, stream=True, timeout=timeout)
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            with open(output_path, 'wb') as f:
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        if total:
                            downloaded += len(chunk)
                            if downloaded % max((total // 10), 1) == 0:
                                logger.info(f"Progress: {(downloaded/total)*100:.1f}%")
            logger.info(f"Downloaded {output_path.name}")
            return True
        except requests.exceptions.RequestException as e:
            logger.warning(f"Download failed ({attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to download {url} after {max_retries} attempts")
                return False
        except Exception as e:
            logger.error(f"Unexpected error downloading {url}: {e}")
            return False
    return False


def add_nc_compression(encoding: dict, ds, complevel: int = 3) -> dict:
    """Add lossless zlib compression to the NetCDF encoding of numeric, non-scalar data variables."""
    for vn in ds.data_vars:
        da = ds[vn]
        if da.ndim > 0 and da.dtype.kind in "biuf":
            encoding.setdefault(vn, {}).update(zlib=True, complevel=complevel)
    return encoding


def env_flag(name: str, default: bool) -> bool:
    """Parse an environment variable into a Boolean with a fallback default."""
    value = os.getenv(name)
    if value is None:
        return default

    value = value.strip().lower()

    if value in {"1", "true", "t", "yes", "y", "on"}:
        return True
    elif value in {"0", "false", "f", "no", "n", "off"}:
        return False
    else:
        logging.warning(
            f"Unrecognized value for {name}={value!r}; falling back to default={default}."
        )
        return default


def use_input_cache() -> bool:
    """Return whether the shared raw-input cache is enabled."""
    return env_flag(INPUT_CACHE_ENABLED_ENV, False)


def get_input_cache_root() -> Optional[Path]:
    """Return configured shared raw-input cache root, validating required state."""
    if not use_input_cache():
        return None

    cache_root = os.getenv(INPUT_CACHE_ROOT_ENV, "").strip()
    if not cache_root:
        raise ValueError(
            f"{INPUT_CACHE_ROOT_ENV} must be set when {INPUT_CACHE_ENABLED_ENV} is enabled"
        )

    cache_root_path = Path(cache_root)
    make_directory(cache_root_path)
    return cache_root_path


def is_valid_file(path: Union[str, Path]) -> bool:
    """Return True when a file exists and is non-empty."""
    p = Path(path)
    return p.is_file() and p.stat().st_size > 0


def _cache_path_for_target(cache_root: Path, output_path: Path) -> Path:
    """Map a requested output file to its shared cache object path.

    Cache identity is based on the local output filename (`output_path.name`).
    This is an intentional, minimal-intrusion strategy and does not detect
    when different source objects (or changed source content) are mapped to
    the same local filename.
    """
    return cache_root / output_path.name


def _lock_path_for_cache(cache_path: Path) -> Path:
    return cache_path.with_name(f"{cache_path.name}.lock")


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _materialize_local_file(cache_path: Path, output_path: Path) -> None:
    """Create the run-local file from cache using hardlink first, copy fallback second."""
    make_directory(output_path.parent)

    if output_path.exists():
        if is_valid_file(output_path):
            return
        _remove_if_exists(output_path)

    try:
        os.link(cache_path, output_path)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            f"Hardlink failed for {output_path} from cache {cache_path}: {exc}; falling back to copy"
        )
        shutil.copy2(cache_path, output_path)


def _acquire_lock(lock_path: Path, stale_lock_seconds: int, poll_seconds: int) -> bool:
    """Acquire a lock directory, waiting until the active owner finishes or the lock is stale."""
    logger = logging.getLogger(__name__)
    while True:
        try:
            lock_path.mkdir()
            return True
        except FileExistsError:
            try:
                age_seconds = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue

            if age_seconds > stale_lock_seconds:
                logger.warning(f"Removing stale cache lock {lock_path} (age {age_seconds:.0f}s)")
                try:
                    lock_path.rmdir()
                    continue
                except OSError:
                    logger.debug(f"Unable to remove stale lock immediately: {lock_path}")

            logger.info(f"Waiting for cache lock: {lock_path}")
            time.sleep(poll_seconds)


def ensure_file_from_url(
    url: str,
    output_path: Union[str, Path],
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: int = DEFAULT_RETRY_DELAY,
    timeout: int = DEFAULT_TIMEOUT,
    poll_seconds: int = DEFAULT_LOCK_POLL_SECONDS,
    stale_lock_seconds: int = DEFAULT_STALE_LOCK_SECONDS,
) -> bool:
    """Ensure an output file exists, optionally via shared cache-backed download.

    When input caching is disabled, this falls back to direct download behavior.
    When enabled, it downloads into the shared cache with a per-object lock and
    materializes the requested local file from the cache.

    The shared cache key is filename-based (via `_cache_path_for_target`), so
    stale cache reuse is possible whenever different source content is reused
    under the same local filename, regardless of URL stability.
    """
    logger = logging.getLogger(__name__)
    output_path = Path(output_path)
    global _INPUT_CACHE_LOGGED

    if not use_input_cache():
        return download_file_with_retry(
            url,
            output_path,
            max_retries=max_retries,
            retry_delay=retry_delay,
            timeout=timeout,
        )

    # In cache-enabled mode, this either returns a valid path
    # or raises ValueError when HRRRCAST_INPUT_CACHE_ROOT is unset.
    cache_root = get_input_cache_root()

    if not _INPUT_CACHE_LOGGED:
        logger.info(f"Shared input cache enabled: {cache_root}")
        _INPUT_CACHE_LOGGED = True

    cache_path = _cache_path_for_target(cache_root, output_path)
    lock_path = _lock_path_for_cache(cache_path)

    if is_valid_file(cache_path):
        logger.info(f"Input cache hit: {cache_path.name}")
        _materialize_local_file(cache_path, output_path)
        return True

    _acquire_lock(lock_path, stale_lock_seconds=stale_lock_seconds, poll_seconds=poll_seconds)
    try:
        if not is_valid_file(cache_path):
            make_directory(cache_path.parent)
            temp_path = cache_path.with_name(
                f"{cache_path.name}.tmp.{os.getpid()}.{time.time_ns()}"
            )
            logger.info(f"Input cache miss: downloading {cache_path.name} into shared cache")
            try:
                ok = download_file_with_retry(
                    url,
                    temp_path,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    timeout=timeout,
                )
                if not ok or not is_valid_file(temp_path):
                    _remove_if_exists(temp_path)
                    return False

                with open(temp_path, 'rb') as temp_file:
                    os.fsync(temp_file.fileno())

                os.replace(temp_path, cache_path)
                logger.info(f"Cached shared input: {cache_path}")
            finally:
                _remove_if_exists(temp_path)
        else:
            logger.info(f"Input cache became available while waiting: {cache_path.name}")
    finally:
        try:
            lock_path.rmdir()
        except OSError:
            logger.debug(f"Cache lock cleanup skipped: {lock_path}")

    _materialize_local_file(cache_path, output_path)
    return True
