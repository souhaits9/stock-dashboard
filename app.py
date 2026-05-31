import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
import datetime
import time

# ── 페이지 설정
st.set_page_config(page_title="내 자산 관리 (실시간)", page_icon="📈", layout="wide")

# ════════════════════════════════════════════════════
# 한국투자증권 KIS API
# ════════════════════════════════════════════════════

@st.cache_data(ttl=3600)  # 토큰 1시간 캐시
def get_kis_token():
    try:
        url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": st.secrets["KIS_APP_KEY"],
            "appsecret": st.secrets["KIS_APP_SECRET"]
        }
        res = requests.post(url, json=body, timeout=10)
        token = res.json().get("access_token")
        if token:
            return token
        return None
    except Exception as e:
        return None

def get_kis_price(token, code):
    """한투 API로 국내주식 현재가 조회"""
    try:
        # 종목코드 정제 (krx:005930 → 005930, 숫자만)
        clean = str(code).split(":")[-1].strip()
        clean = ''.join(filter(str.isdigit, clean))
        if not clean or len(clean) != 6:
            return 0

        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": st.secrets["KIS_APP_KEY"],
            "appsecret": st.secrets["KIS_APP_SECRET"],
            "tr_id": "FHKST01010100",
            "content-type": "application/json"
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": clean
        }
        res = requests.get(url, headers=headers, params=params, timeout=5)
        data = res.json()
        price = int(data["output"]["stck_prpr"])
        return price
    except:
        return 0

# ════════════════════════════════════════════════════
# 구글 시트 연결
# ════════════════════════════════════════════════════

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

@st.cache_data(ttl=300)
def load_data():
    sheet = get_gsheet()
    all_values = sheet.get_all_values()
    if not all_values:
        return pd.DataFrame()

    headers = all_values[0][:10]
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

# ════════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════════

st.title("📈 내 자산 관리 대시보드 (KIS 실시간)")

# 새로고침 버튼
col_btn, col_time, _ = st.columns([1, 2, 4])
with col_btn:
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with col_time:
    st.caption(f"🕐 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 기준")

# 데이터 로드
try:
    df = load_data()
except Exception as e:
    st.error(f"구글 시트 연결 실패: {e}")
    st.stop()

# 데이터 전처리
df["계좌"] = df["계좌"].replace("", pd.NA).ffill()

acct_total_map = {}
for _, row in df.iterrows():
    acct = row["계좌"]
    val = str(row.get("연금총액", "")).replace(",", "").strip()
    if val and val != "nan" and acct not in acct_total_map:
        try:
            acct_total_map[acct] = float(val)
        except:
            pass

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

# ── KIS API 토큰 발급
token = None
token_status = st.empty()

with st.spinner("🔑 KIS API 토큰 발급 중..."):
    token = get_kis_token()

if token:
    token_status.success("✅ KIS API 연결 성공 - 실시간 가격 조회 중...")
else:
    token_status.warning("⚠️ KIS API 연결 실패 - 구글 시트 가격으로 대체합니다")

# ── 실시간 가격 조회
price_source = {}  # {종목코드: (가격, 소스)}

progress = st.progress(0, text="실시간 가격 조회 중...")
unique_codes = df["종목코드"].unique()
total = len(unique_codes)

for i, code in enumerate(unique_codes):
    progress.progress((i + 1) / total, text=f"조회 중... ({i+1}/{total})")

    # 종목코드 정제
    clean = str(code).split(":")[-1].strip()
    clean = ''.join(filter(str.isdigit, clean))

    if token and clean and len(clean) == 6:
        kis_price = get_kis_price(token, code)
        if kis_price > 0:
            price_source[code] = (kis_price, "실시간")
            continue

    # KIS 실패 시 구글 시트 값 사용
    sheet_rows = df[df["종목코드"] == code]
    if not sheet_rows.empty:
        sheet_price = float(sheet_rows.iloc[0]["현재주식가격"])
        price_source[code] = (sheet_price, "시트")

progress.empty()
token_status.empty()

# 가격 적용
df["실시간가격"] = df["종목코드"].map(lambda c: price_source.get(c, (0, "없음"))[0])
df["가격소스"] = df["종목코드"].map(lambda c: price_source.get(c, (0, "없음"))[1])
df["실시간가치"] = df["주식수"] * df["실시간가격"]

# G열(현재가치) > 0 이면 그걸로 대체 (개인투자용국채 등)
mask = df["현재가치"] > 0
df.loc[mask & (df["실시간가격"] == 0), "실시간가치"] = df.loc[mask & (df["실시간가격"] == 0), "현재가치"]

account_totals = acct_total_map

# ── 가격 소스 현황 표시
real_count = sum(1 for v in price_source.values() if v[1] == "실시간")
sheet_count = sum(1 for v in price_source.values() if v[1] == "시트")
st.caption(f"📡 실시간: {real_count}개 종목 | 📋 구글 시트: {sheet_count}개 종목")

st.divider()

# ════════════════════════════════════════════════════
# 상단 카드 + 계좌별 비중 + 자산배분
# ════════════════════════════════════════════════════
total_eval = df["실시간가치"].sum()
today_change = df["자산변동"].sum()
today_rate = (today_change / (total_eval - today_change) * 100) if (total_eval - today_change) else 0

top_left, top_right = st.columns([1, 3])

with top_left:
    st.metric("📈 총 평가금액", f"{total_eval:,.0f}원")
    st.metric("📅 오늘 자산변동", f"{today_change:+,.0f}원", delta=f"{today_rate:+.2f}%")

with top_right:
    pie_col, alloc_col = st.columns([1.2, 1.8])

    with pie_col:
        st.subheader("🥧 계좌별 자산 비중")
        acct_df = df.groupby("계좌")["실시간가치"].sum().reset_index()
        acct_df = acct_df[acct_df["실시간가치"] > 0]
        fig_pie = px.pie(
            acct_df, values="실시간가치", names="계좌",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set3
        )
        fig_pie.update_traces(
            textposition="inside", textinfo="percent+label",
            hovertemplate="%{label}<br>%{value:,.0f}원<br>%{percent}"
        )
        fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=380)
        st.plotly_chart(fig_pie, use_container_width=True)

    with alloc_col:
        st.subheader("🎯 자산배분 현황")
        try:
            sheet = get_gsheet()
            alloc_values = sheet.get("M18:P30", value_render_option="UNFORMATTED_VALUE")
            alloc_rows = []
            for row in alloc_values:
                if len(row) >= 3 and str(row[0]).strip() not in ["", "구분", "총액"]:
                    try:
                        name = str(row[0]).strip()
                        amount = float(str(row[1]).replace(",", "")) if row[1] != "" else 0
                        current_pct = float(str(row[2]).replace(",", "")) if len(row) > 2 and row[2] != "" else 0
                        target_pct = float(str(row[3]).replace(",", "")) if len(row) > 3 and row[3] != "" else 0
                        if name and amount > 0:
                            alloc_rows.append({
                                "구분": name, "금액": amount,
                                "현재비율": current_pct, "목표비율": target_pct,
                                "차이": round(current_pct - target_pct, 2)
                            })
                    except:
                        continue

            if alloc_rows:
                alloc_df = pd.DataFrame(alloc_rows)
                bar_colors = ["#d62728" if r["차이"] > 0 else "#4C72B0" for _, r in alloc_df.iterrows()]
                fig_alloc = go.Figure()
                fig_alloc.add_trace(go.Bar(
                    name="현재", x=alloc_df["구분"], y=alloc_df["현재비율"],
                    marker_color=bar_colors, opacity=0.85,
                    text=alloc_df["현재비율"].apply(lambda x: f"{x:.1f}%"),
                    textposition="outside", textfont=dict(size=11, family="Arial Black"),
                ))
                for _, row in alloc_df.iterrows():
                    idx = alloc_df[alloc_df["구분"] == row["구분"]].index[0]
                    fig_alloc.add_trace(go.Scatter(
                        x=[row["구분"]], y=[row["목표비율"]],
                        mode="markers+text",
                        marker=dict(symbol="line-ew", size=30, color="gray",
                                    line=dict(width=3, color="gray")),
                        text=f"{row['목표비율']:.0f}%",
                        textposition="top center",
                        textfont=dict(size=10, color="gray"),
                        name="목표" if idx == 0 else "",
                        showlegend=(idx == 0),
                        legendgroup="목표",
                    ))
                fig_alloc.update_layout(
                    height=380, margin=dict(t=30, b=20, l=20, r=20),
                    legend=dict(orientation="h", x=0.5, y=1.08, xanchor="center"),
                    yaxis=dict(title="비율(%)", ticksuffix="%"),
                    xaxis=dict(tickangle=-30), plot_bgcolor="white",
                )
                st.plotly_chart(fig_alloc, use_container_width=True)
        except:
            st.info("자산배분 데이터를 불러올 수 없습니다.")

st.divider()

# ════════════════════════════════════════════════════
# 종목별 차트
# ════════════════════════════════════════════════════
col2, col3 = st.columns(2)

with col2:
    st.subheader("📊 종목별 실시간 평가금액")
    stock_df = df.groupby("종목")["실시간가치"].sum().reset_index()
    stock_df = stock_df[stock_df["실시간가치"] > 0].sort_values("실시간가치", ascending=True)
    stock_df["표시텍스트"] = stock_df["실시간가치"].apply(lambda x: f"{x/100000000:.1f}억")
    fig_bar = px.bar(
        stock_df, x="실시간가치", y="종목", orientation="h",
        color="실시간가치", color_continuous_scale="Blues", text="표시텍스트"
    )
    fig_bar.update_traces(
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="#FFFF00", size=11, family="Arial Black")
    )
    fig_bar.update_layout(
        showlegend=False, coloraxis_showscale=False,
        margin=dict(t=20, b=20, l=20, r=20), height=600,
        xaxis_title="", yaxis_title=""
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col3:
    st.subheader("📅 오늘 종목별 자산변동")
    change_df = df.groupby("종목").agg(
        자산변동=("자산변동", "sum"),
        실시간가치=("실시간가치", "sum")
    ).reset_index()
    change_df = change_df.set_index("종목").reindex(stock_df["종목"]).reset_index()
    change_df["색상"] = change_df["자산변동"].apply(lambda x: "상승" if x >= 0 else "하락")
    change_df["전일가치"] = change_df["실시간가치"] - change_df["자산변동"]
    change_df["변동률"] = change_df.apply(
        lambda r: r["자산변동"] / r["전일가치"] * 100 if r["전일가치"] > 0 else 0, axis=1
    )
    fig_change = px.bar(
        change_df, x="자산변동", y="종목", orientation="h",
        color="색상",
        color_discrete_map={"상승": "#d62728", "하락": "#1f77b4"},
    )
    fig_change.update_traces(text=[""] * 100)
    for _, row in change_df.iterrows():
        label = f"{row['자산변동']:+,.0f}원 ({row['변동률']:+.2f}%)"
        if row["자산변동"] < 0:
            fig_change.add_annotation(
                x=0, y=row["종목"], text=label, xanchor="left",
                showarrow=False, font=dict(color="#1f77b4", size=11, family="Arial Black"), xshift=8
            )
        else:
            fig_change.add_annotation(
                x=0, y=row["종목"], text=label, xanchor="right",
                showarrow=False, font=dict(color="#d62728", size=11, family="Arial Black"), xshift=-8
            )
    max_abs = change_df["자산변동"].abs().max()
    fig_change.update_layout(
        showlegend=True, legend=dict(title=""),
        margin=dict(t=20, b=20, l=20, r=20), height=600,
        xaxis_title="", yaxis_title="",
        xaxis=dict(zeroline=True, zerolinewidth=2, zerolinecolor="gray",
                   range=[-max_abs * 1.5, max_abs * 1.5])
    )
    st.plotly_chart(fig_change, use_container_width=True)

st.divider()

# ════════════════════════════════════════════════════
# 계좌별 상세 현황
# ════════════════════════════════════════════════════
st.subheader("📋 계좌별 상세 현황")

summary_rows = []
for acct in df["계좌"].unique():
    acct_data = df[df["계좌"] == acct].copy()
    acct_eval = acct_data["실시간가치"].sum()
    acct_invest = account_totals.get(acct, 0)
    acct_today = acct_data["자산변동"].sum()
    today_rate_acct = (acct_today / acct_eval * 100) if acct_eval else 0
    summary_rows.append({
        "계좌": acct,
        "평가금액(원)": f"{acct_eval:,.0f}",
        "오늘변동(원)": f"{acct_today:+,.0f}",
        "오늘변동률": f"{today_rate_acct:+.2f}%",
        "종목수": f"{len(acct_data)}개",
    })

summary_df = pd.DataFrame(summary_rows)
st.dataframe(summary_df, use_container_width=True, hide_index=True)

st.divider()

# ════════════════════════════════════════════════════
# 전체 종목 현황 (실시간 vs 시트 가격 비교)
# ════════════════════════════════════════════════════
st.subheader("📑 전체 종목 현황 (실시간 가격 확인)")
full_df = df[["계좌", "종목", "주식수", "현재주식가격", "실시간가격", "실시간가치", "가격소스"]].copy()
full_df.columns = ["계좌", "종목명", "보유수량", "시트가격(원)", "실시간가격(원)", "평가금액(원)", "가격소스"]
full_df["보유수량"] = full_df["보유수량"].apply(lambda x: f"{int(x):,}")
full_df["시트가격(원)"] = full_df["시트가격(원)"].apply(lambda x: f"{int(x):,}")
full_df["실시간가격(원)"] = full_df["실시간가격(원)"].apply(lambda x: f"{int(x):,}")
full_df["평가금액(원)"] = full_df["평가금액(원)"].apply(lambda x: f"{x:,.0f}")
st.dataframe(full_df, use_container_width=True, hide_index=True)
