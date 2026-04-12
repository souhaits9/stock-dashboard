import streamlit as st
import requests
import pandas as pd
from bs4 import BeautifulSoup
import json
import os

# ── 파일 저장/불러오기 ────────────────────────────────────
SAVE_FILE = "stocks_data.json"

def load_stocks():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_stocks(stocks):
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)

# ── 네이버 금융에서 현재가 조회 ──────────────────────────
def get_current_price(code):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        price = soup.select_one(".today .blind")
        if price:
            return int(price.text.replace(",", ""))
        return 0
    except:
        return 0

# ── 종목코드 검색 (네이버 자동완성) ──────────────────────
def search_stock(name):
    try:
        url = f"https://ac.finance.naver.com/ac?q={name}&q_enc=UTF-8&target=stock"
        res = requests.get(url)
        data = res.json()
        results = []
        for item in data.get("items", [[]])[0]:
            results.append({"name": item[0], "code": item[1]})
        return results
    except:
        return []

# ── 페이지 설정 ───────────────────────────────────────────
st.set_page_config(page_title="내 자산 관리", page_icon="📊", layout="wide")
st.title("📊 내 자산 관리 대시보드")

# ── 세션 초기화 (파일에서 불러오기) ──────────────────────
if "stocks" not in st.session_state:
    st.session_state.stocks = load_stocks()

# ════════════════════════════════════════════════════════
# 사이드바: 종목 추가
# ════════════════════════════════════════════════════════
with st.sidebar:
    st.header("➕ 종목 추가")

    search_query = st.text_input("종목명 검색", placeholder="예: 삼성전자")
    selected_code = ""
    selected_name = ""

    if search_query:
        results = search_stock(search_query)
        if results:
            options = {f"{r['name']} ({r['code']})": r for r in results[:5]}
            chosen = st.selectbox("종목 선택", list(options.keys()))
            if chosen:
                selected_code = options[chosen]["code"]
                selected_name = options[chosen]["name"]
        else:
            st.warning("검색 결과가 없습니다.")
            st.caption("종목코드를 직접 입력하세요")
            selected_code = st.text_input("종목코드 (6자리)", placeholder="005930")
            selected_name = st.text_input("종목명", placeholder="삼성전자")

    qty = st.number_input("보유 수량 (주)", min_value=1, value=1, step=1)
    buy_price = st.number_input("매입 단가 (원)", min_value=1, value=10000, step=100)

    if st.button("➕ 추가", use_container_width=True):
        if selected_code and selected_name:
            existing = [s for s in st.session_state.stocks if s["code"] == selected_code]
            if existing:
                st.warning(f"{selected_name}은 이미 추가되어 있습니다.")
            else:
                st.session_state.stocks.append({
                    "name": selected_name,
                    "code": selected_code,
                    "qty": qty,
                    "buy_price": buy_price
                })
                save_stocks(st.session_state.stocks)  # 파일에 저장
                st.success(f"{selected_name} 추가 완료!")
                st.rerun()
        else:
            st.error("종목을 먼저 검색해 주세요.")

    st.divider()
    if st.button("🔄 현재가 새로고침", use_container_width=True):
        st.rerun()

# ════════════════════════════════════════════════════════
# 메인 화면
# ════════════════════════════════════════════════════════
if not st.session_state.stocks:
    st.info("👈 왼쪽 사이드바에서 보유 종목을 추가해 주세요!")
else:
    rows = []
    total_buy = 0
    total_eval = 0

    with st.spinner("현재가 조회 중..."):
        for s in st.session_state.stocks:
            cur = get_current_price(s["code"])
            buy_total = s["qty"] * s["buy_price"]
            eval_total = s["qty"] * cur
            profit = eval_total - buy_total
            rate = (profit / buy_total * 100) if buy_total else 0
            total_buy += buy_total
            total_eval += eval_total
            rows.append({
                "종목명": s["name"],
                "종목코드": s["code"],
                "수량": s["qty"],
                "매입단가": s["buy_price"],
                "현재가": cur,
                "매입금액": buy_total,
                "평가금액": eval_total,
                "평가손익": profit,
                "수익률(%)": round(rate, 2)
            })

    total_profit = total_eval - total_buy
    total_rate = (total_profit / total_buy * 100) if total_buy else 0

    # ── 상단 요약 카드 ──
    col1, col2, col3 = st.columns(3)
    col1.metric("💰 총 매입금액", f"{total_buy:,}원")
    col2.metric("📈 총 평가금액", f"{total_eval:,}원")
    col3.metric(
        "💹 총 수익",
        f"{total_profit:,}원",
        delta=f"{total_rate:.2f}%"
    )

    st.divider()

    # ── 종목별 카드 ──
    st.subheader("📋 보유 종목")
    for i, row in enumerate(rows):
        profit = row["평가손익"]
        rate = row["수익률(%)"]
        emoji = "🟢" if profit >= 0 else "🔴"

        with st.expander(f"{emoji} {row['종목명']}  |  현재가: {row['현재가']:,}원  |  수익률: {rate:+.2f}%"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("보유수량", f"{row['수량']:,}주")
            c2.metric("매입단가", f"{row['매입단가']:,}원")
            c3.metric("평가손익", f"{profit:,}원", delta=f"{rate:+.2f}%")
            c4.metric("평가금액", f"{row['평가금액']:,}원")

            if st.button(f"🗑️ {row['종목명']} 삭제", key=f"del_{i}"):
                st.session_state.stocks = [
                    s for s in st.session_state.stocks
                    if s["code"] != row["종목코드"]
                ]
                save_stocks(st.session_state.stocks)  # 파일에 저장
                st.rerun()

    st.divider()

    # ── 전체 테이블 ──
    st.subheader("📑 전체 현황표")
    df = pd.DataFrame(rows)
    df_display = df[["종목명", "수량", "매입단가", "현재가", "매입금액", "평가금액", "평가손익", "수익률(%)"]].copy()
    df_display["매입단가"] = df_display["매입단가"].apply(lambda x: f"{x:,}")
    df_display["현재가"] = df_display["현재가"].apply(lambda x: f"{x:,}")
    df_display["매입금액"] = df_display["매입금액"].apply(lambda x: f"{x:,}")
    df_display["평가금액"] = df_display["평가금액"].apply(lambda x: f"{x:,}")
    df_display["평가손익"] = df_display["평가손익"].apply(lambda x: f"{x:+,}")
    df_display["수익률(%)"] = df_display["수익률(%)"].apply(lambda x: f"{x:+.2f}%")
    st.dataframe(df_display, use_container_width=True, hide_index=True)