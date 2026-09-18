import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

def _quote(symbol, range_="5d", interval="1d"):
    response = requests.get(YAHOO_CHART_URL.format(symbol=symbol), params={"range": range_, "interval": interval}, headers={"User-Agent": "Mozilla/5.0"}, timeout=(5, 10))
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result.get("timestamp") or []
    closes = (result.get("indicators", {}).get("quote", [{}])[0].get("close") or [])
    points = [(ts, close) for ts, close in zip(timestamps, closes) if close is not None]
    if not points:
        raise ValueError(f"no data: {symbol}")
    ts, close = points[-1]
    previous = points[-2][1] if len(points) > 1 else meta.get("previousClose")
    change = close - previous if previous is not None else None
    pct = change / previous * 100 if previous not in (None, 0) and change is not None else None
    return {"symbol": symbol, "price": float(close), "change": float(change) if change is not None else None, "pct": float(pct) if pct is not None else None, "timestamp": ts}

@st.cache_data(ttl=60, show_spinner=False)
def fetch_macro():
    symbols = {
        "KOSPI": "^KS11", "KOSDAQ": "^KQ11",
        "USD/KRW": "KRW=X", "JPY/KRW": "JPYKRW=X", "EUR/KRW": "EURKRW=X",
        "GOLD/USD": "GC=F", "WTI": "CL=F", "US10Y": "^TNX", "DXY": "DX-Y.NYB",
        "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "현대차": "005380.KS", "NAVER": "035420.KS",
    }
    data = {label: _quote(symbol) for label, symbol in symbols.items()}
    data["GOLD/KRW_G"] = {"price": data["GOLD/USD"]["price"] * data["USD/KRW"]["price"] / 31.1034768, "change": None, "pct": data["GOLD/USD"]["pct"], "timestamp": data["GOLD/USD"]["timestamp"]}
    return data

def _change_text(item, digits=2):
    if item.get("change") is None or item.get("pct") is None:
        return "변동률 확인 필요"
    sign = "▲" if item["change"] >= 0 else "▼"
    return f"{item['change']:+.{digits}f} ({item['pct']:+.2f}%)"

def _metric_row(items, value_digits=2):
    for label in items:
        item = items[label]
        cols = st.columns([1.7, 1.5, 2])
        cols[0].markdown(f"**{label}**")
        cols[1].write(f"{item['price']:,.{value_digits}f}")
        cols[2].write(_change_text(item))

def render_macro_snapshot():
    st.subheader("시장 한눈에 보기")
    try:
        data = fetch_macro()
        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                st.markdown("### 📈 국내 지수")
                _metric_row(("KOSPI", "KOSDAQ"))
                st.caption("Yahoo Finance · 지연 시세")
        with c2:
            with st.container(border=True):
                st.markdown("### 💱 환율 · 달러")
                _metric_row(("USD/KRW", "JPY/KRW", "EUR/KRW"))
                dxy = data["DXY"]
                st.write(f"**DXY**  {dxy['price']:,.2f}  {_change_text(dxy)}")
                st.caption("Yahoo Finance · 지연 시세")
        c3, c4 = st.columns(2)
        with c3:
            with st.container(border=True):
                st.markdown("### 🛢️ 원유 · 금리")
                st.write(f"**WTI**  $ {data['WTI']['price']:,.2f}  {_change_text(data['WTI'])}")
                st.write(f"**미국 10년물**  {data['US10Y']['price']:,.3f}%  {_change_text(data['US10Y'], 3)}")
                st.write(f"**국제 금**  $ {data['GOLD/USD']['price']:,.2f}  {_change_text(data['GOLD/USD'])}")
                st.write(f"**금 1g 환산**  ₩{data['GOLD/KRW_G']['price']:,.0f}")
                st.caption("WTI·금은 선물 기준, 미국 10년물은 ^TNX 지수 기준")
        with c4:
            with st.container(border=True):
                st.markdown("### ⭐ 관심종목")
                for label in ("삼성전자", "SK하이닉스", "현대차", "NAVER"):
                    item = data[label]
                    cols = st.columns([1.7, 1.5, 2])
                    cols[0].markdown(f"**{label}**")
                    cols[1].write(f"₩{item['price']:,.0f}")
                    cols[2].write(_change_text(item, 0))
                st.caption("기본 관심종목 · Yahoo Finance 지연 시세")
        updated = datetime.fromtimestamp(data["KOSPI"]["timestamp"], tz=ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
        st.caption(f"마지막 데이터 시각: {updated} · 새로고침 주기 약 60초")
    except Exception:
        with st.container(border=True):
            st.warning("시장 시세를 일부 또는 전체 불러오지 못했습니다.")
            st.caption("외부 시세 제공 서버가 일시적으로 응답하지 않을 수 있습니다. 잠시 후 새로고침하세요.")
