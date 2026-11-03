"""下载 NapCat Shell 载荷到 payload/napcat_shell.zip（构建 exe 前执行一次）。

仅使用标准库。国内网络访问 GitHub 慢时可先设置代理，例如：
    set HTTPS_PROXY=http://127.0.0.1:7890
"""
import os
import sys
import urllib.request

NAPCAT_VERSION = "v4.18.42"
URL = (f"https://github.com/NapNeko/NapCatQQ/releases/download/"
       f"{NAPCAT_VERSION}/NapCat.Shell.zip")
DEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "payload", "napcat_shell.zip")


def main():
    if os.path.exists(DEST):
        print(f"已存在：{DEST}（如需重新下载请先删除）")
        return 0
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    print(f"下载 {URL}")
    print(f"（未自动走代理；需要时可设置 HTTPS_PROXY 环境变量）")
    tmp = DEST + ".part"
    try:
        with urllib.request.urlopen(URL, timeout=60) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r{done / total * 100:5.1f}%  ({done // 1024} KiB)",
                          end="", flush=True)
        print()
        os.replace(tmp, DEST)
        print(f"完成：{DEST}（{os.path.getsize(DEST) // 1024} KiB）")
        return 0
    except Exception as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        print(f"\n下载失败：{e}\n可手动下载 {URL} 放到 {DEST}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
