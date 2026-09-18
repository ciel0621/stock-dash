from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape

import requests
import streamlit as st

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_WATCHLIST = [
    {"code": "005930", "name": "삼성전자", "kind": "관심"},
    {"code": "000660", "name": "SK하이닉스", "kind": "관심"},
    {"code": "005380", "name": "현대차", "kind": "관심"},
    {"code": "035420", "name": "NAVER", "kind": "관심"},
]

def _quote(symbol, range_="5d", interval="1d"):
    response = requests.get(YAHOO_CHART_URL.format(symbol=symbol), params={"range": range_, "interval": interval}, headers={"User-Agent": "Mozilla/5.0"}, timeout=(5, 10))
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result.get("timestamp") or []
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    points = [(ts, close) for ts, close in zip(timestamps, closes) if close is not None]
    if not points:
        raise ValueError(f"no data: {symbol}")
    ts, close = points[-1]
    previous = points[-2][1] if len(points) > 1 else meta.get("previousClose")
    change = close - previous if previous is not None else None
    pct = change / previous * 100 if previous not in (None, 0) and change is not None else None
    return {"symbol": symbol, "price": float(close), "change": float(change) if change is not None else None, "pct": float(pct) if pct is not None else None, "timestamp": ts}

def _yahoo_symbol(stock):
    code = str(stock.get("code", "")).strip()
    if code.startswith("pending-"):
        return None
    if code.isdigit() and len(code) == 6:
        return code + ".KS"
    if "." in code or "=" in code or code.startswith("^"):
        return code
    return None

@st.cache_data(ttl=60, show_spinner=False)
def _sparkline_points(symbol, range_, interval):
    response = requests.get(YAHOO_CHART_URL.format(symbol=symbol), params={"range": range_, "interval": interval}, headers={"User-Agent": "Mozilla/5.0"}, timeout=(5, 10))
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    return [float(v) for _, v in zip(timestamps, closes) if v is not None]

def _sparkline_svg(values, width=150, height=34):
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo or 1
    points = []
    for i, value in enumerate(values):
        x = 2 + (width - 4) * i / (len(values) - 1)
        y = height - 3 - (height - 6) * (value - lo) / span
        points.append(f"{x:.1f},{y:.1f}")
    stroke = "#16a34a" if values[-1] >= values[0] else "#dc2626"
    point_text = " ".join(points)
    return f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"><polyline fill="none" stroke="{stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="{point_text}"/></svg>'

def _watchlist_quote(stock):
    symbol = _yahoo_symbol(stock)
    if not symbol:
        return None, None
    candidates = [symbol]
    if symbol.endswith(".KS"):
        candidates.append(symbol[:-3] + ".KQ")
    for candidate in candidates:
        try:
            quote = _quote(candidate)
            charts = {
                "1일": _sparkline_points(candidate, "1d", "5m"),
                "1주": _sparkline_points(candidate, "5d", "30m"),
                "1개월": _sparkline_points(candidate, "1mo", "1d"),
            }
            return quote, charts
        except Exception:
            continue
    return None, None

@st.cache_data(ttl=60, show_spinner=False)
def fetch_macro():
    symbols = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "USD/KRW": "KRW=X", "JPY/KRW": "JPYKRW=X", "EUR/KRW": "EURKRW=X", "GOLD/USD": "GC=F", "WTI": "CL=F", "US10Y": "^TNX", "DXY": "DX-Y.NYB"}
    data = {label: _quote(symbol) for label, symbol in symbols.items()}
    data["GOLD/KRW_G"] = {"price": data["GOLD/USD"]["price"] * data["USD/KRW"]["price"] / 31.1034768, "change": None, "pct": data["GOLD/USD"]["pct"], "timestamp": data["GOLD/USD"]["timestamp"]}
    return data

def _change_text(item, digits=2):
    if item.get("change") is None or item.get("pct") is None:
        return "변동률 확인 필요"
    return f"{item['change']:+.{digits}f} ({item['pct']:+.2f}%)"

def _metric_row(data, labels, value_digits=2):
    for label in labels:
        item = data[label]
        cols = st.columns([1.7, 1.5, 2])
        cols[0].markdown(f"**{label}**")
        cols[1].write(f"{item['price']:,.{value_digits}f}")
        cols[2].write(_change_text(item))

def _watch_status(stock, price):
    target = stock.get("target_price")
    stop = stock.get("stop_price")
    try:
        target = float(target) if target not in (None, "") else None
        stop = float(stop) if stop not in (None, "") else None
    except (TypeError, ValueError):
        target, stop = None, None
    if target and price >= target:
        return "target"
    if stop and price <= stop:
        return "stop"
    return "normal"

def _watch_status_text(status):
    return {"target": "🎯 목표가격 도달", "stop": "🛑 손절가격 도달", "normal": ""}[status]

def _watch_distance(stock, price):
    try:
        target = float(stock.get("target_price")) if stock.get("target_price") not in (None, "") else None
        stop = float(stock.get("stop_price")) if stock.get("stop_price") not in (None, "") else None
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    target_pct = (target / price - 1) * 100 if target and target > 0 else None
    stop_pct = (stop / price - 1) * 100 if stop and stop > 0 else None
    position = None
    if target and stop and target > stop:
        position = max(0.0, min(1.0, (price - stop) / (target - stop)))
    return {"target_pct": target_pct, "stop_pct": stop_pct, "position": position, "target": target, "stop": stop}

def _watch_risk_reward(distance):
    if not distance:
        return None
    target_pct = distance.get("target_pct")
    stop_pct = distance.get("stop_pct")
    if target_pct is None or stop_pct is None:
        return None
    upside = target_pct
    downside = abs(stop_pct)
    if upside <= 0 or downside <= 0:
        return None
    return upside / downside

def _watch_nearest_label(distance):
    if not distance:
        return None
    target_pct = distance.get("target_pct")
    stop_pct = distance.get("stop_pct")
    if target_pct is None and stop_pct is None:
        return None
    target_dist = abs(target_pct) if target_pct is not None else float("inf")
    stop_dist = abs(stop_pct) if stop_pct is not None else float("inf")
    if target_dist == float("inf"):
        return "🛑 손절만 설정"
    if stop_dist == float("inf"):
        return "🎯 목표만 설정"
    if target_dist < stop_dist:
        return "🎯 목표가 더 가까움"
    if stop_dist < target_dist:
        return "🛑 손절가 더 가까움"
    return "↔️ 목표·손절 거리 동일"

def _render_distance_gauge(distance):
    if not distance:
        return
    target_pct = distance["target_pct"]
    stop_pct = distance["stop_pct"]
    position = distance["position"]
    if position is None:
        if target_pct is not None:
            st.caption(f"🎯 목표까지 {target_pct:+.1f}%")
        if stop_pct is not None:
            st.caption(f"🛑 손절까지 {stop_pct:+.1f}%")
        return
    st.markdown(
        f'''
        <div style="margin:2px 0 8px 0;">
          <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;">
            <span>🛑 {distance["stop"]:,.0f}원 ({stop_pct:+.1f}%)</span>
            <b>현재가 위치 {position*100:.0f}%</b>
            <span>🎯 {distance["target"]:,.0f}원 ({target_pct:+.1f}%)</span>
          </div>
          <div style="position:relative;height:12px;background:linear-gradient(90deg,#fee2e2 0%,#f3f4f6 50%,#dcfce7 100%);border-radius:999px;border:1px solid #e5e7eb;">
            <div style="position:absolute;left:calc({position*100:.2f}% - 7px);top:-4px;width:14px;height:20px;background:#111827;border-radius:7px;box-shadow:0 1px 3px rgba(0,0,0,.25);"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:11px;color:#6b7280;margin-top:3px;">
            <span>손절 영역</span><span>현재가</span><span>목표 영역</span>
          </div>
        </div>
        ''',
        unsafe_allow_html=True,
    )

def _render_watchlist(stock_list):
    if not stock_list:
        st.info("관심종목이 없습니다. 아래에서 종목을 추가해 주세요.")
        return
    previous = st.session_state.setdefault("watch_alert_status", {})
    for stock in stock_list:
        quote, charts = _watchlist_quote(stock)
        status = _watch_status(stock, quote["price"]) if quote else "normal"
        key = str(stock.get("code") or stock.get("name"))
        if status != "normal" and previous.get(key) != status:
            st.toast(f"{stock.get('name', '')}: {_watch_status_text(status)}", icon="🎯" if status == "target" else "🛑")
        previous[key] = status
        if status == "target":
            bg, border = "#ecfdf5", "#16a34a"
        elif status == "stop":
            bg, border = "#fef2f2", "#dc2626"
        else:
            bg, border = "#ffffff", "#e5e7eb"
        with st.container(border=True):
            st.markdown(
                f'<div style="border-left:5px solid {border};background:{bg};padding:8px 10px;border-radius:6px;">'
                f'<strong>{escape(stock["name"])}</strong> · {escape(str(stock.get("code", "")))}'
                + (f' · <b>{_watch_status_text(status)}</b>' if status != "normal" else "")
                + "</div>",
                unsafe_allow_html=True,
            )
            left, mid, right = st.columns([1.25, 1.1, 2.7])
            with left:
                target = stock.get("target_price")
                stop = stock.get("stop_price")
                targets = []
                if target not in (None, ""):
                    targets.append(f"목표 ₩{float(target):,.0f}")
                if stop not in (None, ""):
                    targets.append(f"손절 ₩{float(stop):,.0f}")
                st.caption(" · ".join(targets) if targets else "목표/손절가격 미설정")
            with mid:
                if quote:
                    st.write(f"₩{quote['price']:,.0f}")
                    st.caption(_change_text(quote, 0))
                    distance = _watch_distance(stock, quote["price"])
                    if distance:
                        d1, d2, d3 = st.columns(3)
                        with d1:
                            if distance["target_pct"] is not None:
                                st.metric("🎯 목표 예상수익률", f"{distance['target_pct']:+.1f}%")
                        with d2:
                            rr = _watch_risk_reward(distance)
                            if rr is not None:
                                st.metric("⚖️ 손익비 R:R", f"1 : {rr:.2f}")
                            elif distance["stop_pct"] is not None:
                                st.metric("🛑 손절까지", f"{distance['stop_pct']:+.1f}%")
                        with d3:
                            nearest = _watch_nearest_label(distance)
                            if nearest:
                                st.metric("📍 거리 비교", nearest)
                        _render_distance_gauge(distance)
                else:
                    st.caption("시세 확인 필요")
            with right:
                if charts:
                    chart_cols = st.columns(3)
                    for col, label in zip(chart_cols, ("1일", "1주", "1개월")):
                        with col:
                            st.caption(label)
                            svg = _sparkline_svg(charts.get(label, []))
                            st.markdown(svg if svg else "—", unsafe_allow_html=bool(svg))
                else:
                    st.caption("종목코드가 없거나 시세 제공처에서 데이터를 찾지 못했습니다.")


def render_macro_snapshot(watchlist=None):
    st.subheader("시장 한눈에 보기")
    try:
        data = fetch_macro()
        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                st.markdown("### 📈 국내 지수")
                _metric_row(data, ("KOSPI", "KOSDAQ"))
                st.caption("Yahoo Finance · 지연 시세")
        with c2:
            with st.container(border=True):
                st.markdown("### 💱 환율 · 달러")
                _metric_row(data, ("USD/KRW", "JPY/KRW", "EUR/KRW"))
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
                _render_watchlist(watchlist or [])
                st.caption("관심종목은 대시보드에서 직접 추가·삭제할 수 있습니다.")
        updated = datetime.fromtimestamp(data["KOSPI"]["timestamp"], tz=ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
        st.caption(f"마지막 데이터 시각: {updated} · 시세/차트 캐시 약 60초")
    except Exception:
        with st.container(border=True):
            st.warning("시장 시세를 일부 또는 전체 불러오지 못했습니다.")
            st.caption("외부 시세 제공 서버가 일시적으로 응답하지 않을 수 있습니다. 잠시 후 새로고침하세요.")
