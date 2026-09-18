import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _quote(symbol):
    response = requests.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={"range": "5d", "interval": "1d"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=(5, 10),
    )
    response.raise_for_status()
    payload = response.json()
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result.get("timestamp") or []
    closes = (result.get("indicators", {}).get("quote", [{}])[0].get("close") or [])
    points = [(ts, close) for ts, close in zip(timestamps, closes) if close is not None]
    if not points:
        raise ValueError("가격 데이터가 없습니다.")
    ts, close = points[-1]
    previous = points[-2][1] if len(points) > 1 else meta.get("previousClose")
    change = close - previous if previous is not None else None
    pct = change / previous * 100 if previous not in (None, 0) and change is not None else None
    return {
        "symbol": symbol,
        "price": float(close),
        "change": float(change) if change is not None else None,
        "pct": float(pct) if pct is not None else None,
        "timestamp": ts,
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_macro():
    data = {
        "USD/KRW": _quote("KRW=X"),
        "JPY/KRW": _quote("JPYKRW=X"),
        "EUR/KRW": _quote("EURKRW=X"),
        "GOLD/USD": _quote("GC=F"),
    }
    data["GOLD/KRW_G"] = {
        "price": data["GOLD/USD"]["price"] * data["USD/KRW"]["price"] / 31.1034768,
        "change": None,
        "pct": data["GOLD/USD"]["pct"],
        "timestamp": data["GOLD/USD"]["timestamp"],
    }
    return data


def _change_text(item, digits=2):
    if item.get("change") is None:
        return "변동률 확인 필요"
    sign = "▲" if item["change"] >= 0 else "▼"
    return f"{sign} {item['change']:+.{digits}f} ({item['pct']:+.2f}%)"


def render_macro_snapshot():
    st.subheader("환율 · 금 시세")
    try:
        data = fetch_macro()
        fx, gold = st.columns([1.25, 1])
        with fx:
            with st.container(border=True):
                st.markdown("### 🌐 환율")
                for label in ("USD/KRW", "JPY/KRW", "EUR/KRW"):
                    item = data[label]
                    cols = st.columns([1.7, 1.5, 2])
                    cols[0].markdown(f"**{label}**")
                    cols[1].write(f"{item['price']:,.2f}")
                    color_text = _change_text(item)
                    cols[2].write(color_text)
                updated = datetime.fromtimestamp(
                    data["USD/KRW"]["timestamp"], tz=ZoneInfo("Asia/Seoul")
                ).strftime("%m/%d %H:%M")
                st.caption(f"Yahoo Finance · 최근 거래 데이터 · {updated} KST")

        with gold:
            with st.container(border=True):
                st.markdown("### 🪙 금 시세")
                usd = data["GOLD/USD"]
                krw = data["GOLD/KRW_G"]
                st.metric("국제 금 (Gold/USD)", f"$ {usd['price']:,.2f}", _change_text(usd))
                st.metric("원화 환산 금 1g", f"₩ {krw['price']:,.0f}", f"{usd['pct']:+.2f}%" if usd.get("pct") is not None else "변동률 확인 필요")
                st.caption("국제 금 선물(GC=F)을 원/달러 환율로 환산한 참고값 · 1 트로이온스 = 31.1035g")
    except Exception:
        with st.container(border=True):
            st.warning("환율·금 시세를 불러오지 못했습니다.")
            st.caption("외부 시세 제공 서버가 일시적으로 응답하지 않을 수 있습니다. 잠시 후 새로고침하세요.")
