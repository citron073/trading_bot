from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple


APP_DIR = Path(__file__).resolve().parent
HEALTHCHECK_SCRIPT = APP_DIR / "keiba_public_healthcheck.sh"
PUBLIC_STATUS_PATH = APP_DIR / "data" / "public_tunnel_status.json"
HEALTH_STATUS_PATH = APP_DIR / "data" / "public_health_status.json"
WATCH_STATE_PATH = APP_DIR / "data" / "public_watch_state.json"
CONFIG_PATH = APP_DIR / ".streamlit" / "keiba_public_notify.json"

try:
    from tools.notification_policy import LEVEL_CRITICAL, LEVEL_INFO, LEVEL_WARN, post_ntfy
except ModuleNotFoundError:
    main_dir = APP_DIR.parent / "MAIN"
    if str(main_dir) not in sys.path:
        sys.path.insert(0, str(main_dir))
    from tools.notification_policy import LEVEL_CRITICAL, LEVEL_INFO, LEVEL_WARN, post_ntfy  # type: ignore


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_healthcheck() -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            [str(HEALTHCHECK_SCRIPT)],
            cwd=str(APP_DIR),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return False, f"healthcheck failed: {exc}"
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    return result.returncode == 0, output.strip()


def _is_healthy(health: Dict[str, Any]) -> bool:
    return bool(
        health.get("launchagent_loaded") is True
        and health.get("local_ok") is True
        and health.get("public_ok") is True
        and int(health.get("public_http_status") or 0) in range(200, 400)
    )


def _notify_macos(title: str, text: str) -> Tuple[bool, str]:
    safe_title = title.replace('"', "'")
    safe_text = text.replace('"', "'")
    script = f'display notification "{safe_text}" with title "{safe_title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=10)
        return True, "macos"
    except Exception as exc:
        return False, f"macos:{exc}"


def _http_post(url: str, body: bytes, headers: Dict[str, str]) -> Tuple[bool, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            code = getattr(resp, "status", 200)
        return 200 <= int(code) < 400, str(code)
    except Exception as exc:
        return False, str(exc)


def _event_level(event_type: str) -> str:
    code = str(event_type or "").strip().lower()
    if code == "recovered":
        return LEVEL_INFO
    if code in {"url_changed", "still_unhealthy"}:
        return LEVEL_WARN
    if code == "unhealthy":
        return LEVEL_CRITICAL
    return LEVEL_WARN


def _notify_remote(config: Dict[str, Any], title: str, text: str, payload: Dict[str, Any], event_type: str) -> Tuple[bool, str]:
    results = []
    level = _event_level(event_type)

    ntfy_url = str(config.get("ntfy_topic_url", "") or "").strip()
    ntfy_token = str(config.get("ntfy_bearer_token", "") or "").strip()
    if ntfy_url:
        ok_ntfy, msg_ntfy = post_ntfy(
            ntfy_url,
            title or "KEIBA Public Notification",
            text,
            level=level,
            tags="horse,public_watch",
            bearer=ntfy_token,
            timeout=8.0,
        )
        results.append(("ntfy", ok_ntfy, msg_ntfy))

    webhook_url = str(config.get("webhook_url", "") or "").strip()
    webhook_token = str(config.get("webhook_bearer_token", "") or "").strip()
    if webhook_url:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if webhook_token:
            headers["Authorization"] = f"Bearer {webhook_token}"
        webhook_payload = dict(payload)
        webhook_payload["event_code"] = str(event_type or webhook_payload.get("event", "") or "").strip()
        webhook_payload["event_level"] = level
        results.append(("webhook",) + _http_post(webhook_url, json.dumps(webhook_payload, ensure_ascii=False).encode("utf-8"), headers))

    if not results:
        return True, "no_remote_target"

    ok_all = all(ok for _, ok, _ in results)
    detail = ", ".join(f"{name}:{msg}" for name, _, msg in results)
    return ok_all, detail


def _notify(config: Dict[str, Any], title: str, text: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not bool(config.get("enabled", True)):
        return True, "disabled"

    details = []
    ok_all = True

    if bool(config.get("macos_notification", True)):
        ok, msg = _notify_macos(title, text)
        ok_all = ok_all and ok
        details.append(msg)

    ok_remote, msg_remote = _notify_remote(config, title, text, payload, str(payload.get("event", "")))
    ok_all = ok_all and ok_remote
    details.append(msg_remote)
    return ok_all, ", ".join(details)


def _find_streamlit_pid_from_status(status: Dict[str, Any], health: Dict[str, Any]) -> int:
    for key in ("streamlit_pid",):
        try:
            pid = int(status.get(key) or 0)
        except Exception:
            pid = 0
        if pid > 0:
            return pid

    local_url = str(health.get("local_url", "") or status.get("local_url", "") or "").strip()
    port = ""
    if ":" in local_url:
        port = local_url.rsplit(":", 1)[-1].strip()
    if not port.isdigit():
        port = str(status.get("port", "") or "").strip()
    if not port.isdigit():
        return 0

    try:
        result = subprocess.run(
            ["ps", "ax", "-o", "pid=", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return 0

    target_tokens = (f"--server.port {port}", f"--server.port={port}")
    for line in (result.stdout or "").splitlines():
        raw = line.strip()
        if not raw or "streamlit run app.py" not in raw:
            continue
        if not any(token in raw for token in target_tokens):
            continue
        pid_text = raw.split(maxsplit=1)[0]
        try:
            return int(pid_text)
        except Exception:
            continue
    return 0


def _terminate_pid(pid: int, sig: int = signal.SIGTERM) -> Tuple[bool, str]:
    if pid <= 0:
        return False, "pid_missing"
    try:
        os.kill(pid, sig)
        return True, f"terminated_pid={pid}"
    except ProcessLookupError:
        return False, f"pid_not_found={pid}"
    except Exception as exc:
        return False, f"kill_failed:{pid}:{exc}"


def _build_event(
    previous: Dict[str, Any],
    health: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[str, str, str]:
    has_previous = bool(str(previous.get("checked_at", "") or "").strip())
    healthy = _is_healthy(health)
    prev_status = str(previous.get("status", "unknown") or "unknown")
    curr_status = "healthy" if healthy else "unhealthy"
    prev_url = str(previous.get("public_url", "") or "").strip()
    curr_url = str(health.get("public_url", "") or "").strip()
    http_status = str(health.get("public_http_status", "-") or "-")

    if not has_previous:
        return "", "", ""

    if bool(config.get("notify_on_url_change", True)) and prev_url and curr_url and prev_url != curr_url:
        title = "KEIBA public URL changed"
        text = f"new url: {curr_url}"
        return "url_changed", title, text

    if prev_status != "healthy" and curr_status == "healthy" and bool(config.get("notify_on_recovery", True)):
        title = "KEIBA public recovered"
        text = f"url: {curr_url} / http: {http_status}"
        return "recovered", title, text

    if prev_status != "unhealthy" and curr_status == "unhealthy":
        title = "KEIBA public unhealthy"
        text = f"http: {http_status} / message: {str(health.get('message', '-') or '-')}"
        return "unhealthy", title, text

    if curr_status == "unhealthy" and bool(config.get("repeat_unhealthy_notification", True)):
        min_interval_sec = max(60, int(config.get("min_interval_sec", 600) or 600))
        last_notified_ts = float(previous.get("last_notified_ts", 0.0) or 0.0)
        if time.time() - last_notified_ts >= min_interval_sec:
            title = "KEIBA public still unhealthy"
            text = f"http: {http_status} / message: {str(health.get('message', '-') or '-')}"
            return "still_unhealthy", title, text

    return "", "", ""


def _restart_public_process(config: Dict[str, Any], health: Dict[str, Any], state: Dict[str, Any]) -> Tuple[bool, str]:
    if not bool(config.get("auto_restart_on_unhealthy", True)):
        return False, "auto_restart_disabled"

    cooldown_sec = max(60, int(config.get("restart_cooldown_sec", 900) or 900))
    last_restart_ts = float(state.get("last_restart_ts", 0.0) or 0.0)
    if time.time() - last_restart_ts < cooldown_sec:
        return False, "restart_cooldown"

    status = _read_json(PUBLIC_STATUS_PATH)
    tunnel_pid = 0
    try:
        tunnel_pid = int(status.get("tunnel_pid") or 0)
    except Exception:
        tunnel_pid = 0
    streamlit_pid = _find_streamlit_pid_from_status(status, health)

    local_ok = health.get("local_ok") is True
    public_ok = health.get("public_ok") is True

    restart_notes = []
    restarted = False

    if local_ok and not public_ok and tunnel_pid > 0:
        ok_kill, msg_kill = _terminate_pid(tunnel_pid)
        restart_notes.append(msg_kill)
        return ok_kill, ", ".join(restart_notes)

    if not local_ok:
        if tunnel_pid > 0:
            ok_tunnel, msg_tunnel = _terminate_pid(tunnel_pid)
            restarted = restarted or ok_tunnel
            restart_notes.append(msg_tunnel)
        if streamlit_pid > 0:
            ok_streamlit, msg_streamlit = _terminate_pid(streamlit_pid)
            restarted = restarted or ok_streamlit
            restart_notes.append(msg_streamlit)
        if restarted:
            return True, ", ".join(restart_notes)

    if tunnel_pid > 0:
        ok_kill, msg_kill = _terminate_pid(tunnel_pid)
        return ok_kill, msg_kill

    label = str(health.get("label", "com.ouroboros.keiba.public") or "com.ouroboros.keiba.public")
    try:
        uid = subprocess.run(["id", "-u"], capture_output=True, text=True, timeout=1, check=True).stdout.strip()
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"], capture_output=True, text=True, timeout=5, check=True)
        return True, f"kickstart:{label}"
    except Exception as exc:
        return False, f"kickstart_failed:{exc}"


def main() -> int:
    config = _read_json(CONFIG_PATH)
    previous = _read_json(WATCH_STATE_PATH)

    ok, output = _run_healthcheck()
    health = _read_json(HEALTH_STATUS_PATH)
    if not ok and not health:
        health = {
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "launchagent_loaded": False,
            "local_ok": False,
            "public_ok": False,
            "public_http_status": None,
            "public_url": "",
            "message": output or "healthcheck failed",
        }

    event_type, title, text = _build_event(previous, health, config)
    state = {
        "checked_at": str(health.get("checked_at", datetime.now().isoformat(timespec="seconds"))),
        "status": "healthy" if _is_healthy(health) else "unhealthy",
        "provider": str(health.get("provider", "") or ""),
        "public_url": str(health.get("public_url", "") or ""),
        "public_http_status": health.get("public_http_status"),
        "last_event_type": str(previous.get("last_event_type", "") or ""),
        "last_notified_at": str(previous.get("last_notified_at", "") or ""),
        "last_notified_ts": float(previous.get("last_notified_ts", 0.0) or 0.0),
        "last_notify_result": str(previous.get("last_notify_result", "") or ""),
        "last_restart_at": str(previous.get("last_restart_at", "") or ""),
        "last_restart_ts": float(previous.get("last_restart_ts", 0.0) or 0.0),
        "last_restart_result": str(previous.get("last_restart_result", "") or ""),
    }

    if state["status"] == "unhealthy":
        restarted, restart_msg = _restart_public_process(config, health, state)
        state["last_restart_result"] = restart_msg
        if restarted:
            now_iso = datetime.now().isoformat(timespec="seconds")
            state["last_restart_at"] = now_iso
            state["last_restart_ts"] = time.time()

    if event_type:
        payload = {
            "event": event_type,
            "checked_at": health.get("checked_at"),
            "provider": health.get("provider"),
            "public_url": health.get("public_url"),
            "local_ok": health.get("local_ok"),
            "public_ok": health.get("public_ok"),
            "public_http_status": health.get("public_http_status"),
            "message": health.get("message"),
            "restart_result": state.get("last_restart_result", ""),
        }
        ok_notify, notify_msg = _notify(config, title, text, payload)
        now_iso = datetime.now().isoformat(timespec="seconds")
        state["last_event_type"] = event_type
        state["last_notified_at"] = now_iso
        state["last_notified_ts"] = time.time()
        state["last_notify_result"] = notify_msg
        print(f"notify_event={event_type}")
        print(f"notify_ok={ok_notify}")
        print(f"notify_message={notify_msg}")
    else:
        print("notify_event=-")
        print("notify_ok=True")
        print("notify_message=no_change")

    _write_json(WATCH_STATE_PATH, state)
    print(f"status={state['status']}")
    print(f"public_url={state['public_url'] or '-'}")
    print(f"checked_at={state['checked_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
