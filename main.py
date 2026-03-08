#!/usr/bin/env python3
"""HDRezka Downloader — скачивание фильмов и сериалов с HDRezka."""

import json
import os
import re
import sys
import time
import base64
from binascii import Error as BinasciiError
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import product
from typing import Optional, Tuple, List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from colorama import Fore, Style, init
from tqdm import tqdm

init(autoreset=True)

# ─────────────────────────── Constants ───────────────────────────
DEFAULT_SITE_URL = "https://rezka.ag"
ALT_SITE_URL = "https://standby-rezka.tv"
CONFIG_FILE = "config.json"
DOWNLOADS_DIR = "downloads"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

MAX_THREADS = 20
MAX_RETRIES = 5
RETRY_DELAY = 3
CHUNK_SIZE = 1024 * 1024  # 1 MB chunks for faster download
MAX_SEASONS_SCAN = 30
MAX_EPISODES_SCAN = 500
SIZE_TOLERANCE = 0.95

TRASH_CHARS = ["@", "#", "!", "^", "$"]
SEPARATORS = ["//_//", "////", "///"]

DEBUG = True


def debug(msg: str):
    if DEBUG:
        print(f"{Fore.MAGENTA}[DEBUG] {msg}{Style.RESET_ALL}")


# ─────────────────────────── Exceptions ──────────────────────────
class DownloaderError(Exception):
    pass

class ContentUnavailableError(DownloaderError):
    pass

class InvalidSelectionError(DownloaderError):
    pass

class StreamDecodeError(DownloaderError):
    pass

class EpisodeOutOfRangeError(DownloaderError):
    pass

class SeasonOutOfRangeError(DownloaderError):
    pass


# ─────────────────────────── Utilities ───────────────────────────
def prompt_int(message: str, min_val: int = 1, max_val: int = 100,
               default: Optional[int] = None) -> int:
    while True:
        suffix = f" [default: {default}]" if default is not None else ""
        raw = input(f"{Fore.YELLOW}{message}{suffix}: {Style.RESET_ALL}").strip()
        if not raw and default is not None:
            return default
        try:
            value = int(raw)
            if min_val <= value <= max_val:
                return value
            print(f"{Fore.RED}Enter a number between {min_val} "
                  f"and {max_val}.{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Enter a valid number.{Style.RESET_ALL}")


def prompt_choice(message: str, options: list, default: str = "") -> str:
    while True:
        raw = input(
            f"{Fore.YELLOW}{message}: {Style.RESET_ALL}"
        ).strip() or default
        if raw in options:
            return raw
        print(f"{Fore.RED}Choose one of: "
              f"{', '.join(o for o in options if o)}{Style.RESET_ALL}")


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip(". ")


def ensure_https(url: str) -> str:
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    if size_bytes <= 0:
        return "unknown size"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


# ─────────────────────── Configuration ───────────────────────────
class Config:
    def __init__(self):
        self._config: dict = {}
        self._load()
        if not self._config:
            self._setup_initial()
        self.display()

    def _load(self):
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                self._config = json.load(f)

    def _save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4, ensure_ascii=False)

    def display(self):
        print(f"{Fore.YELLOW}── Current settings ──{Style.RESET_ALL}")
        print(f"  Threads : {self._config.get('threads')}")
        print(f"  Site URL: {self._config.get('site_url')}")
        creds = self._config.get("credentials", {})
        if creds and creds.get("dle_user_id"):
            print(f"  Login   : dle_user_id="
                  f"{creds.get('dle_user_id', '?')}")

    def _ask_site_and_creds(self, current_url="", current_creds=None):
        print(f"{Fore.CYAN}1 — rezka.ag (no login){Style.RESET_ALL}")
        print(f"{Fore.CYAN}2 — standby-rezka.tv "
              f"(login required){Style.RESET_ALL}")
        print(f"{Fore.CYAN}3 — Custom URL "
              f"(login required){Style.RESET_ALL}")
        choice = prompt_choice(
            "Select site", ["1", "2", "3", ""],
            default="1" if not current_url else ""
        )
        if not choice:
            return current_url, current_creds or {}
        if choice == "1":
            return DEFAULT_SITE_URL, {}
        site_url = ALT_SITE_URL if choice == "2" else ensure_https(
            input(f"{Fore.YELLOW}Enter custom URL: {Style.RESET_ALL}")
        )
        old = current_creds or {}
        uid = input(
            f"{Fore.YELLOW}dle_user_id "
            f"[{old.get('dle_user_id', '')}]: {Style.RESET_ALL}"
        ).strip() or old.get("dle_user_id", "")
        pwd = input(
            f"{Fore.YELLOW}dle_password "
            f"[*****]: {Style.RESET_ALL}"
        ).strip() or old.get("dle_password", "")
        return site_url, {"dle_user_id": uid, "dle_password": pwd}

    def _setup_initial(self):
        print(f"{Fore.YELLOW}First-time setup:{Style.RESET_ALL}")
        threads = prompt_int(
            "Download threads (1-20)", 1, MAX_THREADS, default=10
        )
        site_url, creds = self._ask_site_and_creds()
        self._config = {
            "threads": threads,
            "site_url": site_url,
            "credentials": creds,
        }
        self._save()

    def change(self):
        threads = prompt_int(
            f"Threads (1-{MAX_THREADS}) "
            f"[current: {self._config['threads']}]",
            1, MAX_THREADS, default=self._config["threads"],
        )
        site_url, creds = self._ask_site_and_creds(
            self._config["site_url"],
            self._config.get("credentials"),
        )
        self._config.update({
            "threads": threads,
            "site_url": site_url,
            "credentials": creds,
        })
        self._save()
        self.display()

    @property
    def threads(self) -> int:
        return self._config.get("threads", 10)

    @property
    def site_url(self) -> str:
        return self._config["site_url"]

    @property
    def credentials(self) -> dict:
        return self._config.get("credentials", {})


# ─────────────────────── HTTP session ────────────────────────────
class HttpClient:
    def __init__(self, site_url: str, credentials: dict):
        self.site_url = site_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })
        if credentials:
            for key, val in credentials.items():
                if val:
                    self._session.cookies.set(
                        key, val,
                        domain=urlparse(site_url).hostname,
                    )
        self._init_session()

    def _init_session(self):
        debug(f"HttpClient._init_session() GET {self.site_url}/")
        try:
            resp = self._session.get(self.site_url + "/", timeout=15)
            debug(
                f"HttpClient._init_session() status={resp.status_code}, "
                f"cookies={dict(self._session.cookies)}"
            )
        except Exception as e:
            debug(f"HttpClient._init_session() error: {e}")

    def get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        return self._session.get(url, **kwargs)

    def get_page(self, url: str) -> requests.Response:
        """GET page — sets Referer for subsequent AJAX calls."""
        self._session.headers.update({
            "Referer": self.site_url + "/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        })
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        self._session.headers["Referer"] = url
        return resp

    def post_ajax(self, url: str, data: dict) -> requests.Response:
        """POST AJAX with browser-like headers."""
        ajax_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": (
                "application/x-www-form-urlencoded; charset=UTF-8"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": self.site_url,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        return self._session.post(
            url, data=data, headers=ajax_headers, timeout=30
        )

    def download_stream(self, url: str, dest: str):
        """Download a stream URL to file with progress bar."""
        # Use a separate session for CDN downloads to avoid header conflicts
        with requests.Session() as dl_session:
            dl_session.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "Connection": "keep-alive",
            })
            with dl_session.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))

                if total > 0:
                    print(f"{Fore.CYAN}  File size: "
                          f"{format_size(total)}{Style.RESET_ALL}")

                os.makedirs(os.path.dirname(dest), exist_ok=True)
                tmp = dest + ".part"

                try:
                    downloaded = 0
                    start_time = time.time()

                    with open(tmp, "wb") as f:
                        if total > 0:
                            with tqdm(
                                total=total,
                                unit="B",
                                unit_scale=True,
                                unit_divisor=1024,
                                desc=os.path.basename(dest),
                                ncols=80,
                                bar_format=(
                                    "{l_bar}{bar}| {n_fmt}/{total_fmt} "
                                    "[{elapsed}<{remaining}, {rate_fmt}]"
                                ),
                            ) as bar:
                                for chunk in r.iter_content(
                                    chunk_size=CHUNK_SIZE
                                ):
                                    if chunk:
                                        f.write(chunk)
                                        bar.update(len(chunk))
                                        downloaded += len(chunk)
                        else:
                            # No content-length — manual progress
                            print(f"{Fore.YELLOW}  Downloading "
                                  f"(size unknown)...{Style.RESET_ALL}")
                            for chunk in r.iter_content(
                                chunk_size=CHUNK_SIZE
                            ):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    elapsed = time.time() - start_time
                                    speed = (
                                        downloaded / elapsed
                                        if elapsed > 0 else 0
                                    )
                                    sys.stdout.write(
                                        f"\r  Downloaded: "
                                        f"{format_size(downloaded)} "
                                        f"({format_size(int(speed))}/s)"
                                    )
                                    sys.stdout.flush()
                            print()  # newline after progress

                    # Verify download
                    actual_size = os.path.getsize(tmp)
                    if total > 0 and actual_size < total * SIZE_TOLERANCE:
                        raise DownloaderError(
                            f"Incomplete: {format_size(actual_size)} / "
                            f"{format_size(total)}"
                        )

                    os.replace(tmp, dest)

                    elapsed = time.time() - start_time
                    avg_speed = downloaded / elapsed if elapsed > 0 else 0
                    print(
                        f"{Fore.GREEN}  ✓ Saved: "
                        f"{format_size(actual_size)} in "
                        f"{elapsed:.1f}s "
                        f"({format_size(int(avg_speed))}/s)"
                        f"{Style.RESET_ALL}"
                    )

                except Exception:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    raise


# ─────────────────────── Stream decoder ──────────────────────────
class StreamDecoder:
    _trash_codes: Optional[list] = None

    @classmethod
    def _build_trash_codes(cls) -> list:
        if cls._trash_codes is None:
            codes = []
            for length in range(2, 4):
                for combo in product(TRASH_CHARS, repeat=length):
                    codes.append(
                        base64.b64encode(
                            "".join(combo).encode()
                        ).decode()
                    )
            codes.sort(key=len, reverse=True)
            cls._trash_codes = codes
        return cls._trash_codes

    @classmethod
    def decode(cls, data: str) -> str:
        if not data:
            raise StreamDecodeError("Empty stream data")

        debug(f"decode() input length: {len(data)}")
        if len(data) > 200:
            debug(f"decode() first 200: {data[:200]}")
        else:
            debug(f"decode() data: {data}")

        # Already decoded?
        if data.lstrip().startswith("[") and "http" in data:
            debug("decode() → already decoded")
            return data

        # Find separator
        separator = None
        for sep in SEPARATORS:
            if sep in data:
                separator = sep
                debug(f"decode() separator: {repr(sep)}")
                break

        if separator is None:
            if "http" in data:
                debug("decode() → no sep but has http")
                return data
            raise StreamDecodeError("Unknown encoding format")

        parts = data.replace("#h", "").split(separator)
        debug(f"decode() {len(parts)} parts")
        blob = "".join(parts)

        for code in cls._build_trash_codes():
            blob = blob.replace(code, "")

        blob = re.sub(r"[^A-Za-z0-9+/=]", "", blob)
        blob += "=" * (-len(blob) % 4)

        for encoding in ("utf-8", "latin-1", "cp1251"):
            try:
                result = base64.b64decode(blob).decode(encoding)
                if "http" in result:
                    debug(f"decode() OK ({encoding})")
                    return result
            except (UnicodeDecodeError, BinasciiError):
                continue

        try:
            result = base64.b64decode(
                blob, validate=False
            ).decode("latin-1")
            return result
        except Exception as exc:
            raise StreamDecodeError(f"Cannot decode: {exc}") from exc

    @staticmethod
    def parse_qualities(decoded: str) -> List[Tuple[str, str]]:
        items = []
        for segment in decoded.split(","):
            segment = segment.strip()
            if "]" not in segment:
                continue
            pos = segment.index("]")
            label = segment[:pos + 1].strip()
            url_part = segment[pos + 1:].strip()
            if " or " in url_part:
                url_part = url_part.rsplit(" or ", 1)[-1].strip()
            if url_part and "http" in url_part:
                if ".mp4" in url_part:
                    url_part = url_part.split(".mp4")[0] + ".mp4"
                items.append((label, url_part))
        debug(f"parse_qualities() → {len(items)} items")
        return items

    @classmethod
    def select_quality(
        cls, decoded: str, preferred: str
    ) -> Tuple[str, str]:
        items = cls.parse_qualities(decoded)
        if not items:
            raise StreamDecodeError("No streams found")
        for label, url in items:
            if preferred in label:
                return label, url
        return items[-1]


# ─────────────────────── Stream fetcher ──────────────────────────
class StreamFetcher:
    def __init__(self, client: HttpClient):
        self.client = client
        self._current_page_url: Optional[str] = None
        self._page_html: str = ""

    def _ensure_page_visited(self, page_url: str):
        """Visit the content page to establish session cookies + Referer."""
        if self._current_page_url == page_url:
            return
        debug(f"_ensure_page_visited() → {page_url}")
        resp = self.client.get_page(page_url)
        self._current_page_url = page_url
        self._page_html = resp.text
        debug(f"_ensure_page_visited() HTML={len(self._page_html)}, "
              f"cookies={dict(self.client._session.cookies)}")

    def _ajax_url(self) -> str:
        t = str(time.time() * 1000)
        return f"{self.client.site_url}/ajax/get_cdn_series/?t={t}"

    def _post_ajax(self, data: dict) -> dict:
        url = self._ajax_url()
        debug(f"_post_ajax() POST {url}")
        debug(f"_post_ajax() data={data}")

        resp = self.client.post_ajax(url, data)
        debug(f"_post_ajax() status={resp.status_code}, "
              f"len={len(resp.text)}")

        try:
            result = resp.json()
        except Exception as e:
            debug(f"_post_ajax() JSON error: {e}")
            debug(f"_post_ajax() text[:500]: {resp.text[:500]}")
            raise

        success = result.get("success")
        url_val = result.get("url", "")
        debug(f"_post_ajax() success={success}, "
              f"has_url={bool(url_val)}")

        if not success:
            msg = result.get("message", "")
            debug(f"_post_ajax() message: {msg}")

        return result

    def _extract_streams_from_html(self, html: str) -> Optional[str]:
        """
        Extract encoded stream string from page HTML.
        Looks for the longest quoted string argument in initCDN*Events()
        that's likely an encoded stream.
        """
        debug("_extract_streams_from_html() searching...")

        candidates = []

        # Find all initCDN*Events calls
        for call_match in re.finditer(
            r'sof\.tv\.initCDN\w+Events\s*\(([^;]+?)\);',
            html,
            re.DOTALL,
        ):
            call_body = call_match.group(1)
            debug(f"  initCDN call body len={len(call_body)}")

            # Extract all quoted strings
            for str_match in re.finditer(
                r"""(?:'([^']{20,})'|"([^"]{20,})")""",
                call_body,
            ):
                s = str_match.group(1) or str_match.group(2)
                # Skip if it looks like a URL/domain (not encoded)
                if re.match(r'^https?://', s):
                    continue
                if len(s) < 50:
                    continue
                candidates.append(s)
                debug(f"  candidate len={len(s)}, "
                      f"first80={s[:80]}")

        # Also check for streams: 'encoded...' pattern
        for m in re.finditer(
            r"""streams\s*:\s*['"]([^'"]{100,})['"]""", html
        ):
            candidates.append(m.group(1))
            debug(f"  streams: candidate len={len(m.group(1))}")

        # Check for strings containing separators
        for sep in SEPARATORS:
            escaped = re.escape(sep)
            for m in re.finditer(
                r"""['"]([^'"]*""" + escaped + r"""[^'"]+)['"]""",
                html,
            ):
                if len(m.group(1)) > 100:
                    candidates.append(m.group(1))
                    debug(f"  sep-based candidate len={len(m.group(1))}")

        if not candidates:
            debug("  no candidates found")
            self._dump_html_debug()
            return None

        # Pick the longest candidate
        best = max(candidates, key=len)
        debug(f"  best candidate len={len(best)}")

        # Validate it looks like encoded stream
        has_sep = any(sep in best for sep in SEPARATORS)
        has_b64 = bool(re.search(r'[A-Za-z0-9+/=]{20,}', best))
        has_http = "http" in best

        debug(f"  has_sep={has_sep}, has_b64={has_b64}, "
              f"has_http={has_http}")

        if has_sep or has_b64 or has_http:
            return best

        debug("  best candidate doesn't look like stream data")
        return None

    def _dump_html_debug(self):
        """Dump diagnostic info from HTML for debugging."""
        html = self._page_html
        if not html:
            return

        debug("=== HTML diagnostics ===")
        for m in re.finditer(
            r'sof\.tv\.(initCDN\w+)\s*\(([^)]{0,300})',
            html,
        ):
            debug(f"  {m.group(1)}({m.group(2)[:200]}...)")

        for m in re.finditer(r'data-translator_id="(\d+)"', html):
            debug(f"  translator_id={m.group(1)}")

        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.select("script")
        inline = [s for s in scripts if s.string]
        for i, s in enumerate(inline):
            text = s.string.strip()
            if any(kw in text.lower() for kw in
                   ("cdn", "stream", "player", "initcdn")):
                debug(f"  script#{i} len={len(text)}: "
                      f"{text[:300]}...")

    def _get_translator_info(self, html: str) -> dict:
        info = {}
        m = re.search(
            r'sof\.tv\.initCDNMoviesEvents\s*\(\s*(\d+)\s*,\s*(\d+)',
            html,
        )
        if m:
            info["data_id"] = m.group(1)
            info["translator_id"] = m.group(2)
            info["is_movie"] = True

        m = re.search(
            r'sof\.tv\.initCDNSeriesEvents\s*\(\s*(\d+)\s*,\s*(\d+)',
            html,
        )
        if m:
            info["data_id"] = m.group(1)
            info["translator_id"] = m.group(2)
            info["is_movie"] = False

        return info

    def get_stream_url(
        self, page_url: str, data: dict,
        quality: str, is_series: bool
    ) -> str:
        """
        Get stream URL. Order:
        1. AJAX request
        2. If AJAX fails — extract from page HTML
        """
        self._ensure_page_visited(page_url)

        # === AJAX ===
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = self._post_ajax(data)
                if r.get("success") and r.get("url"):
                    debug("get_stream_url() AJAX OK")
                    decoded = StreamDecoder.decode(r["url"])
                    _, url = StreamDecoder.select_quality(
                        decoded, quality
                    )
                    return url
                else:
                    msg = r.get("message", "")
                    if "истекло" in msg or "сессии" in msg.lower():
                        debug("Session expired, re-init...")
                        self._current_page_url = None
                        self.client._init_session()
                        self._ensure_page_visited(page_url)
                        if attempt < 3:
                            time.sleep(RETRY_DELAY)
                            continue
                    break
            except Exception as e:
                debug(f"get_stream_url() AJAX err#{attempt}: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        # === HTML fallback ===
        debug("get_stream_url() → HTML fallback")
        encoded = self._extract_streams_from_html(self._page_html)
        if encoded:
            try:
                decoded = StreamDecoder.decode(encoded)
                label, url = StreamDecoder.select_quality(
                    decoded, quality
                )
                debug(f"get_stream_url() HTML OK: {label}")
                return url
            except StreamDecodeError as e:
                debug(f"get_stream_url() HTML decode fail: {e}")

        # === Alt translator ===
        info = self._get_translator_info(self._page_html)
        alt_tid = info.get("translator_id")
        if alt_tid and alt_tid != data.get("translator_id"):
            debug(f"get_stream_url() trying alt translator={alt_tid}")
            alt = dict(data)
            alt["translator_id"] = alt_tid
            try:
                r = self._post_ajax(alt)
                if r.get("success") and r.get("url"):
                    decoded = StreamDecoder.decode(r["url"])
                    _, url = StreamDecoder.select_quality(
                        decoded, quality
                    )
                    return url
            except Exception as e:
                debug(f"get_stream_url() alt fail: {e}")

        raise ContentUnavailableError(
            "Cannot get stream. Region-locked? Try VPN."
        )

    def get_available_qualities(
        self, page_url: str, data: dict, is_series: bool
    ) -> List[str]:
        """Get list of available quality labels."""
        self._ensure_page_visited(page_url)

        # AJAX
        for attempt in range(1, 3):
            try:
                r = self._post_ajax(data)
                if r.get("success") and r.get("url"):
                    decoded = StreamDecoder.decode(r["url"])
                    quals = [
                        lbl for lbl, _
                        in StreamDecoder.parse_qualities(decoded)
                    ]
                    if quals:
                        debug(f"qualities AJAX: {quals}")
                        return quals
                else:
                    msg = r.get("message", "")
                    if "истекло" in msg:
                        self._current_page_url = None
                        self.client._init_session()
                        self._ensure_page_visited(page_url)
                        time.sleep(RETRY_DELAY)
                        continue
                    break
            except Exception as e:
                debug(f"qualities AJAX err: {e}")
                break

        # HTML fallback
        debug("qualities → HTML fallback")
        encoded = self._extract_streams_from_html(self._page_html)
        if encoded:
            try:
                decoded = StreamDecoder.decode(encoded)
                quals = [
                    lbl for lbl, _
                    in StreamDecoder.parse_qualities(decoded)
                ]
                if quals:
                    debug(f"qualities HTML: {quals}")
                    return quals
            except Exception as e:
                debug(f"qualities HTML err: {e}")

        # Alt translator
        info = self._get_translator_info(self._page_html)
        alt_tid = info.get("translator_id")
        if alt_tid and alt_tid != data.get("translator_id"):
            debug(f"qualities → alt translator={alt_tid}")
            alt = dict(data)
            alt["translator_id"] = alt_tid
            try:
                r = self._post_ajax(alt)
                if r.get("success") and r.get("url"):
                    decoded = StreamDecoder.decode(r["url"])
                    quals = [
                        lbl for lbl, _
                        in StreamDecoder.parse_qualities(decoded)
                    ]
                    if quals:
                        return quals
            except Exception as e:
                debug(f"qualities alt err: {e}")

        return []

    def get_episodes_map(
        self, page_url: str, data_id: str, translator_id: str
    ) -> dict:
        """Get {season: episode_count} map for a translator."""
        self._ensure_page_visited(page_url)
        payload = {
            "id": data_id,
            "translator_id": translator_id,
            "action": "get_episodes",
        }
        try:
            r = self._post_ajax(payload)
            if r.get("success"):
                combined = (r.get("seasons", "") or "") + \
                           (r.get("episodes", "") or "")
                if combined:
                    soup = BeautifulSoup(combined, "html.parser")
                    tabs = soup.select("li[data-tab_id]")
                    if tabs:
                        eps = {}
                        for li in tabs:
                            sn = int(li.get("data-tab_id", 0))
                            if sn > 0:
                                items = soup.select(
                                    f"li[data-season_id='{sn}']"
                                )
                                eps[sn] = len(items)
                        if eps:
                            debug(f"get_episodes_map() {eps}")
                            return eps
        except Exception as e:
            debug(f"get_episodes_map() err: {e}")
        return {}

    def episode_exists(
        self, page_url: str, data_id: str,
        translator_id: str, season: int, episode: int
    ) -> bool:
        self._ensure_page_visited(page_url)
        payload = {
            "id": data_id,
            "translator_id": translator_id,
            "season": season,
            "episode": episode,
            "action": "get_stream",
        }
        try:
            r = self._post_ajax(payload)
            return bool(r.get("success") and r.get("url"))
        except Exception:
            return False

    def detect_translator_id(self, html: str) -> Optional[str]:
        for pattern in (
            r'sof\.tv\.initCDNMoviesEvents\s*\(\s*\d+\s*,\s*(\d+)',
            r'sof\.tv\.initCDNSeriesEvents\s*\(\s*\d+\s*,\s*(\d+)',
            r'data-translator_id="(\d+)"',
        ):
            m = re.search(pattern, html)
            if m:
                debug(f"detect_translator_id() → {m.group(1)}")
                return m.group(1)
        return None


# ─────────────────────── Search ──────────────────────────────────
class SearchResult:
    __slots__ = (
        "index", "name", "media_type", "year",
        "country", "genre", "data_id", "url",
    )

    def __init__(self, index, name, media_type, year,
                 country, genre, data_id, url):
        self.index = index
        self.name = name
        self.media_type = media_type
        self.year = year
        self.country = country
        self.genre = genre
        self.data_id = data_id
        self.url = url


class Search:
    def __init__(self, query: str, client: HttpClient, site_url: str):
        self._results: list = []
        self._site_url = site_url
        resp = client.get(
            f"{site_url}/search/",
            params={
                "do": "search",
                "subaction": "search",
                "q": query,
            },
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        for tag in soup.select("div.b-content__inline_item"):
            self._parse_item(tag)

    def _parse_item(self, tag):
        link_div = tag.select_one("div.b-content__inline_item-link")
        if not link_div:
            return
        a_tag = link_div.select_one("a")
        if not a_tag:
            return
        name = a_tag.text.strip()
        info_div = link_div.select_one("div")
        info_text = info_div.text if info_div else ""
        parts = [p.strip() for p in info_text.split(",")]
        year = parts[0] if parts else "?"
        country = parts[1] if len(parts) > 1 else "?"
        genre = parts[2] if len(parts) > 2 else "?"
        entity = tag.select_one("i.entity")
        media_type = entity.text.strip() if entity else "?"
        cover_a = tag.select_one(
            "div.b-content__inline_item-cover > a"
        )
        href = (
            cover_a["href"]
            if cover_a and cover_a.has_attr("href")
            else (a_tag["href"] if a_tag.has_attr("href") else "")
        )
        self._results.append(SearchResult(
            index=len(self._results) + 1,
            name=name, media_type=media_type,
            year=year, country=country, genre=genre,
            data_id=tag.get("data-id", ""), url=href,
        ))

    @property
    def results(self) -> list:
        return self._results

    def display(self):
        if not self._results:
            hint = (
                " rezka.ag may block your IP — try option 2/3."
                if self._site_url == DEFAULT_SITE_URL else ""
            )
            print(f"{Fore.RED}Nothing found.{hint}{Style.RESET_ALL}")
            return
        for r in self._results:
            print(
                f"{Fore.CYAN}{r.index} — [{r.media_type}] "
                f"{r.name} | {r.year}{Style.RESET_ALL}"
            )

    def get(self, index: int) -> SearchResult:
        if index < 1 or index > len(self._results):
            raise InvalidSelectionError(f"Invalid #{index}")
        return self._results[index - 1]


# ─────────────────────── Media info ──────────────────────────────
class MediaInfo:
    def __init__(self, result: SearchResult, client: HttpClient):
        self._result = result
        self._client = client
        self.url = result.url.split(".html")[0] + ".html"
        resp = client.get_page(self.url)
        self._html = resp.text
        self._soup = BeautifulSoup(self._html, "html.parser")
        self._data: dict = {}
        self._parse()

    def _is_movie(self) -> bool:
        return "/films/" in self.url

    def _parse(self):
        translations = self._parse_translations()
        base = {
            "name": self._result.name,
            "year": self._result.year,
            "country": self._result.country,
            "duration": self._text("td", itemprop="duration") or "?",
            "genre": [
                s.text
                for s in self._soup.find_all("span", itemprop="genre")
            ],
            "rating": self._parse_rating(),
            "translations_list": translations,
            "data-id": self._result.data_id,
            "url": self.url,
            "html": self._html,
        }
        if self._is_movie():
            base["type"] = "movie"
        else:
            base["type"] = "series"
            seasons = self._soup.select(
                "#simple-seasons-tabs > li"
            )
            base["seasons_count"] = max(len(seasons), 1)
            eps: dict = {}
            total = 0
            for i in range(1, base["seasons_count"] + 1):
                c = len(self._soup.select(
                    f"#simple-episodes-list-{i} > li"
                ))
                eps[i] = c
                total += c
            base["seasons_episodes_count"] = eps
            base["allepisodes"] = total
        self._data = base

    def _parse_translations(self) -> list:
        items = self._soup.select("ul#translators-list > li")
        if not items:
            return []
        return [
            {
                "name": li.text.strip(),
                "id": li.get("data-translator_id"),
            }
            for li in items
        ]

    def _parse_rating(self) -> dict:
        def _r(cls):
            el = self._soup.select_one(
                f"span.b-post__info_rates.{cls} > span"
            )
            return el.text.strip() if el else None
        return {"imdb": _r("imdb"), "kp": _r("kp")}

    def _text(self, tag, **attrs) -> str:
        el = self._soup.find(tag, **attrs)
        return el.text.strip() if el else ""

    @property
    def data(self) -> dict:
        return self._data

    def display(self):
        d = self._data
        kind = d["type"].capitalize()
        print(f"\n{Fore.GREEN}{kind}: {d['name']}{Style.RESET_ALL}")
        if d["type"] != "movie":
            print(f"  Seasons : {d['seasons_count']}")
            print(f"  Episodes: {d['seasons_episodes_count']}")
            print(f"  Total   : {d['allepisodes']}")
        print(f"  Year    : {d['year']}")
        print(f"  Country : {d['country']}")
        print(f"  Duration: {d['duration']}")
        print(f"  Genre   : {', '.join(d['genre'])}")
        r = d["rating"]
        if r["imdb"] or r["kp"]:
            parts = []
            if r["imdb"]:
                parts.append(f"IMDb {r['imdb']}")
            if r["kp"]:
                parts.append(f"KP {r['kp']}")
            print(f"  Rating  : {' / '.join(parts)}")
        if d["translations_list"]:
            names = ", ".join(
                t["name"] for t in d["translations_list"]
            )
            print(f"  Voices  : {names}")
        print()


# ─────────────────────── Downloader ──────────────────────────────
class Downloader:
    def __init__(self, media: dict, quality: str,
                 config: Config, client: HttpClient):
        self.media = media
        self.quality = quality
        self.config = config
        self.client = client
        self.stream = StreamFetcher(client)
        self.safe_name = sanitize_filename(media["name"])
        self.translator_id = self._choose_translation()
        if media["type"] != "movie":
            self._refresh_episode_map()

    def _choose_translation(self) -> str:
        tlist = self.media.get("translations_list") or []
        if not tlist:
            detected = self.stream.detect_translator_id(
                self.media.get("html", "")
            )
            if detected:
                print(f"{Fore.CYAN}Auto-detected translator: "
                      f"{detected}{Style.RESET_ALL}")
                return detected
            return "0"
        if len(tlist) == 1:
            print(f"{Fore.CYAN}Voice: "
                  f"{tlist[0]['name']}{Style.RESET_ALL}")
            return tlist[0]["id"]
        print(f"{Fore.YELLOW}Available voices:{Style.RESET_ALL}")
        for i, t in enumerate(tlist, 1):
            print(f"  {Fore.CYAN}{i} — {t['name']}{Style.RESET_ALL}")
        idx = prompt_int("Select voice", 1, len(tlist))
        return tlist[idx - 1]["id"]

    def _refresh_episode_map(self):
        print(f"{Fore.YELLOW}Refreshing episodes…{Style.RESET_ALL}")
        eps_map = self.stream.get_episodes_map(
            self.media["url"],
            self.media["data-id"],
            self.translator_id,
        )
        if eps_map:
            self.media["seasons_count"] = len(eps_map)
            self.media["seasons_episodes_count"] = eps_map
            self.media["allepisodes"] = sum(eps_map.values())
            print(
                f"{Fore.GREEN}{len(eps_map)} season(s), "
                f"{self.media['allepisodes']} episode(s)"
                f"{Style.RESET_ALL}"
            )
        else:
            self._probe_episodes()

    def _probe_episodes(self):
        eps_map: dict = {}
        total = 0
        did = self.media["data-id"]
        tid = self.translator_id
        purl = self.media["url"]
        for season in range(1, MAX_SEASONS_SCAN + 1):
            if not self.stream.episode_exists(
                purl, did, tid, season, 1
            ):
                break
            lo, hi, best = 1, MAX_EPISODES_SCAN, 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if self.stream.episode_exists(
                    purl, did, tid, season, mid
                ):
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            eps_map[season] = best
            total += best
        if eps_map:
            self.media["seasons_count"] = len(eps_map)
            self.media["seasons_episodes_count"] = eps_map
            self.media["allepisodes"] = total
            print(
                f"{Fore.GREEN}Probed: {len(eps_map)} season(s), "
                f"{total} episode(s){Style.RESET_ALL}"
            )

    def download_movie(self):
        dest = self._movie_path()
        if self._file_ok(dest):
            print(f"{Fore.GREEN}Already downloaded: "
                  f"{os.path.basename(dest)}{Style.RESET_ALL}")
            return

        print(f"{Fore.CYAN}Getting stream URL...{Style.RESET_ALL}")
        data = {
            "id": self.media["data-id"],
            "translator_id": self.translator_id,
            "is_camrip": 0,
            "is_ads": 0,
            "is_director": 0,
            "favs": "",
            "action": "get_movie",
        }
        url = self.stream.get_stream_url(
            self.media["url"], data, self.quality, is_series=False
        )
        print(f"{Fore.CYAN}Downloading: "
              f"{os.path.basename(dest)}{Style.RESET_ALL}")
        self.client.download_stream(url, dest)

    def download_all(self):
        for s in range(1, self.media["seasons_count"] + 1):
            self.download_season(s)

    def download_season(self, season: int):
        self._validate_season(season)
        count = self.media["seasons_episodes_count"].get(season, 0)
        print(f"{Fore.YELLOW}Season {season}: "
              f"{count} episode(s){Style.RESET_ALL}")
        self._download_eps(season, 1, count)

    def download_seasons(self, start: int, end: int):
        self._validate_season(start)
        self._validate_season(end)
        for s in range(start, end + 1):
            self.download_season(s)

    def download_episodes(self, season: int, start: int, end: int):
        self._validate_season(season)
        count = self.media["seasons_episodes_count"].get(season, 0)
        if start < 1 or end > count or start > end:
            raise EpisodeOutOfRangeError(
                f"Range {start}-{end} invalid (has {count})"
            )
        self._download_eps(season, start, end)

    def _download_eps(self, season: int, start: int, end: int):
        with ThreadPoolExecutor(
            max_workers=self.config.threads
        ) as pool:
            futures = {
                pool.submit(self._dl_episode, season, ep): ep
                for ep in range(start, end + 1)
            }
            for f in as_completed(futures):
                ep = futures[f]
                try:
                    f.result()
                except Exception as exc:
                    print(
                        f"{Fore.RED}S{season:02d}E{ep:02d} "
                        f"failed: {exc}{Style.RESET_ALL}"
                    )

    def _dl_episode(self, season: int, episode: int):
        dest = self._episode_path(season, episode)
        tag = f"S{season:02d}E{episode:02d}"
        if self._file_ok(dest):
            print(f"{Fore.GREEN}{tag} already done{Style.RESET_ALL}")
            return

        payload = {
            "id": self.media["data-id"],
            "translator_id": self.translator_id,
            "season": season,
            "episode": episode,
            "action": "get_stream",
        }
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                url = self.stream.get_stream_url(
                    self.media["url"], payload,
                    self.quality, is_series=True,
                )
                print(f"{Fore.CYAN}{tag} downloading...{Style.RESET_ALL}")
                self.client.download_stream(url, dest)
                if self._file_ok(dest):
                    print(f"{Fore.GREEN}{tag} ✓{Style.RESET_ALL}")
                    return
            except Exception as exc:
                if attempt < MAX_RETRIES:
                    print(
                        f"{Fore.YELLOW}{tag} attempt "
                        f"{attempt}: {exc}{Style.RESET_ALL}"
                    )
                    time.sleep(RETRY_DELAY)
                else:
                    raise

    def _base_dir(self) -> str:
        return os.path.join(DOWNLOADS_DIR, self.safe_name)

    def _episode_path(self, season: int, episode: int) -> str:
        return os.path.join(
            self._base_dir(),
            f"s{season:02d}e{episode:02d}-{self.quality}.mp4",
        )

    def _movie_path(self) -> str:
        return os.path.join(
            self._base_dir(),
            f"{self.safe_name}-{self.quality}.mp4",
        )

    @staticmethod
    def _file_ok(path: str) -> bool:
        return os.path.isfile(path) and os.path.getsize(path) > 0

    def _validate_season(self, season: int):
        if season < 1 or season > self.media["seasons_count"]:
            raise SeasonOutOfRangeError(
                f"Season {season} not in "
                f"1–{self.media['seasons_count']}"
            )


# ─────────────────────── Main ────────────────────────────────────
def main():
    config = Config()

    while True:
        query = input(
            f"\n{Fore.YELLOW}Search title "
            f"(or '1' for settings, 'q' to quit): "
            f"{Style.RESET_ALL}"
        ).strip()

        if query.lower() == "q":
            print(f"{Fore.CYAN}Bye!{Style.RESET_ALL}")
            return
        if query == "1":
            config.change()
            continue
        if not query:
            continue

        client = HttpClient(config.site_url, config.credentials)
        search = Search(query, client, config.site_url)
        search.display()
        if not search.results:
            continue

        title_idx = prompt_int(
            "Select title #", 1, len(search.results)
        )
        result = search.get(title_idx)

        info = MediaInfo(result, client)
        info.display()
        media = info.data

        # ── Quality selection ──
        stream = StreamFetcher(client)
        is_series = media["type"] != "movie"

        first_tid = (
            media["translations_list"][0]["id"]
            if media["translations_list"]
            else stream.detect_translator_id(
                media.get("html", "")
            ) or "0"
        )

        debug(f"data-id={media['data-id']}, "
              f"translator={first_tid}, series={is_series}")

        probe: dict = {
            "id": media["data-id"],
            "translator_id": first_tid,
        }
        if is_series:
            probe.update({
                "season": 1, "episode": 1,
                "action": "get_stream",
            })
        else:
            probe.update({
                "is_camrip": 0, "is_ads": 0,
                "is_director": 0, "favs": "",
                "action": "get_movie",
            })

        qualities = stream.get_available_qualities(
            media["url"], probe, is_series
        )
        if not qualities:
            print(f"{Fore.RED}No qualities found. "
                  f"Try different voice or VPN.{Style.RESET_ALL}")
            continue

        print(f"{Fore.YELLOW}Available qualities:{Style.RESET_ALL}")
        for i, q in enumerate(qualities, 1):
            print(f"  {Fore.CYAN}{i} — {q}{Style.RESET_ALL}")
        q_idx = prompt_int("Select quality #", 1, len(qualities))
        quality = qualities[q_idx - 1].strip("[]")

        dl = Downloader(media, quality, config, client)

        if media["type"] == "movie":
            dl.download_movie()
            print(f"\n{Fore.GREEN}✓ Movie download "
                  f"complete!{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}Download options:{Style.RESET_ALL}")
            print("  1 — Single season")
            print("  2 — Episode range")
            print("  3 — Season range")
            print("  4 — Entire series")
            choice = prompt_int("Option", 1, 4)

            sc = media["seasons_count"]

            if choice == 1:
                s = prompt_int(f"Season (1–{sc})", 1, sc)
                dl.download_season(s)
            elif choice == 2:
                s = prompt_int(f"Season (1–{sc})", 1, sc)
                ec = media["seasons_episodes_count"].get(s, 0)
                print(f"{Fore.CYAN}Season {s}: "
                      f"{ec} episode(s){Style.RESET_ALL}")
                e1 = prompt_int("Start episode", 1, ec)
                e2 = prompt_int("End episode", e1, ec)
                dl.download_episodes(s, e1, e2)
            elif choice == 3:
                s1 = prompt_int(f"Start season (1–{sc})", 1, sc)
                s2 = prompt_int(
                    f"End season ({s1}–{sc})", s1, sc
                )
                dl.download_seasons(s1, s2)
            elif choice == 4:
                dl.download_all()

            print(f"\n{Fore.GREEN}✓ Download "
                  f"complete!{Style.RESET_ALL}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Interrupted.{Style.RESET_ALL}")
        sys.exit(0)
    except Exception as exc:
        print(f"{Fore.RED}Fatal: {exc}{Style.RESET_ALL}")
        if DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(1)
