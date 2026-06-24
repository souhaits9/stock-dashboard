import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
import datetime
import re
import logging

# 로깅 설정 (터미널 및 스트림릿 로그에서 에러 추적 가능)
logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")

# ── 페이지 설정
st.set_page_config(page_title="내 자산 관리 대시보드", page_icon="📊", layout="wide")

# ── 다크 테마 (Linear/Notion 스타일) 색상 토큰
THEME = {
    "canvas": "#0a0a0b",
    "surface_1": "#141516",
    "surface_2": "#191a1b",
    "hairline": "#23252a",
    "hairline_strong": "#34343a",
    "ink": "#f7f8f8",
    "ink_muted": "#d0d6e0",
    "ink_subtle": "#8a8f98",
    "primary": "#5e6ad2",
    "primary_hover": "#828fff",
    "rise": "#e5484d",
    "fall": "#5e9bd2",
}

# ── 커스텀 CSS (Linear/Notion 스타일 다크 테마)
st.html(f"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
html, body, [class*="css"] {{
    font-family: 'Pretendard', 'Inter', -apple-system, system-ui, 'Malgun Gothic', sans-serif !important;
}}

.stApp {{
    background-color: {THEME['canvas']};
}}

h1, h2, h3 {{
    letter-spacing: -0.5px;
    font-weight: 600;
}}

div[data-testid="stMetric"] {{
    background-color: {THEME['surface_1']};
    border: 1px solid {THEME['hairline']};
    border-radius: 12px;
    padding: 16px 20px;
}}

div[data-testid="stMetricLabel"] {{
    color: {THEME['ink_subtle']};
}}

div[data-testid="stMetricValue"] {{
    color: {THEME['ink']};
}}

div[data-testid="stExpander"] {{
    background-color: {THEME['surface_1']};
    border: 1px solid {THEME['hairline']};
    border-radius: 12px;
}}

div[data-testid="stDataFrame"] {{
    border: 1px solid {THEME['hairline']};
    border-radius: 8px;
}}

div[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: 12px;
}}

hr {{
    border-color: {THEME['hairline']} !important;
}}

div[data-testid="stButton"] button {{
    background-color: {THEME['surface_1']};
    color: {THEME['ink']};
    border: 1px solid {THEME['hairline']};
    border-radius: 8px;
}}

div[data-testid="stButton"] button:hover {{
    border-color: {THEME['primary']};
    color: {THEME['primary_hover']};
}}

div[data-testid="stTabs"] button[aria-selected="true"] {{
    color: {THEME['primary_hover']};
    border-bottom-color: {THEME['primary']} !important;
}}

div[data-baseweb="select"] > div {{
    background-color: {THEME['surface_1']};
    border-color: {THEME['hairline']};
}}
</style>
""")

# ── Plotly 다크 테마 공통 레이아웃
DARK_LAYOUT = dict(
    paper_bgcolor=THEME["canvas"],
    plot_bgcolor=THEME["canvas"],
    font=dict(color=THEME["ink_muted"], family="Pretendard, Inter, sans-serif"),
)

PALETTE = ["#5e6ad2", "#828fff", "#8a8f98", "#27a644", "#bbb8b1", "#3e3e44", "#a3a8f0", "#62666d"]

# ── 구글 API 클라이언트 캐싱
@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    return gspread.authorize(creds)

# ① 스프레드시트 개체 캐싱으로 open_by_url() 중복 호출 해결
@st.cache_resource
def get_spreadsheet():
    client = get_gspread_client()
    try:
        sheet_url = st.secrets["SHEET_URL"]
    except Exception as e:
        logging.warning(f"SHEET_URL 수집 방식 전환 (GCP 어카운트 내부 확인): {e}")
        sheet_url = st.secrets["gcp_service_account"]["SHEET_URL"]
    return client.open_by_url(sheet_url)

def get_worksheet(sheet_name):
    spreadsheet = get_spreadsheet()
    return spreadsheet.worksheet(sheet_name)

# ── 데이터 불러오기 (현기준 탭 A~J열)
@st.cache_data(ttl=300)
def load_data():
    sheet = get_worksheet("현기준")
    all_values = sheet.get_all_values()
    if not all_values:
        return pd.DataFrame()

    headers = all_values[0][:10]   # A~J 열만
    rows = [r[:10] for r in all_values[1:]]
    df = pd.DataFrame(rows, columns=headers)
    df.columns = df.columns.str.strip()

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

# ── 자산배분 데이터 로딩 (현기준 탭 M~P열)
@st.cache_data(ttl=300)
def load_allocation():
    try:
        sheet = get_worksheet("현기준")
        values = sheet.get("M18:P30", value_render_option="UNFORMATTED_VALUE")
        rows = []
        for row in values:
            if len(row) >= 3 and row[0] not in ["", "구분", "총액"]:
                try:
                    name = str(row[0]).strip()
                    amount = float(str(row[1]).replace(",", "")) if row[1] != "" else 0
                    current_pct = float(str(row[2]).replace(",", "")) if len(row) > 2 and row[2] != "" else 0
                    target_pct = float(str(row[3]).replace(",", "")) if len(row) > 3 and row[3] != "" else 0
                    if name and amount > 0:
                        rows.append({
                            "구분": name,
                            "금액": amount,
                            "현재비율": current_pct,
                            "목표비율": target_pct,
                            "차이": round(current_pct - target_pct, 2)
                        })
                except Exception as e:
                    # ② 에러 로그 추가 후 continue
                    logging.error(f"자산배분 개별 행 파싱 실패: {e}")
                    continue
        return rows
    except Exception as e:
        # ② 에러 로그 추가 후 빈 리스트 리턴
        logging.error(f"자산배분 데이터 로드 실패: {e}")
        return []

# ── summary 탭 로딩 (연간/월간 수익률)
@st.cache_data(ttl=60)
def load_summary():
    try:
        sheet = get_worksheet("summary")
        all_values = sheet.get(value_render_option="UNFORMATTED_VALUE")
        return all_values
    except Exception as e:
        # ② 에러 로그 추가 후 빈 리스트 리턴
        logging.error(f"Summary 시트 로드 실패: {e}")
        return []

def get_period_returns(summary_values, current_eval):
    now = datetime.datetime.now()
    current_year = now.year
    current_month = now.month

    year_asset = {}
    current_year_val = None
    for row in summary_values[9:]: 
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
        except Exception as e:
            # ② 에러 로그 추가 후 continue
            logging.error(f"기간별 수익률 행 계산 실패: {e}")
            continue

    ytd_rate = None
    prev_year_dec = year_asset.get((current_year - 1, 12))
    if prev_year_dec and prev_year_dec > 0:
        ytd_change = current_eval - prev_year_dec
        ytd_rate = ytd_change / prev_year_dec * 100

    mtd_rate = None
    prev_month = current_month - 1 if current_month > 1 else 12
    prev_month_year = current_year if current_month > 1 else current_year - 1
    prev_month_asset = year_asset.get((prev_month_year, prev_month))
    if prev_month_asset and prev_month_asset > 0:
        mtd_change = current_eval - prev_month_asset
        mtd_rate = mtd_change / prev_month_asset * 100

    return ytd_rate, mtd_rate, prev_year_dec, prev_month_asset

# ③ 월별 데이터 파싱 로직을 별도 함수로 분리
def parse_monthly_data(summary_values):
    monthly_data = []
    current_year = None
    
    for row in summary_values[9:]: 
        if len(row) < 2:
            continue

        year_raw = row[0]
        if year_raw != "" and year_raw is not None and str(year_raw).strip() != "":
            year_clean = str(year_raw).strip().replace("년", "").strip()
            year_digits = re.sub(r"[^0-9]", "", year_clean)
            if year_digits:
                try:
                    current_year = int(year_digits)
                except Exception as e:
                    logging.error(f"연도 변환 실패 ({year_digits}): {e}")

        if current_year is None:
            continue

        try:
            month = int(float(str(row[1]).replace("월", "").strip()))
        except Exception as e:
            logging.error(f"월 데이터 변환 실패 ({row[1]}): {e}")
            continue

        asset = 0
        if len(row) > 2 and row[2] != "":
            try:
                asset = float(str(row[2]).replace(",", ""))
            except Exception as e:
                logging.error(f"자산 데이터 변환 실패 ({row[2]}): {e}")
                asset = 0

        profit = 0
        if len(row) > 3 and row[3] != "":
            try:
                profit = float(str(row[3]).replace(",", ""))
            except Exception as e:
                logging.error(f"수익금 데이터 변환 실패 ({row[3]}): {e}")
                profit = 0

        rate = 0.0
        if len(row) > 4 and row[4] != "":
            try:
                rate = float(str(row[4]).replace(",", ""))
            except Exception as e:
                logging.error(f"수익률 데이터 변환 실패 ({row[4]}): {e}")
                rate = 0.0

        if asset > 0:
            monthly_data.append({
                "연월": f"{current_year}년 {month:02d}월",
                "연도": current_year,
                "월": month,
                "자산": asset,
                "수익금": profit,
                "수익률": rate,
            })
            
    return monthly_data


# ══════════════════════════════════════════════
# 메인 대시보드 로직
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
    st.error(f"구글 시트 연결에 실패했습니다. Secrets 설정 및 네트워크를 확인하세요. 에러명: {e}")
    st.stop()

# ── 데이터 전처리
df["계좌"] = df["계좌"].replace("", pd.NA).ffill()
df["연금총액"] = df["연금총액"].replace("", pd.NA)

acct_total_map = {}
for _, row in df.iterrows():
    acct = row["계좌"]
    val = str(row.get("연금총액", "")).replace(",", "").strip()
    if val and val != "nan" and acct not in acct_total_map:
        try:
            acct_total_map[acct] = float(val)
        except Exception as e:
            logging.error(f"계좌별 연금총액 매핑 실패: {e}")

df = df[
    df["종목"].notna() &
    (df["종목"].str.strip() != "") &
    (~df["종목"].str.strip().isin(["안전자산비율", "현금1"]))
].copy()

for col in ["주식수", "현재주식가격", "현재가치", "연금총액", "가격변동", "자산변동"]:
    df[col] = pd.to_numeric(
        df[col].astype(str).str.replace(",", "").str.replace(" ", ""),
        errors="coerce"
    ).fillna(0)

df["실시간가격"] = df["현재주식가격"]
df["실시간가치"] = df["주식수"] * df["실시간가격"]

mask = df["현재가치"] > 0
df.loc[mask, "실시간가치"] = df.loc[mask, "현재가치"]

account_totals = acct_total_map

# ── 상단 요약 카드 데이터 계산
total_eval = df["실시간가치"].sum()
today_change = df["자산변동"].sum()
today_rate = (today_change / (total_eval - today_change) * 100) if (total_eval - today_change) else 0

summary_values = load_summary()
ytd_rate, mtd_rate, prev_year_dec, prev_month_asset = get_period_returns(summary_values, total_eval)

st.divider()

# ── 1행: 카드(좌) + 계좌별 비중 및 자산배분(우)
top_left, top_right = st.columns([1, 3])

with top_left:
    st.metric("📈 총 평가금액", f"{total_eval:,.0f}원")
    st.metric("📅 오늘 자산변동", f"{today_change:+,.0f}원", delta=f"{today_rate:+.2f}%")
    if ytd_rate is not None:
        ytd_change = total_eval - prev_year_dec
        st.metric("📆 올해 수익률", f"{ytd_rate:+.2f}%", delta=f"{ytd_change:+,.0f}원", help=f"작년 12월말 자산: {prev_year_dec:,.0f}원")
    else:
        st.metric("📆 올해 수익률", "데이터 없음")
    if mtd_rate is not None:
        mtd_change = total_eval - prev_month_asset
        st.metric("📅 이번달 수익률", f"{mtd_rate:+.2f}%", delta=f"{mtd_change:+,.0f}원", help=f"전달 말 자산: {prev_month_asset:,.0f}원")
    else:
        st.metric("📅 이번달 수익률", "데이터 없음")

with top_right:
    pie_col, alloc_col = st.columns([1.2, 1.8])

    with pie_col:
        st.subheader("🥧 계좌별 자산 비중")
        acct_df = df.groupby("계좌")["실시간가치"].sum().reset_index()
        acct_df = acct_df[acct_df["실시간가치"] > 0]
        fig_pie = px.pie(
            acct_df, values="실시간가치", names="계좌", hole=0.4,
            color_discrete_sequence=PALETTE
        )
        fig_pie.update_traces(
            textposition="inside", textinfo="percent+label",
            textfont=dict(color=THEME["ink"]),
            marker=dict(line=dict(color=THEME["canvas"], width=2)),
            hovertemplate="%{label}<br>%{value:,.0f}원<br>%{percent}"
        )
        fig_pie.update_layout(**DARK_LAYOUT, margin=dict(t=20, b=20, l=20, r=20), height=400)
        st.plotly_chart(fig_pie, use_container_width=True)

    with alloc_col:
        st.subheader("🎯 자산배분 현황")
        alloc_data = load_allocation()
        if alloc_data:
            alloc_df = pd.DataFrame(alloc_data)
            fig_alloc = go.Figure()

            bar_colors = [THEME["rise"] if row["차이"] > 0 else THEME["primary"] for _, row in alloc_df.iterrows()]
            fig_alloc.add_trace(go.Bar(
                name="현재", x=alloc_df["구분"], y=alloc_df["현재비율"],
                marker_color=bar_colors, opacity=0.9,
                text=alloc_df["현재비율"].apply(lambda x: f"{x:.1f}%"),
                textposition="outside", textfont=dict(size=11, color=THEME["ink"], family="Pretendard"),
            ))

            for _, row in alloc_df.iterrows():
                idx = alloc_df[alloc_df["구분"] == row["구분"]].index[0]
                fig_alloc.add_trace(go.Scatter(
                    x=[row["구분"]], y=[row["목표비율"]], mode="markers+text",
                    marker=dict(symbol="line-ew", size=30, color=THEME["ink_subtle"], line=dict(width=3, color=THEME["ink_subtle"])),
                    text=f"{row['목표비율']:.0f}%", textposition="top center",
                    textfont=dict(size=10, color=THEME["ink_subtle"]), name="목표" if idx == 0 else "",
                    showlegend=(idx == 0), legendgroup="목표",
                ))

            fig_alloc.update_layout(
                **DARK_LAYOUT,
                height=420, margin=dict(t=30, b=20, l=20, r=20),
                legend=dict(orientation="h", x=0.5, y=1.08, xanchor="center", font=dict(color=THEME["ink_muted"])),
                yaxis=dict(title="비율(%)", ticksuffix="%", gridcolor=THEME["hairline"]),
                xaxis=dict(tickangle=-30, gridcolor=THEME["hairline"]),
                showlegend=True,
            )
            st.plotly_chart(fig_alloc, use_container_width=True)
        else:
            st.info("자산배분 데이터를 불러올 수 없습니다.")

st.divider()

# ── 2행: 실시간 평가금액(좌) + 자산변동(우)
col2, col3 = st.columns(2)

with col2:
    st.subheader("📊 종목별 실시간 평가금액")
    stock_df = df.groupby("종목")["실시간가치"].sum().reset_index()
    stock_df = stock_df[stock_df["실시간가치"] > 0].sort_values("실시간가치", ascending=True)
    stock_df["표시텍스트"] = stock_df["실시간가치"].apply(lambda x: f"{x/100000000:.1f}억" if x >= 100000000 else f"{x/10000:.0f}만")
    
    fig_bar = px.bar(
        stock_df, x="실시간가치", y="종목", orientation="h",
        color="실시간가치", color_continuous_scale=[THEME["surface_2"], THEME["primary"], THEME["primary_hover"]],
        text="표시텍스트"
    )
    fig_bar.update_traces(
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color=THEME["ink"], size=11, family="Pretendard")
    )
    fig_bar.update_layout(
        **DARK_LAYOUT,
        showlegend=False, coloraxis_showscale=False,
        margin=dict(t=20, b=20, l=20, r=20), height=600, xaxis_title="", yaxis_title="",
        xaxis=dict(gridcolor=THEME["hairline"]), yaxis=dict(gridcolor=THEME["hairline"])
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col3:
    st.subheader("📅 오늘 종목별 자산변동")
    change_df = df.groupby("종목").agg(
        자산변동=("자산변동", "sum"),
        실시간가치=("실시간가치", "sum")
    ).reset_index()
    
    change_df = pd.merge(stock_df["종목"], change_df, on="종목", how="left").fillna(0)
    
    change_df["색상"] = change_df["자산변동"].apply(lambda x: "상승" if x >= 0 else "하락")
    change_df["전일가치"] = change_df["실시간가치"] - change_df["자산변동"]
    change_df["변동률"] = change_df.apply(
        lambda r: r["자산변동"] / r["전일가치"] * 100 if r["전일가치"] > 0 else 0, axis=1
    )
    
    fig_change = px.bar(
        change_df, x="자산변동", y="종목", orientation="h", color="색상",
        color_discrete_map={"상승": THEME["rise"], "하락": THEME["fall"]}
    )
    fig_change.update_traces(text=[""] * len(change_df))

    for _, row in change_df.iterrows():
        label = f"{row['자산변동']:+,.0f}원 ({row['변동률']:+.2f}%)"
        if row["자산변동"] < 0:
            fig_change.add_annotation(
                x=0, y=row["종목"], text=label, xanchor="left", showarrow=False,
                font=dict(color=THEME["fall"], size=11, family="Pretendard"), xshift=8
            )
        else:
            fig_change.add_annotation(
                x=0, y=row["종목"], text=label, xanchor="right", showarrow=False,
                font=dict(color=THEME["rise"], size=11, family="Pretendard"), xshift=-8
            )

    max_abs = change_df["자산변동"].abs().max()
    x_range = [-max_abs * 1.5, max_abs * 1.5] if max_abs > 0 else [-10000, 10000]
    fig_change.update_layout(
        **DARK_LAYOUT,
        showlegend=True, legend=dict(title="", font=dict(color=THEME["ink_muted"])),
        margin=dict(t=20, b=20, l=20, r=20),
        height=600, xaxis_title="", yaxis_title="",
        xaxis=dict(zeroline=True, zerolinewidth=2, zerolinecolor=THEME["hairline_strong"], range=x_range, gridcolor=THEME["hairline"])
    )
    st.plotly_chart(fig_change, use_container_width=True)

st.divider()

# ── 3행: 계좌별 상세 현황 현황표
st.subheader("📋 계좌별 상세 현황")

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
        "data": acct_data, "eval": acct_eval, "invest": acct_invest,
        "profit": acct_profit, "rate": acct_rate, "today": acct_today,
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

for acct, det in acct_details.items():
    acct_eval   = det["eval"]
    acct_invest = det["invest"]
    acct_profit = det["profit"]
    acct_rate   = det["rate"]
    acct_today  = det["today"]
    acct_data   = det["data"]
    emoji       = "🟢" if acct_profit >= 0 else "🔴"

    with st.expander(f"{emoji} {acct}"):
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("📥 투자금액", f"{acct_invest:,.0f}원")
        m2.metric("💰 평가금액", f"{acct_eval:,.0f}원")
        m3.metric("💹 총 수익", f"{acct_profit:,.0f}원", delta=f"{acct_rate:+.2f}%")
        m4.metric("📅 오늘 변동", f"{acct_today:+,.0f}원", delta=f"{acct_today/acct_eval*100:+.2f}%" if acct_eval else None)
        m5.metric("📂 종목 수", f"{len(acct_data)}개")

        display_df = acct_data[["종목", "주식수", "실시간가격", "실시간가치", "자산변동"]].copy()
        display_df.columns = ["종목명", "보유수량", "현재가(원)", "평가금액(원)", "오늘변동(원)"]
        display_df["보유수량"]   = display_df["보유수량"].apply(lambda x: f"{int(x):,}")
        display_df["현재가(원)"] = display_df["현재가(원)"] .apply(lambda x: f"{int(x):,}")
        display_df["평가금액(원)"] = display_df["평가금액(원)"].apply(lambda x: f"{x:,.0f}")
        display_df["오늘변동(원)"] = display_df["오늘변동(원)"].apply(lambda x: f"{x:+,.0f}")
        st.dataframe(display_df, use_container_width=True, hide_index=True)

st.divider()

# ── 4행: 전체 종목 현황표
st.subheader("📑 전체 종목 현황표")
full_df = df[["계좌", "종목", "주식수", "실시간가격", "실시간가치", "자산변동"]].copy()
full_df.columns = ["계좌", "종목명", "보유수량", "현재가(원)", "평가금액(원)", "오늘변동(원)"]
full_df["보유수량"] = full_df["보유수량"].apply(lambda x: f"{int(x):,}")
full_df["현재가(원)"] = full_df["현재가(원)"].apply(lambda x: f"{int(x):,}")
full_df["평가금액(원)"] = full_df["평가금액(원)"].apply(lambda x: f"{x:,.0f}")
full_df["오늘변동(원)"] = full_df["오늘변동(원)"].apply(lambda x: f"{x:+,.0f}")
st.dataframe(full_df, use_container_width=True, hide_index=True)

st.divider()

# ── 5행: 월별 자산 추이 그래프
st.subheader("📈 월별 자산 추이")

if summary_values:
    # ③ 파싱 전용 함수 호출로 코드 간소화 완료
    monthly_data = parse_monthly_data(summary_values)

    if monthly_data:
        mdf = pd.DataFrame(monthly_data)
        mdf = mdf.sort_values(["연도", "월"]).reset_index(drop=True)

        tab1, tab2 = st.tabs(["📊 자산 추이", "📉 월별 수익률"])

        with tab1:
            all_order = mdf["연월"].tolist()
            fig_asset = px.area(
                mdf, x="연월", y="자산", markers=True,
                color_discrete_sequence=[THEME["primary"]],
                labels={"자산": "자산(원)", "연월": ""},
                category_orders={"연월": all_order},
            )
            fig_asset.update_traces(
                hovertemplate="%{x}<br>자산: %{y:,.0f}원",
                line=dict(width=2), marker=dict(size=8, color=THEME["primary_hover"]),
                fillcolor="rgba(94, 106, 210, 0.18)"
            )
            fig_asset.update_layout(
                **DARK_LAYOUT,
                height=400, margin=dict(t=20, b=20, l=20, r=20),
                yaxis=dict(tickformat=",.0f", gridcolor=THEME["hairline"]),
                xaxis=dict(tickangle=-45, categoryorder="array", categoryarray=all_order, gridcolor=THEME["hairline"])
            )
            st.plotly_chart(fig_asset, use_container_width=True)

        with tab2:
            rate_df = mdf.copy()
            month_order = rate_df["연월"].tolist()
            colors = rate_df["수익률"].apply(lambda x: THEME["rise"] if x >= 0 else THEME["fall"]).tolist()

            fig_dual = go.Figure()

            fig_dual.add_trace(go.Bar(
                x=rate_df["연월"], y=rate_df["수익금"], name="수익금",
                marker_color=colors, marker_opacity=0.8, yaxis="y1",
                hovertemplate="%{x}<br>수익금: %{y:,.0f}원<extra></extra>",
            ))

            fig_dual.add_trace(go.Scatter(
                x=rate_df["연월"], y=rate_df["수익률"], name="수익률(%)",
                mode="lines+markers+text", line=dict(color=THEME["ink_subtle"], width=2),
                marker=dict(color=THEME["ink_subtle"], size=6),
                text=rate_df["수익률"].apply(lambda x: f"{x:+.1f}%"),
                textposition="top center", textfont=dict(size=10, color=THEME["ink_muted"]),
                yaxis="y2", hovertemplate="%{x}<br>수익률: %{y:+.2f}%<extra></extra>",
            ))

            max_profit = rate_df["수익금"].abs().max()
            max_rate = rate_df["수익률"].abs().max()

            fig_dual.update_layout(
                **DARK_LAYOUT,
                height=420, margin=dict(t=40, b=60, l=80, r=60),
                xaxis=dict(tickangle=-45, categoryorder="array", categoryarray=month_order, tickfont=dict(size=10), gridcolor=THEME["hairline"]),
                yaxis=dict(
                    title="수익금", tickformat=".1s", showgrid=True,
                    gridcolor=THEME["hairline"], range=[-max_profit * 1.4, max_profit * 1.4],
                    tickfont=dict(size=10),
                ),
                yaxis2=dict(
                    title="수익률(%)", overlaying="y", side="right", showgrid=False,
                    range=[-max_rate * 2.5, max_rate * 2.5], tickfont=dict(size=10), ticksuffix="%",
                ),
                legend=dict(orientation="h", x=0.5, y=1.05, xanchor="center", font=dict(size=11, color=THEME["ink_muted"])),
                shapes=[dict(
                    type="line", yref="y", y0=0, y1=0, xref="paper", x0=0, x1=1,
                    line=dict(color=THEME["hairline_strong"], width=1, dash="dot")
                )],
            )
            st.plotly_chart(fig_dual, use_container_width=True)
    else:
        st.info("summary 탭에 월별 데이터가 없습니다.")
else:
    st.info("summary 탭을 불러올 수 없습니다.")
