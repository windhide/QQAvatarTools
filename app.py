#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NTQQ 高精度/透明头像上传工具
本地编辑器 + NapCat HTTP 桥接（set_qq_avatar -> NodeIKernelProfileService.setHeader）
仅依赖 Pillow：pip install pillow
"""
import json
import os
import re
import sys
import uuid
import base64
import ctypes
import hashlib
import io
import secrets
import subprocess
import threading
import webbrowser
import zipfile
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    print("缺少 Pillow，请先运行: pip install pillow")
    sys.exit(1)

try:
    import qrcode as _qrcode
except ImportError:
    _qrcode = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# PyInstaller 冻结后：资源在 _MEIPASS 解包目录，可写文件（config/uploads）放 exe 旁
if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "static"
    DATA_DIR = Path(sys.executable).resolve().parent
else:
    RESOURCE_DIR = Path(__file__).resolve().parent / "static"
    DATA_DIR = Path(__file__).resolve().parent
STATIC_DIR = RESOURCE_DIR
UPLOAD_DIR = DATA_DIR / "uploads"
CONFIG_PATH = DATA_DIR / "config.json"
PORT = 17860

# 旧协议与 NTQQ 的通行限制：3 MiB / 4096px，超限自动按比例缩小
MAX_BYTES = 3 * 1024 * 1024
MAX_DIM = 4096
MIN_DIM = 320

# 内置 NapCat（Shell 模式）
NAPCAT_DIR = DATA_DIR / "napcat"
BOOT_LOG = DATA_DIR / "napcat_boot.log"
BOOT_PID_FILE = DATA_DIR / "napcat.pid"
ONEBOT_PORT = 6090      # NapCat 对本工具开放的 OneBot HTTP
WEBUI_PORT = 6099       # NapCat 自带 WebUI（用于扫码/快速登录）

DEFAULT_CONFIG = {
    "napcat_url": "http://127.0.0.1:3000",   # 外置 NapCat（高级）
    "token": "",
    "internal_token": "",
    "webui_token": "",
}


class ToolError(Exception):
    pass


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text("utf-8"))
            loaded.pop("auto_login_uin", None)  # 已废弃：不再自动登录
            cfg.update(loaded)
        except Exception:
            pass
    dirty = False
    for key in ("internal_token", "webui_token"):
        if not cfg.get(key):
            cfg[key] = secrets.token_hex(12)
            dirty = True
    if dirty:
        save_config(cfg)
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(
        json.dumps({k: cfg.get(k, DEFAULT_CONFIG[k]) for k in DEFAULT_CONFIG},
                   ensure_ascii=False, indent=2),
        "utf-8")


class NapCatClient:
    def __init__(self, base_url, token):
        base = (base_url or "").strip()
        if not re.match(r"^https?://", base):
            raise ToolError("NapCat 地址需以 http:// 或 https:// 开头")
        self.base = base.rstrip("/")
        self.token = (token or "").strip()

    def call(self, action, params, timeout=90):
        url = f"{self.base}/{action}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(
            url, data=json.dumps(params).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise ToolError(f"NapCat HTTP {e.code}：{body or e.reason}")
        except urllib.error.URLError as e:
            raise ToolError(f"无法连接 NapCat（{e.reason}）。请确认 NapCat 已登录并在网络配置中开启了 HTTP 服务器。")
        except json.JSONDecodeError:
            raise ToolError("NapCat 返回了无法解析的内容，请检查地址是否指向 OneBot HTTP 服务端口")

    def login_info(self, timeout=8):
        return self.call("get_login_info", {}, timeout=timeout)

    def set_avatar(self, file_path):
        return self.call("set_qq_avatar", {"file": str(file_path)})


# ---------- 内置 NapCat（Shell）：零安装，用本机已装的 QQ ----------

_boot_proc = None


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def payload_zip_path():
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "."))
        for name in ("napcat_shell.zip", "napcat_payload.zip"):
            p = base / name
            if p.exists():
                return p
        return base / "napcat_shell.zip"
    return Path(__file__).resolve().parent / "payload" / "napcat_shell.zip"


def ensure_payload():
    boot_exe = NAPCAT_DIR / "NapCatWinBootMain.exe"
    marker = NAPCAT_DIR / ".payload_ok"
    if marker.exists() and boot_exe.exists():
        return
    z = payload_zip_path()
    if not z.exists():
        raise ToolError("内置 NapCat 载荷缺失（打包异常），请重新获取完整程序")
    NAPCAT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(NAPCAT_DIR)
    if not boot_exe.exists():
        raise ToolError("内置 NapCat 载荷不完整")
    marker.write_text(str(z.stat().st_size), "utf-8")


def find_qq_exe():
    import winreg
    candidates = []
    for root_path in (
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path) as k:
                val, _ = winreg.QueryValueEx(k, "UninstallString")
            p = Path(val.strip('"'))
            candidates.append(p.parent / "QQ.exe")
        except OSError:
            continue
    env_pf = [
        Path(r"C:\Program Files\Tencent\QQNT\QQ.exe"),
        Path(r"C:\Program Files (x86)\Tencent\QQNT\QQ.exe"),
    ]
    for c in candidates + env_pf:
        if c.exists():
            return c
    return None


def write_napcat_config(cfg):
    cdir = NAPCAT_DIR / "config"
    cdir.mkdir(parents=True, exist_ok=True)
    webui = {
        "host": "127.0.0.1", "port": WEBUI_PORT, "token": cfg["webui_token"],
        # autoLoginAccount 固定为空：每次打开都必须扫码，绝不沿用上次登录
        "loginRate": 10, "autoLoginAccount": "",
        # 注意：v4.18.42 的 theme 是对象类型，写字符串会导致整个配置校验失败，
        # NapCat 会丢弃文件并随机生成 token；此处省略 theme 让其取默认值
        "disableWebUI": False, "accessControlMode": "none",
        "ipWhitelist": [], "ipBlacklist": [], "enableXForwardedFor": False,
        "enable2FA": False, "totpSecret": "",
    }
    (cdir / "webui.json").write_text(json.dumps(webui, indent=4), "utf-8")
    ob11 = {
        "network": {
            "httpServers": [{
                "name": "nt-avatar-tool", "enable": True, "port": ONEBOT_PORT,
                "host": "127.0.0.1", "enableCors": True, "enableWebsocket": False,
                "messagePostFormat": "array", "token": cfg["internal_token"],
                "debug": False,
            }],
            "httpSseServers": [], "httpClients": [], "websocketServers": [],
            "websocketClients": [], "plugins": [],
        },
        "musicSignUrl": "", "enableLocalFile2Url": False, "parseMultMsg": False,
        "imageDownloadProxy": "",
        "timeout": {"baseTimeout": 10000, "uploadSpeedKBps": 256,
                    "downloadSpeedKBps": 256, "maxTimeout": 1800000},
    }
    (cdir / "onebot11.json").write_text(json.dumps(ob11, indent=4), "utf-8")


def _pid_alive(pid):
    if not pid:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == 259  # STILL_ACTIVE
        return False
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def _read_boot_pid():
    try:
        return int(BOOT_PID_FILE.read_text("utf-8").strip())
    except Exception:
        return None


def _tcp_open(port, timeout=1.0):
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def boot_alive():
    global _boot_proc
    if _boot_proc is not None:
        return _boot_proc.poll() is None
    if _pid_alive(_read_boot_pid()):
        return True
    # 记录的进程已退出但服务仍在（工具重启/提权后收养遗留实例）
    return _tcp_open(WEBUI_PORT) or _tcp_open(ONEBOT_PORT)


def start_builtin():
    global _boot_proc
    if boot_alive():
        raise ToolError("内置 QQ 已在运行，无需重复启动；若要重来请先点「停止」")
    ensure_payload()
    qq = find_qq_exe()
    if not qq:
        raise ToolError("未找到已安装的新版 QQ（NTQQ）。请先安装 QQ 桌面版后再使用本工具。")
    cfg = load_config()
    write_napcat_config(cfg)

    exe = NAPCAT_DIR / "NapCatWinBootMain.exe"
    dll = NAPCAT_DIR / "NapCatWinBootHook.dll"
    env = {**os.environ,
           "NAPCAT_PATCH_PACKAGE": str(NAPCAT_DIR / "qqnt.json"),
           "NAPCAT_LOAD_PATH": str(NAPCAT_DIR / "loadNapCat.js"),
           "NAPCAT_INJECT_PATH": str(dll),
           "NAPCAT_LAUNCHER_PATH": str(exe),
           "NAPCAT_MAIN_PATH": str(NAPCAT_DIR / "napcat.mjs")}
    # 注意：不传第三个 uin 参数 —— 传了 NapCat 会用上次会话自动快速登录，
    # 用户要求每次打开都必须重新扫码
    args = [str(exe), str(qq), str(dll)]
    BOOT_LOG.parent.mkdir(exist_ok=True)
    logf = open(BOOT_LOG, "ab")
    proc = subprocess.Popen(
        args, cwd=str(NAPCAT_DIR), env=env,
        stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    _boot_proc = proc
    _boot_spawned["on"] = True
    _spawn_exit_watcher()
    BOOT_PID_FILE.write_text(str(proc.pid), "utf-8")
    return proc.pid


# 单行、自包含语句：既可直接写入 ps1 文件（-File），也可内嵌 -Command，
# 不能出现跨行管道，否则拼接成单行时会产生“空管道元素”语法错误
STOP_SWEEP_PS1 = (
    "Get-CimInstance Win32_Process -Filter \"Name='NapCatWinBootMain.exe'\" | "
    "ForEach-Object { & taskkill /PID $_.ProcessId /T /F | Out-Null }; "
    "Get-CimInstance Win32_Process -Filter \"Name='QQ.exe'\" | "
    "ForEach-Object { & taskkill /PID $_.ProcessId /T /F | Out-Null }"
)


def _sweep_qq():
    # 与 NapCat 官方 KillQQ.bat 同策略：结束所有 QQ 进程，
    # 防止无头实例残留占用 6099 端口导致后续启动端口漂移
    ps1 = DATA_DIR / "stop_sweep.ps1"
    ps1.write_text(STOP_SWEEP_PS1, "utf-8")
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, timeout=30)
    except Exception:
        pass
    try:
        (NAPCAT_DIR / "cache" / "qrcode.png").unlink(missing_ok=True)
    except Exception:
        pass


def stop_builtin():
    global _boot_proc
    if _boot_proc is not None and _boot_proc.poll() is None:
        _boot_proc.terminate()
    _boot_proc = None
    _sweep_qq()
    BOOT_PID_FILE.unlink(missing_ok=True)


# ---- 退出清理：关闭工具时结束本次拉起的隐藏 QQ，还原干净状态 ----

_boot_spawned = {"on": False}
_exit_cleaned = {"on": False}
_watcher_spawned = {"on": False}


def _cleanup_on_exit():
    if _exit_cleaned["on"]:
        return
    _exit_cleaned["on"] = True
    if not _boot_spawned["on"]:
        return
    try:
        if _boot_proc is not None and _boot_proc.poll() is None:
            _boot_proc.terminate()
    except Exception:
        pass
    _sweep_qq()
    BOOT_PID_FILE.unlink(missing_ok=True)


def _spawn_exit_watcher():
    # 看门狗：独立 PowerShell 进程盯住本进程，无论本进程以何种方式退出
    # （关窗口 / Ctrl+C / 崩溃 / 任务管理器强杀），都会清扫所有 QQ 进程。
    # atexit / 控制台事件只能覆盖优雅退出，强杀只有这条路能兜底。
    if _watcher_spawned["on"] or os.name != "nt":
        return
    _watcher_spawned["on"] = True
    mypid = os.getpid()
    ps = (
        f"$p = Get-Process -Id {mypid} -ErrorAction SilentlyContinue; "
        f"if ($p) {{ Wait-Process -Id {mypid} -ErrorAction SilentlyContinue }}; "
        + STOP_SWEEP_PS1
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", ps],
        creationflags=subprocess.CREATE_NO_WINDOW)


def install_exit_cleanup():
    import atexit
    import signal
    atexit.register(_cleanup_on_exit)

    def _term(sig, frame):
        _cleanup_on_exit()
        sys.exit(0)
    try:
        signal.signal(signal.SIGTERM, _term)
    except Exception:
        pass

    # 关闭控制台窗口 / 注销 / 关机时 atexit 不会执行，需要系统回调
    if os.name == "nt":
        import ctypes
        handler = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

        def _ctrl(evt):  # 2=CTRL_CLOSE 5=LOGOFF 6=SHUTDOWN
            if evt in (2, 5, 6):
                _cleanup_on_exit()
            return False
        _CTRL_HANDLER = handler(_ctrl)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_CTRL_HANDLER, 1)


# ---- NapCat WebUI 客户端（登录二维码 / 快速登录） ----
# 凭证缓存 1 小时有效；WebUI 登录接口限流 10 次/60 秒，绝不能每次轮询都登录

_webui_cred = {"cred": None}


def _webui_request(cfg, path, body=None, cred=None, timeout=6):
    url = f"http://127.0.0.1:{WEBUI_PORT}{path}"
    headers = {"Content-Type": "application/json"}
    if cred:
        headers["Authorization"] = f"Bearer {cred}"
    req = urllib.request.Request(url, data=json.dumps(body or {}).encode("utf-8"),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def webui_credential(cfg):
    if _webui_cred["cred"]:
        return _webui_cred["cred"]
    h = hashlib.sha256((cfg["webui_token"] + ".napcat").encode("utf-8")).hexdigest()
    res = _webui_request(cfg, "/api/auth/login", {"hash": h})
    cred = (res.get("data") or {}).get("Credential")
    if res.get("code") == 0 and cred:
        _webui_cred["cred"] = cred
        return cred
    raise ToolError(f"WebUI 认证失败：{res.get('message')}")


def _webui_call(cfg, path, body=None, timeout=6, _retry=True):
    cred = webui_credential(cfg)
    try:
        return _webui_request(cfg, path, body, cred=cred, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and _retry:
            _webui_cred["cred"] = None
            return _webui_call(cfg, path, body, timeout, _retry=False)
        raise


def builtin_status():
    cfg = load_config()
    payload_err = ""
    try:
        ensure_payload()
    except ToolError as e:
        payload_err = str(e)
    st = {
        "payload_zip": payload_zip_path().exists(),
        "payload_ready": (NAPCAT_DIR / ".payload_ok").exists(),
        "payload_error": payload_err,
        "qq_exe": str(find_qq_exe()) if find_qq_exe() else None,
        "admin": is_admin(),
        "boot_alive": boot_alive(),
        "webui_up": False,
        "logged_in": False,
        "login": None,
        "login_phase": "",
        "qr_png": None,
        "quick_list": [],
    }
    if not st["boot_alive"]:
        return st

    # OneBot 通道：登录即通
    try:
        client = NapCatClient(f"http://127.0.0.1:{ONEBOT_PORT}", cfg["internal_token"])
        s = napcat_result_summary(client.login_info(timeout=4))
        if s["ok"] and isinstance(s["data"], dict):
            st["logged_in"] = True
            st["login"] = s["data"]
            return st
    except ToolError:
        pass
    except Exception:
        pass

    # 未登录：经 WebUI 提供二维码/快速登录
    try:
        st["webui_up"] = True
        res = _webui_call(cfg, "/api/QQLogin/CheckLoginStatus")
        d = res.get("data") or {}
        st["login_phase"] = d.get("loginPhase", "")
        if d.get("qrcodeurl") and _qrcode is not None:
            img = _qrcode.make(d["qrcodeurl"])
            buf = io.BytesIO()
            img.save(buf, "PNG")
            st["qr_png"] = base64.b64encode(buf.getvalue()).decode("ascii")
        try:
            ql = _webui_call(cfg, "/api/QQLogin/GetQuickLoginList")
            st["quick_list"] = ql.get("data") or []
        except Exception:
            pass
    except ToolError:
        st["webui_up"] = False
    except Exception:
        st["webui_up"] = False
    return st


def builtin_quick_login(uin):
    cfg = load_config()
    res = _webui_call(cfg, "/api/QQLogin/SetQuickLogin", {"uin": str(uin)})
    if res.get("code") != 0:
        raise ToolError(f"快速登录失败：{res.get('message')}")


def builtin_qr_refresh():
    cfg = load_config()
    res = _webui_call(cfg, "/api/QQLogin/RefreshQRcode")
    if res.get("code") != 0:
        raise ToolError(f"刷新二维码失败：{res.get('message')}")


# ---------- 图片管线：按源图原始像素裁剪，输出无损 PNG（保留透明通道） ----------

def inspect_image(path):
    # 从内存打开：异常路径下不持有文件句柄，Windows 上才能可靠清理
    import io
    try:
        im = Image.open(io.BytesIO(path.read_bytes()))
    except Exception:
        raise ToolError("不是可识别的图片文件")
    if getattr(im, "is_animated", False):
        raise ToolError("暂不支持动图。NTQQ 上传通道不支持动态头像（电脑端不播放动画，"
                        "动态图层需旧协议 + 小世界，本工具不涉及）")
    fmt = (im.format or "").upper()
    if fmt not in ("PNG", "JPEG", "WEBP", "BMP"):
        raise ToolError(f"不支持的格式：{fmt or '未知'}（支持 PNG / JPG / WebP / BMP）")
    im.load()
    return {
        "format": fmt,
        "width": im.width,
        "height": im.height,
        "has_alpha": bool(
            im.mode in ("RGBA", "LA")
            or (im.mode == "P" and "transparency" in im.info)
        ),
    }


def render_avatar(src_path, x, y, size, angle=0.0, flip_h=False, flip_v=False):
    import io
    im = Image.open(io.BytesIO(src_path.read_bytes()))
    im = ImageOps.exif_transpose(im)
    if im.mode == "P" and "transparency" in im.info:
        im = im.convert("RGBA")
    elif im.mode not in ("RGBA", "RGB"):
        im = im.convert("RGBA" if "A" in im.getbands() or im.mode in ("LA", "PA") else "RGB")

    size = max(16, int(size))
    x, y = int(x), int(y)
    pad = x < 0 or y < 0 or x + size > im.width or y + size > im.height
    if flip_h:
        im = ImageOps.mirror(im)
    if flip_v:
        im = ImageOps.flip(im)
    if angle:
        # 浏览器画布正角=顺时针（y 向下），Pillow 正角=逆时针，取负保持一致；
        # 旋转扩边后必然产生空白，统一透明填充
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        im = im.rotate(-float(angle), Image.BICUBIC,
                       expand=True, fillcolor=(0, 0, 0, 0))
        # 扩边后的实际尺寸以服务端为准，裁剪坐标按它钳制
        x = max(-size, min(x, im.width))
        y = max(-size, min(y, im.height))
        pad = pad or x < 0 or y < 0 or x + size > im.width or y + size > im.height

    out_size = min(size, MAX_DIM)
    k = out_size / size  # 源坐标 → 输出坐标
    if not pad and out_size == size:
        out = im.crop((x, y, x + size, y + size))
    else:
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        out = Image.new("RGBA", (out_size, out_size), (0, 0, 0, 0))
        ix0, iy0 = max(0, x), max(0, y)
        ix1, iy1 = min(im.width, x + size), min(im.height, y + size)
        if ix1 > ix0 and iy1 > iy0:
            region = im.crop((ix0, iy0, ix1, iy1))
            tw = max(1, round((ix1 - ix0) * k))
            th = max(1, round((iy1 - iy0) * k))
            if (tw, th) != region.size:
                region = region.resize((tw, th), Image.LANCZOS)
            out.paste(region, (round((ix0 - x) * k), round((iy0 - y) * k)))

    # 无损 PNG；若超 3MiB 逐步缩小（保精度优先，只在必要时牺牲）
    scale = 1.0
    while True:
        buf = io.BytesIO()
        frame = out if scale == 1.0 else out.resize(
            (max(1, round(out.width * scale)), max(1, round(out.height * scale))),
            Image.LANCZOS)
        frame.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_BYTES or min(frame.width, frame.height) <= MIN_DIM:
            return data, frame.width, frame.height
        scale *= 0.9


def napcat_result_summary(res):
    """NapCat 已知会出现假阴性（头像已更新却报错），统一附加提示。"""
    if not isinstance(res, dict):
        return {"ok": False, "detail": "NapCat 返回格式异常", "data": res}
    ok = res.get("status") == "ok" and res.get("retcode") == 0
    detail = f"retcode={res.get('retcode')} {res.get('msg') or res.get('wording') or ''}".strip()
    return {"ok": ok, "detail": detail or ("成功" if ok else "失败"), "data": res.get("data")}


# ---------- HTTP 服务 ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > 64 * 1024 * 1024:
            raise ToolError("文件过大（>64MB）")
        return self.rfile.read(length)

    # ----- GET -----
    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/" or path == "/index.html":
                return self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                rel = Path(path[len("/static/"):])
                if ".." in rel.parts:
                    return self._send(403, {"ok": False, "error": "禁止访问"})
                f = STATIC_DIR / rel
                ctype = "application/javascript" if f.suffix == ".js" else (
                    "text/css" if f.suffix == ".css" else "application/octet-stream")
                return self._send_file(f, ctype)
            if path == "/api/config":
                cfg = load_config()
                return self._send(200, {"ok": True, **cfg})
            if path == "/api/napcat/status":
                try:
                    cfg = load_config()
                    client = NapCatClient(cfg["napcat_url"], cfg["token"])
                    info = client.login_info()
                    s = napcat_result_summary(info)
                    if s["ok"] and isinstance(s["data"], dict):
                        return self._send(200, {"ok": True, "login": s["data"]})
                    return self._send(200, {"ok": False, "error": s["detail"]})
                except ToolError as e:
                    return self._send(200, {"ok": False, "error": str(e)})
            if path == "/api/builtin/status":
                return self._send(200, {"ok": True, **builtin_status()})
            if path == "/api/builtin/log":
                try:
                    data = BOOT_LOG.read_bytes()[-4096:]
                    return self._send(200, {"ok": True, "log": data.decode("utf-8", "replace")})
                except FileNotFoundError:
                    return self._send(200, {"ok": True, "log": ""})
            self._send(404, {"ok": False, "error": "not found"})
        except BrokenPipeError:
            pass
        except Exception as e:
            self._send(500, {"ok": False, "error": f"{e}"})

    def _send_file(self, fpath, ctype):
        try:
            data = fpath.read_bytes()
        except FileNotFoundError:
            return self._send(404, {"ok": False, "error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ----- POST -----
    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            if path == "/api/config":
                body = json.loads(self._read_body().decode("utf-8"))
                cfg = load_config()
                cfg["napcat_url"] = str(body.get("napcat_url", cfg["napcat_url"]))[:300]
                cfg["token"] = str(body.get("token", cfg["token"]))[:300]
                save_config(cfg)
                return self._send(200, {"ok": True})
            if path == "/api/image":
                data = self._read_body()
                if not data:
                    raise ToolError("空的图片数据")
                UPLOAD_DIR.mkdir(exist_ok=True)
                image_id = uuid.uuid4().hex[:16]
                tmp = UPLOAD_DIR / f"src_{image_id}.png"
                tmp.write_bytes(data)
                try:
                    info = inspect_image(tmp)
                except Exception:
                    tmp.unlink(missing_ok=True)
                    raise
                return self._send(200, {"ok": True, "image_id": image_id, **info})
            if path == "/api/builtin/start":
                pid = start_builtin()
                return self._send(200, {"ok": True, "pid": pid})
            if path == "/api/builtin/stop":
                stop_builtin()
                return self._send(200, {"ok": True})
            if path == "/api/builtin/quicklogin":
                body = json.loads(self._read_body().decode("utf-8") or "{}")
                uin = str(body.get("uin") or "").strip()
                if not uin.isdigit():
                    raise ToolError("QQ 号格式不正确")
                builtin_quick_login(uin)
                return self._send(200, {"ok": True})
            if path == "/api/builtin/qrrefresh":
                builtin_qr_refresh()
                return self._send(200, {"ok": True})
            if path == "/api/builtin/elevate":
                # 以管理员身份重启本程序（注入 QQ 需要），随后退出当前实例
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Start-Process -FilePath '{sys.executable}' "
                     f"-ArgumentList '\"{Path(sys.argv[0])}\"' -Verb RunAs"],
                    capture_output=True)
                if r.returncode != 0:
                    return self._send(200, {"ok": False,
                                            "error": "提权失败（可能拒绝了 UAC）：" + r.stderr.decode("utf-8", "replace")[:200]})
                threading.Timer(1.5, lambda: os._exit(0)).start()
                return self._send(200, {"ok": True})
            if path == "/api/avatar":
                body = json.loads(self._read_body().decode("utf-8"))
                image_id = str(body.get("image_id", ""))
                if not re.fullmatch(r"[0-9a-f]{16}", image_id):
                    raise ToolError("无效的图片 ID，请重新导入图片")
                src = UPLOAD_DIR / f"src_{image_id}.png"
                if not src.exists():
                    raise ToolError("图片已过期，请重新导入")

                cfg = load_config()
                # 优先走内置 NapCat；未登录则回退到外置地址
                mode = "builtin"
                client = NapCatClient(f"http://127.0.0.1:{ONEBOT_PORT}", cfg["internal_token"])
                try:
                    login = napcat_result_summary(client.login_info())
                    if not login["ok"]:
                        raise ToolError(login["detail"])
                    login_data = login.get("data") or {}
                except ToolError:
                    mode = "external"
                    client = NapCatClient(cfg["napcat_url"], cfg["token"])
                    try:
                        login = napcat_result_summary(client.login_info())
                        if not login["ok"]:
                            raise ToolError(f"NapCat 未就绪：{login['detail']}")
                        login_data = login.get("data") or {}
                    except ToolError:
                        raise
                    except Exception as e:
                        raise ToolError(f"连接 NapCat 失败：{e}")
                except Exception as e:
                    raise ToolError(f"连接内置 NapCat 失败：{e}")

                png, w, h = render_avatar(
                    src, body.get("x", 0), body.get("y", 0), body.get("size", 0),
                    angle=max(-360, min(360, float(body.get("angle") or 0))),
                    flip_h=bool(body.get("flip_h")),
                    flip_v=bool(body.get("flip_v")))
                out = UPLOAD_DIR / f"out_{uuid.uuid4().hex[:16]}.png"
                out.write_bytes(png)
                try:
                    res = napcat_result_summary(client.set_avatar(out))
                finally:
                    out.unlink(missing_ok=True)

                result = {
                    "ok": res["ok"],
                    "detail": res["detail"],
                    "mode": mode,
                    "sent": {"width": w, "height": h, "bytes": len(png)},
                    "login": login_data,
                    "hint": ("若此处报错，请先刷新 QQ 查看头像是否实际已更新"
                             "（NapCat 对 set_qq_avatar 存在已知的假阴性）")
                            if not res["ok"] else "",
                }
                return self._send(200, result)
            self._send(404, {"ok": False, "error": "not found"})
        except ToolError as e:
            self._send(200, {"ok": False, "error": str(e)})
        except json.JSONDecodeError:
            self._send(200, {"ok": False, "error": "请求体不是合法 JSON"})
        except BrokenPipeError:
            pass
        except Exception as e:
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})


def main():
    install_exit_cleanup()
    UPLOAD_DIR.mkdir(exist_ok=True)
    for stale in UPLOAD_DIR.glob("*"):
        stale.unlink(missing_ok=True)

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"NTQQ 头像工具已启动：{url}  （Ctrl+C 退出）")
    import os
    if not os.environ.get("NTAVATAR_NO_BROWSER"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
