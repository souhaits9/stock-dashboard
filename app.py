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

# ── summary 탭 로딩 (연간/월간 수익률)
@st.cache_data(ttl=60)
def load_summary():
    try:
        creds_info = st.secrets["gcp_service_account"]
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        try:
            sheet_url = st.secrets["SHEET_URL"]
        except:
            sheet_url = creds_info["SHEET_URL"]
        sheet = client.open_by_url(sheet_url).worksheet("summary")
        # value_render_option="UNFORMATTED_VALUE" 로 수식 결과값 읽기
        all_values = sheet.get_all_values(value_render_option="UNFORMATTED_VALUE")
        return all_values
    except:
        return []

def get_period_returns(summary_values, current_eval):
    """연간/월간 수익률 계산"""
    import datetime
    now = datetime.datetime.now()
    current_year = now.year
    current_month = now.month

    # 9행(인덱스8)부터 월별 데이터: A=연도, B=월, C=자산
    year_asset = {}   # {(year, month): asset}
    current_year_val = None
    for row in summary_values[9:]:  # 10행부터 데이터
        if len(row) < 3:
            continue
        year_str = str(row[0]).strip()
        month_str = str(row[1]).strip().replace("월", "")
        asset_str = str(row[2]).strip().replace(",", "")
        if year_str:
            current_year_val = year_str
        try:
            year = int(current_year_val.replace("년", "")) if current_year_val else 0
            month = int(month_str)
            asset = float(asset_str) if asset_str else 0
            if asset > 0:
                year_asset[(year, month)] = asset
        except:
            continue

    # 올해 수익률: 작년 12월 자산 대비
    ytd_rate = None
    prev_year_dec = year_asset.get((current_year - 1, 12))
    if prev_year_dec and prev_year_dec > 0:
        ytd_change = current_eval - prev_year_dec
        ytd_rate = ytd_change / prev_year_dec * 100

    # 이번달 수익률: 전달 말 자산 대비
    mtd_rate = None
    prev_month = current_month - 1 if current_month > 1 else 12
    prev_month_year = current_year if current_month > 1 else current_year - 1
    prev_month_asset = year_asset.get((prev_month_year, prev_month))
    if prev_month_asset and prev_month_asset > 0:
        mtd_change = current_eval - prev_month_asset
        mtd_rate = mtd_change / prev_month_asset * 100

    return ytd_rate, mtd_rate, prev_year_dec, prev_month_asset

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
# 1. 계좌명 먼저 채우기 (필터링 전에 해야 병합셀이 올바르게 처리됨)
df["계좌"] = df["계좌"].replace("", pd.NA).ffill()

# 2. 연금총액도 계좌별로 먼저 채우기
df["연금총액"] = df["연금총액"].replace("", pd.NA)
# 계좌별 연금총액 저장 (필터링 전)
acct_total_map = {}
for _, row in df.iterrows():
    acct = row["계좌"]
    val = str(row.get("연금총액", "")).replace(",", "").strip()
    if val and val != "nan" and acct not in acct_total_map:
        try:
            acct_total_map[acct] = float(val)
        except:
            pass

# 3. 불필요한 행 제거
df = df[
    df["종목"].notna() &
    (df["종목"].str.strip() != "") &
    (~df["종목"].str.strip().isin(["안전자산비율", "현금1"]))
].copy()

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

    # 실시간가치가 0이거나 종목코드가 없는 종목은 G열(현재가치) 사용
    # 현재가치는 이미 숫자형으로 변환되어 있음
    mask = (df["실시간가치"] <= 0) | (df["종목코드"].astype(str).str.strip() == "")
    df.loc[mask, "실시간가치"] = df.loc[mask, "현재가치"]
    df.loc[mask, "실시간가격"] = df.loc[mask, "현재주식가격"]

# 계좌별 투자원금 (필터링 전에 저장한 값 사용)
account_totals = acct_total_map

# ── 상단 요약 카드
total_eval = df["실시간가치"].sum()
today_change = df["자산변동"].sum()
today_rate = (today_change / (total_eval - today_change) * 100) if (total_eval - today_change) else 0

# 연간/월간 수익률 계산
summary_values = load_summary()
ytd_rate, mtd_rate, prev_year_dec, prev_month_asset = get_period_returns(summary_values, total_eval)

st.divider()
c1, c2, c3, c4 = st.columns(4)
c1.metric("📈 총 평가금액", f"{total_eval:,.0f}원")
c2.metric("📅 오늘 자산변동", f"{today_change:+,.0f}원", delta=f"{today_rate:+.2f}%")

if ytd_rate is not None:
    ytd_change = total_eval - prev_year_dec
    c3.metric("📆 올해 수익률", f"{ytd_rate:+.2f}%",
              delta=f"{ytd_change:+,.0f}원", help=f"작년 12월말 자산: {prev_year_dec:,.0f}원")
else:
    c3.metric("📆 올해 수익률", "데이터 없음")

if mtd_rate is not None:
    mtd_change = total_eval - prev_month_asset
    c4.metric("📅 이번달 수익률", f"{mtd_rate:+.2f}%",
              delta=f"{mtd_change:+,.0f}원", help=f"전달 말 자산: {prev_month_asset:,.0f}원")
else:
    c4.metric("📅 이번달 수익률", "데이터 없음")

st.divider()

# ── 시각화
col1, col2, col3 = st.columns(3)

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

# 종목별 실시간 평가금액 막대차트
with col2:
    st.subheader("📊 종목별 실시간 평가금액")
    stock_df = df.groupby("종목")["실시간가치"].sum().reset_index()
    stock_df = stock_df[stock_df["실시간가치"] > 0].sort_values("실시간가치", ascending=True)
    total_stock = stock_df["실시간가치"].sum()
    stock_df["표시텍스트"] = stock_df["실시간가치"].apply(
        lambda x: f"{x/100000000:.1f}억"
    )
    fig_bar = px.bar(
        stock_df,
        x="실시간가치",
        y="종목",
        orientation="h",
        color="실시간가치",
        color_continuous_scale="Blues",
        text="표시텍스트"
    )
    fig_bar.update_traces(
        textposition="inside",
        insidetextanchor="middle",
        textfont=dict(color="#FFFF00", size=11, family="Arial Black")
    )
    fig_bar.update_layout(
        showlegend=False,
        coloraxis_showscale=False,
        margin=dict(t=20, b=20, l=20, r=20),
        height=500,
        xaxis_title="",
        yaxis_title=""
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# 오늘 자산변동 차트
with col3:
    st.subheader("📅 오늘 종목별 자산변동")
    change_df = df.groupby("종목").agg(
        자산변동=("자산변동", "sum"),
        실시간가치=("실시간가치", "sum")
    ).reset_index()
    change_df = change_df.set_index("종목").reindex(stock_df["종목"]).reset_index()
    change_df["색상"] = change_df["자산변동"].apply(lambda x: "상승" if x >= 0 else "하락")
    # 변동률 계산 (전일가치 = 실시간가치 - 자산변동)
    change_df["전일가치"] = change_df["실시간가치"] - change_df["자산변동"]
    change_df["변동률"] = change_df.apply(
        lambda r: r["자산변동"] / r["전일가치"] * 100 if r["전일가치"] > 0 else 0, axis=1
    )
    change_df["표시텍스트"] = change_df.apply(
        lambda r: f"{r['자산변동']:+,.0f}원 ({r['변동률']:+.2f}%)", axis=1
    )
    fig_change = px.bar(
        change_df,
        x="자산변동",
        y="종목",
        orientation="h",
        color="색상",
        color_discrete_map={"상승": "#1f77b4", "하락": "#d62728"},
        text="표시텍스트"
    )
    # x축 범위: 좌우 대칭 (0 기준)
    max_abs = change_df["자산변동"].abs().max()
    x_range = [-max_abs * 1.3, max_abs * 1.3]

    fig_change.update_traces(
        textposition="outside",
        textfont=dict(color="#333333", size=13, family="Arial Black")
    )
    fig_change.update_layout(
        showlegend=True,
        legend=dict(title=""),
        margin=dict(t=20, b=20, l=20, r=20),
        height=500,
        xaxis_title="",
        yaxis_title="",
        xaxis=dict(
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor="gray",
            range=x_range
        )
    )
    st.plotly_chart(fig_change, use_container_width=True)

st.divider()

# ── 계좌별 상세 현황
st.subheader("📋 계좌별 상세 현황")

# 계좌 요약 테이블 먼저 표시
summary_rows = []
acct_details = {}
for acct in df["계좌"].unique():
    acct_data = df[df["계좌"] == acct].copy()
    acct_eval = acct_data["실시간가치"].sum()
    acct_invest = account_totals.get(acct, 0)
    acct_profit = acct_eval - acct_invest
    acct_rate = (acct_profit / acct_invest * 100) if acct_invest else 0
    acct_today = acct_data["자산변동"].sum()
    acct_details[acct] = {
        "data": acct_data,
        "eval": acct_eval,
        "invest": acct_invest,
        "profit": acct_profit,
        "rate": acct_rate,
        "today": acct_today,
    }
    today_rate = (acct_today / acct_eval * 100) if acct_eval else 0
    summary_rows.append({
        "계좌": acct,
        "평가금액(원)": f"{acct_eval:,.0f}",
        "오늘변동(원)": f"{acct_today:+,.0f}",
        "오늘변동률": f"{today_rate:+.2f}%",
        "종목수": f"{len(acct_data)}개",
    })

summary_table = pd.DataFrame(summary_rows)
st.dataframe(summary_table, use_container_width=True, hide_index=True)

st.divider()

# 계좌별 상세 펼치기
for acct, det in acct_details.items():
    acct_eval   = det["eval"]
    acct_invest = det["invest"]
    acct_profit = det["profit"]
    acct_rate   = det["rate"]
    acct_today  = det["today"]
    acct_data   = det["data"]
    emoji       = "🟢" if acct_profit >= 0 else "🔴"
    today_emoji = "📈" if acct_today >= 0 else "📉"

    with st.expander(f"{emoji} {acct}"):
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("📥 투자금액", f"{acct_invest:,.0f}원")
        m2.metric("💰 평가금액", f"{acct_eval:,.0f}원")
        m3.metric("💹 총 수익", f"{acct_profit:,.0f}원", delta=f"{acct_rate:+.2f}%")
        m4.metric("📅 오늘 변동", f"{acct_today:+,.0f}원",
                  delta=f"{acct_today/acct_eval*100:+.2f}%" if acct_eval else None)
        m5.metric("📂 종목 수", f"{len(acct_data)}개")

        display_df = acct_data[["종목", "주식수", "실시간가격", "실시간가치", "자산변동"]].copy()
        display_df.columns = ["종목명", "보유수량", "현재가(원)", "평가금액(원)", "오늘변동(원)"]
        display_df["보유수량"]   = display_df["보유수량"].apply(lambda x: f"{int(x):,}")
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

st.divider()

# ── 월별 자산 추이 그래프
st.subheader("📈 월별 자산 추이")

# 디버그: summary 원본값 확인
with st.expander("🔍 summary 원본 데이터 확인 (디버그)"):
    if summary_values:
        st.write(f"총 행 수: {len(summary_values)}")
        st.write("10행 이후 데이터 (월별 자산):")
        for i, row in enumerate(summary_values[9:25], start=10):
            st.write(f"행{i}: {row[:6]}")
    else:
        st.write("summary_values가 비어있음")

# summary 데이터에서 월별 자산 추출
if summary_values:
    monthly_data = []
    current_year_val = None
    for row in summary_values[9:]:  # 10행부터 데이터
        if len(row) < 3:
            continue
        year_str = str(row[0]).strip()
        month_str = str(row[1]).strip().replace("월", "")
        asset_str = str(row[2]).strip().replace(",", "")
        profit_str = str(row[3]).strip().replace(",", "") if len(row) > 3 else ""
        rate_str = str(row[4]).strip().replace(",", "") if len(row) > 4 else ""

        if year_str:
            current_year_val = year_str.replace("년", "")
        try:
            year = int(current_year_val) if current_year_val else 0
            month = int(month_str)
            asset = float(asset_str) if asset_str else 0
            profit = float(profit_str) if profit_str else 0
            rate = float(rate_str) if rate_str else 0
            if asset > 0:
                monthly_data.append({
                    "연월": f"{year}년 {month:02d}월",
                    "연도": year,
                    "월": month,
                    "자산": asset,
                    "수익금": profit,
                    "수익률": rate,  # 나중에 직접 계산으로 덮어씀
                })
        except:
            continue

    if monthly_data:
        mdf = pd.DataFrame(monthly_data)
        mdf = mdf.sort_values(["연도", "월"]).reset_index(drop=True)

        # 구글 시트에 데이터가 있는 마지막 월까지만 사용
        # (현재월 조작 없이 시트 데이터 그대로 사용)
        mdf = mdf.sort_values(["연도", "월"]).reset_index(drop=True)

        # 수익률 직접 계산 (시트 수식 문제 우회)
        for i in range(len(mdf)):
            if i == 0:
                mdf.at[i, "수익률"] = 0
            else:
                prev_asset = mdf.at[i-1, "자산"]
                curr_asset = mdf.at[i, "자산"]
                profit = mdf.at[i, "수익금"]
                if prev_asset > 0:
                    # 수익금이 있으면 수익금/전월자산, 없으면 자산변동률
                    if profit != 0:
                        mdf.at[i, "수익률"] = profit / prev_asset * 100
                    else:
                        mdf.at[i, "수익률"] = (curr_asset - prev_asset) / prev_asset * 100

        tab1, tab2 = st.tabs(["📊 자산 추이", "📉 월별 수익률"])

        with tab1:
            fig_asset = px.area(
                mdf,
                x="연월",
                y="자산",
                markers=True,
                color_discrete_sequence=["#1f77b4"],
                labels={"자산": "자산(원)", "연월": ""},
            )
            fig_asset.update_traces(
                hovertemplate="%{x}<br>자산: %{y:,.0f}원",
                line=dict(width=2),
                marker=dict(size=8)
            )
            fig_asset.update_layout(
                height=400,
                margin=dict(t=20, b=20, l=20, r=20),
                yaxis=dict(tickformat=",.0f"),
                xaxis=dict(tickangle=-45)
            )
            st.plotly_chart(fig_asset, use_container_width=True)

        with tab2:
            # 수익률 막대그래프
            rate_df = mdf[mdf["수익률"] != 0].copy()
            rate_df["색상"] = rate_df["수익률"].apply(lambda x: "상승" if x >= 0 else "하락")
            fig_rate = px.bar(
                rate_df,
                x="연월",
                y="수익률",
                color="색상",
                color_discrete_map={"상승": "#1f77b4", "하락": "#d62728"},
                text=rate_df["수익률"].apply(lambda x: f"{x:+.2f}%"),
                labels={"수익률": "수익률(%)", "연월": ""},
            )
            fig_rate.update_traces(textposition="outside")
            fig_rate.update_layout(
                height=400,
                margin=dict(t=20, b=40, l=20, r=20),
                xaxis=dict(tickangle=-45),
                yaxis=dict(title="수익률(%)"),
                showlegend=True,
                legend=dict(title=""),
                xaxis_title="",
                shapes=[dict(
                    type="line", yref="y", y0=0, y1=0,
                    xref="paper", x0=0, x1=1,
                    line=dict(color="gray", width=1)
                )]
            )
            st.plotly_chart(fig_rate, use_container_width=True)
    else:
        st.info("summary 탭에 월별 데이터가 없습니다.")
else:
    st.info("summary 탭을 불러올 수 없습니다.")
