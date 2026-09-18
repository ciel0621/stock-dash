import json
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import websocket

KIS_APPROVAL_URL = "https://openapi.koreainvestment.com:9443/oauth2/Approval"
KIS_WS_URL = "ws://ops.koreainvestment.com:21000"
KIS_TR_ID = "H0STCNT0"


def _secrets():
    appkey = st.secrets.get("KIS_APPKEY", "")
    appsecret = st.secrets.get("KIS_APPSECRET", "")
    return str(appkey).strip(), str(appsecret).strip()


@st.cache_data(ttl=300, show_spinner=False)
def _approval_key(appkey, appsecret):
    response = requests.post(
        KIS_APPROVAL_URL,
        headers={"content-type": "application/json; charset=utf-8"},
        json={"grant_type": "client_credentials", "appkey": appkey, "secretkey": appsecret},
        timeout=(5, 10),
    )
    response.raise_for_status()
    key = response.json().get("approval_key")
    if not key:
        raise ValueError("KIS approval_key missing")
    return key


class KISRealtime:
    def __init__(self, appkey, appsecret):
        self.appkey = appkey
        self.appsecret = appsecret
        self.lock = threading.Lock()
        self.prices = {}
        self.codes = set()
        self.ws = None
        self.thread = None
        self.stop_event = threading.Event()
        self.connected = False
        self.reconnect_count = 0
        self.last_error = ""
        self.last_connected_at = None
        self.last_message_at = None

    def set_codes(self, codes):
        codes = {str(c).strip() for c in codes if str(c).strip().isdigit() and len(str(c).strip()) == 6}
        with self.lock:
            changed = codes != self.codes
            self.codes = codes
        if changed:
            self._restart()

    def _restart(self):
        self.stop_event.set()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _subscribe_message(self, code, tr_type="1"):
        return json.dumps({
            "header": {
                "approval_key": _approval_key(self.appkey, self.appsecret),
                "custtype": "P",
                "tr_type": tr_type,
                "content-type": "utf-8",
            },
            "body": {"input": {"tr_id": KIS_TR_ID, "tr_key": code}},
        })

    def _run(self):
        while not self.stop_event.is_set():
            try:
                ws = websocket.create_connection(KIS_WS_URL, timeout=10)
                self.ws = ws
                with self.lock:
                    self.connected = True
                    self.last_error = ""
                    self.last_connected_at = time.time()
                with self.lock:
                    codes = list(self.codes)
                for code in codes:
                    ws.send(self._subscribe_message(code))
                    time.sleep(0.12)
                while not self.stop_event.is_set():
                    raw = ws.recv()
                    if not raw:
                        continue
                    with self.lock:
                        self.last_message_at = time.time()
                    self._parse(raw)
            except Exception as exc:
                with self.lock:
                    self.connected = False
                    self.reconnect_count += 1
                    self.last_error = str(exc)[:180]
                time.sleep(2)
            finally:
                if self.ws:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
                self.ws = None
                with self.lock:
                    self.connected = False

    def _parse(self, raw):
        if raw.startswith("{"):
            return
        parts = raw.split("|")
        if len(parts) < 4 or parts[0] != "0":
            return
        tr_id = parts[1]
        if tr_id != KIS_TR_ID:
            return
        fields = parts[3].split("^")
        if len(fields) < 7:
            return
        code = fields[0]
        try:
            price = float(fields[2])
            change = float(fields[4])
            pct = float(fields[5])
        except (TypeError, ValueError):
            return
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        with self.lock:
            self.prices[code] = {
                "symbol": code,
                "price": price,
                "change": change,
                "pct": pct,
                "timestamp": now.timestamp(),
                "updated_at": now.strftime("%Y-%m-%d %H:%M:%S KST"),
                "source": "한국투자증권 실시간",
            }

    def status(self):
        with self.lock:
            if self.connected:
                return {"state": "connected", "label": "● 실시간 연결됨", "reconnect_count": self.reconnect_count, "last_error": self.last_error, "last_connected_at": self.last_connected_at, "last_message_at": self.last_message_at}
            return {"state": "reconnecting", "label": "↻ 자동 재연결 중", "reconnect_count": self.reconnect_count, "last_error": self.last_error, "last_connected_at": self.last_connected_at, "last_message_at": self.last_message_at}

    def get(self, code):
        with self.lock:
            return self.prices.get(str(code).strip())


@st.cache_resource
def get_kis_realtime():
    appkey, appsecret = _secrets()
    if not appkey or not appsecret:
        return None
    return KISRealtime(appkey, appsecret)


def realtime_quotes(codes):
    service = get_kis_realtime()
    if service is None:
        return {}, "KIS_APPKEY/KIS_APPSECRET 미설정"
    service.set_codes(codes)
    time.sleep(0.15)
    with service.lock:
        return {code: service.prices.get(code) for code in codes if service.prices.get(code)}, "한국투자증권 실시간"


def realtime_status():
    service = get_kis_realtime()
    if service is None:
        return {"state": "unconfigured", "label": "○ KIS 미설정", "reconnect_count": 0, "last_error": "Secrets에 KIS_APPKEY/KIS_APPSECRET가 없습니다."}
    return service.status()
