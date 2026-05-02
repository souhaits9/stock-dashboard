import streamlit as st
import requests
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px

# ── 페이지 설정
st.set_page_config(page_title="내 자산 관리 대시보드", page_icon="📊", layout="wide")

# ── 구글 시트 연결
@st.cache_resource
def get_gsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    client = gspread.authorize(creds)
    try:
        sheet_url = st.secrets["SHEET_URL"]
    except:
        sheet_url = st.secrets["gcp_service_account"]["SHEET_URL"]
    return client.open_by_url(sheet_url).worksheet("현기준")

# ── 데이터 불러오기
@st.cache_data(ttl=300)
def load_data():
    sheet = get_gsheet()
    all_values = sheet.get_all_values()
    if not all_values:
        return pd.DataFrame()

    headers = all_values[0][:10]   # A~J 열만
    rows = [r[:10] for r in all_values[1:]]
    df = pd.DataFrame(rows, columns=headers)

    # 헤더 정리
    df.columns = df.columns.str.strip()

    # 실제 컬럼명 고정 매핑 (A~J)
    col_map = {
        df.columns[0]: "계좌",
        df.columns[1]: "연금총액",
        df.columns[2]: "종목",
        df.columns[3]: "종목코드",
        df.columns[4]: "주식수",
        df.columns[5]: "현재주식가격",
        df.columns[6]: "현재가치",
        df.columns[7]: "가격변동",
        df.columns[8]: "오늘가격변동률",
        df.columns[9]: "자산변동",
    }
    df = df.rename(columns=col_map)
    return df

# ── 네이버 금융 현재가 조회
@st.cache_data(ttl=60)
def get_current_price(code):
    try:
        clean_code = str(code).split(":")[-1].strip()
        clean_code = "".join(filter(str.isdigit, clean_code))
        if not clean_code:
            return 0
        url = f"https://finance.naver.com/item/main.naver?code={clean_code}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        price = soup.select_one(".today .blind")
        return int(price.text.replace(",", "")) if price else 0
    except:
        return 0

# ══════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════
st.title("📊 내 자산 관리 대시보드")

col_refresh, _ = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    df = load_data()
except Exception as e:
    import traceback
    st.error(f"구글 시트 연결 실패: {e}")
    st.code(traceback.format_exc())
    st.stop()

# ── 데이터 전처리
df = df[
    df["종목"].notna() &
    (df["종목"].str.strip() != "") &
    (~df["종목"].str.strip().isin(["안전자산비율", "현금1"]))
].copy()

# 계좌명 앞으로 채우기 (병합셀 처리)
df["계좌"] = df["계좌"].replace("", pd.NA).ffill()

# 숫자형 변환
for col in ["주식수", "현재주식가격", "현재가치", "연금총액", "가격변동", "자산변동"]:
    df[col] = pd.to_numeric(
        df[col].astype(str).str.replace(",", "").str.replace(" ", ""),
        errors="coerce"
    ).fillna(0)

# ── 현재가 자동 조회
with st.spinner("📡 네이버 금융에서 현재가 조회 중..."):
    prices = {}
    for _, row in df.iterrows():
        code = str(row.get("종목코드", ""))
        if code and code not in prices:
            price = get_current_price(code)
            prices[code] = price if price > 0 else int(row.get("현재주식가격", 0))

    df["실시간가격"] = df["종목코드"].astype(str).map(prices)
    df["실시간가치"] = df["주식수"] * df["실시간가격"]

# 계좌별 투자원금
account_totals = {}
for _, row in df.iterrows():
    acct = row["계좌"]
    if acct not in account_totals:
        try:
            account_totals[acct] = float(row.get("연금총액", 0) or 0)
        except:
            account_totals[acct] = 0

# ── 상단 요약 카드
total_eval = df["실시간가치"].sum()
total_invest = sum(account_totals.values())
total_profit = total_eval - total_invest
total_rate = (total_profit / total_invest * 100) if total_invest else 0
today_change = df["자산변동"].sum()

st.divider()
c1, c2, c3, c4 = st.columns(4)
c1.metric("💰 총 투자금액", f"{total_invest:,.0f}원")
c2.metric("📈 총 평가금액", f"{total_eval:,.0f}원")
c3.metric("💹 총 수익", f"{total_profit:,.0f}원", delta=f"{total_rate:.2f}%")
c4.metric("📅 오늘 자산변동", f"{today_change:,.0f}원")

st.divider()

# ── 시각화
col1, col2 = st.columns(2)

# 계좌별 자산 비중 파이차트
with col1:
    st.subheader("🥧 계좌별 자산 비중")
    acct_df = df.groupby("계좌")["실시간가치"].sum().reset_index()
    acct_df = acct_df[acct_df["실시간가치"] > 0]
    fig_pie = px.pie(
        acct_df,
        values="실시간가치",
        names="계좌",
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Set3
    )
    fig_pie.update_traces(
        textposition="inside",
        textinfo="percent+label",
        hovertemplate="%{label}<br>%{value:,.0f}원<br>%{percent}"
    )
    fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=420)
    st.plotly_chart(fig_pie, use_container_width=True)

# 종목별 현재가치 막대차트
with col2:
    st.subheader("📊 종목별 현재가치")
    stock_df = df.groupby("종목")["실시간가치"].sum().reset_index()
    stock_df = stock_df[stock_df["실시간가치"] > 0].sort_values("실시간가치", ascending=True)
    fig_bar = px.bar(
        stock_df,
        x="실시간가치",
        y="종목",
        orientation="h",
        color="실시간가치",
        color_continuous_scale="Blues",
        text=stock_df["실시간가치"].apply(lambda x: f"{x/100000000:.1f}억")
    )
    fig_bar.update_traces(textposition="outside")
    fig_bar.update_layout(
        showlegend=False,
        coloraxis_showscale=False,
        margin=dict(t=20, b=20, l=20, r=80),
        height=420,
        xaxis_title="",
        yaxis_title=""
    )
    st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# ── 계좌별 상세 현황
st.subheader("📋 계좌별 상세 현황")

for acct in df["계좌"].unique():
    acct_data = df[df["계좌"] == acct].copy()
    acct_eval = acct_data["실시간가치"].sum()
    acct_invest = account_totals.get(acct, 0)
    acct_profit = acct_eval - acct_invest
    acct_rate = (acct_profit / acct_invest * 100) if acct_invest else 0
    acct_today = acct_data["자산변동"].sum()
    emoji = "🟢" if acct_profit >= 0 else "🔴"

    with st.expander(f"{emoji} {acct}  |  평가금액: {acct_eval:,.0f}원  |  수익률: {acct_rate:+.2f}%"):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("투자금액", f"{acct_invest:,.0f}원")
        m2.metric("평가금액", f"{acct_eval:,.0f}원")
        m3.metric("총 수익", f"{acct_profit:,.0f}원", delta=f"{acct_rate:+.2f}%")
        m4.metric("오늘 변동", f"{acct_today:,.0f}원")

        display_df = acct_data[["종목", "주식수", "실시간가격", "실시간가치", "자산변동"]].copy()
        display_df.columns = ["종목명", "보유수량", "현재가(원)", "평가금액(원)", "오늘변동(원)"]
        display_df["보유수량"] = display_df["보유수량"].apply(lambda x: f"{int(x):,}")
        display_df["현재가(원)"] = display_df["현재가(원)"].apply(lambda x: f"{int(x):,}")
        display_df["평가금액(원)"] = display_df["평가금액(원)"].apply(lambda x: f"{x:,.0f}")
        display_df["오늘변동(원)"] = display_df["오늘변동(원)"].apply(lambda x: f"{x:+,.0f}")
        st.dataframe(display_df, use_container_width=True, hide_index=True)

st.divider()

# ── 전체 종목 현황표
st.subheader("📑 전체 종목 현황표")
full_df = df[["계좌", "종목", "주식수", "실시간가격", "실시간가치", "자산변동"]].copy()
full_df.columns = ["계좌", "종목명", "보유수량", "현재가(원)", "평가금액(원)", "오늘변동(원)"]
full_df["보유수량"] = full_df["보유수량"].apply(lambda x: f"{int(x):,}")
full_df["현재가(원)"] = full_df["현재가(원)"].apply(lambda x: f"{int(x):,}")
full_df["평가금액(원)"] = full_df["평가금액(원)"].apply(lambda x: f"{x:,.0f}")
full_df["오늘변동(원)"] = full_df["오늘변동(원)"].apply(lambda x: f"{x:+,.0f}")
st.dataframe(full_df, use_container_width=True, hide_index=True)
