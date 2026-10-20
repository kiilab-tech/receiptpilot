"""ReceiptPilot.app の起動役(docs/UI要件定義.md の B)。

アプリをダブルクリックすると Contents/MacOS/ReceiptPilot からこのファイルが呼ばれる。

1. すでに動いていれば、新しく起動せずブラウザで画面を開くだけ(二重起動の防止 R8)。
   ただし動いているのが別の版・別の場所のアプリ(入れ替える前の古い版など)なら、
   それを止めてから、この版で起動し直す(入れ替え時に「先に終了」を不要にする)
2. 動いていなければ、空いている番号(ポート)を選んで画面のサーバーを裏で起動し(R17)、
   準備ができたらブラウザで開く。サーバーは 127.0.0.1 だけで待ち受ける(R18)
3. データは「書類/ReceiptPilot」に置く(R21)。ログは ~/Library/Logs/ReceiptPilot
4. 失敗したら、日本語のダイアログで知らせる

このプロセス自体は、ブラウザを開いたら終わる(サーバーは裏で動き続け、画面の「終了する」で止まる)。
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RES = Path(__file__).resolve().parent            # Contents/Resources
HOME = Path.home()
DATA = HOME / "Documents" / "ReceiptPilot"
SUPPORT = HOME / "Library" / "Application Support" / "ReceiptPilot"
LOGS = HOME / "Library" / "Logs" / "ReceiptPilot"
STATE = SUPPORT / "server.json"
VERSION = (RES / "VERSION").read_text().strip() if (RES / "VERSION").exists() else "dev"
IDLE_EXIT_MIN = 180  # 画面を3時間さわらなければ自動で止まる(閉じ忘れ対策 R19)


def dialog(message: str) -> None:
    script = (f'display dialog "{message}" with title "ReceiptPilot" '
              'buttons {"OK"} default button "OK" with icon caution')
    subprocess.run(["osascript", "-e", script], check=False)


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def running_server() -> dict | None:
    """動いているサーバーの情報 {pid, port, version, app}。動いていなければ None。"""
    try:
        info = json.loads(STATE.read_text())
        port = int(info["port"])
    except (OSError, ValueError, KeyError):
        return None
    return info if healthy(port) else None


def is_our_server(pid: int) -> bool:
    """その番号のプロセスが ReceiptPilot の画面のサーバーか(別のプロセスを止めないための確認)。"""
    out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    cmd = out.stdout
    return "streamlit" in cmd and "ReceiptPilot" in cmd and "streamlit_app.py" in cmd


def stop_server(info: dict) -> None:
    """古い版のサーバーを止める。止まるまで最大10秒待ち、だめなら強制終了する。"""
    pid, port = int(info.get("pid", 0)), int(info["port"])
    if not pid or not is_our_server(pid):
        raise RuntimeError("動いている ReceiptPilot を確認できませんでした")
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not healthy(port):
            return
        time.sleep(0.5)
    os.kill(pid, signal.SIGKILL)
    time.sleep(1)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_browser(port: int) -> None:
    subprocess.run(["open", f"http://127.0.0.1:{port}"], check=False)


def start_server() -> int:
    port = free_port()
    env = {
        **os.environ,
        "RECEIPTPILOT_DATA": str(DATA),
        "RECEIPTPILOT_IDLE_EXIT_MIN": str(IDLE_EXIT_MIN),
        "PYTHONNOUSERSITE": "1",
    }
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(RES / "app" / "streamlit_app.py"),
        "--server.address", "127.0.0.1", "--server.port", str(port),
        "--server.headless", "true", "--server.maxUploadSize", "20",
        "--server.fileWatcherType", "none", "--global.developmentMode", "false",
        "--browser.gatherUsageStats", "false", "--client.toolbarMode", "minimal",
        "--theme.base", "light", "--theme.primaryColor", "#2f7d5b",
    ]
    log = (LOGS / "server.log").open("a", encoding="utf-8")
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 起動 port={port}\n")
    log.flush()
    proc = subprocess.Popen(cmd, cwd=str(RES), env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    STATE.write_text(json.dumps({"pid": proc.pid, "port": port, "version": VERSION, "app": str(RES)}))
    for _ in range(120):  # 最大60秒待つ
        if healthy(port):
            return port
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    raise RuntimeError("画面のサーバーが起動しませんでした")


def main() -> None:
    for d in (DATA, SUPPORT, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    # 同時にダブルクリックされても、起動は1回だけにする
    with (SUPPORT / "launch.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = running_server()
        if info and (info.get("version") != VERSION or info.get("app") != str(RES)):
            with (LOGS / "server.log").open("a", encoding="utf-8") as f:
                f.write(f"古い版({info.get('version', '不明')})を止めて {VERSION} で起動し直します\n")
            try:
                stop_server(info)
            except Exception as e:  # noqa: BLE001
                dialog("前の版の ReceiptPilot が動いています。画面の「終了する」を押してから、"
                       f"もう一度開いてください。({e})")
                sys.exit(1)
            info = None
        port = int(info["port"]) if info else None
        if port is None:
            try:
                port = start_server()
            except Exception as e:  # noqa: BLE001
                with (LOGS / "server.log").open("a", encoding="utf-8") as f:
                    f.write(f"起動失敗: {type(e).__name__}: {e}\n")
                dialog("ReceiptPilot を起動できませんでした。"
                       "Mac を再起動してから、もう一度開いてください。"
                       f"解決しない場合は、記録ファイル {LOGS / 'server.log'} を添えてご連絡ください。")
                sys.exit(1)
    open_browser(port)


if __name__ == "__main__":
    main()
