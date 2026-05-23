from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

APP_TITLE = "Maryland Voter Registration Dashboard"
DATA_DIR = Path("data/parsed")
PARTY_COLUMNS = ["DEM", "REP", "UNA", "LIB", "GRN", "WCP", "NLM", "OTH"]
PARTY_LABELS = {
    "DEM": "Democratic",
    "REP": "Republican",
    "UNA": "Unaffiliated",
    "LIB": "Libertarian",
    "GRN": "Green",
    "WCP": "Working Class Party",
    "NLM": "No Labels MD",
    "OTH": "Other",
}
PARTY_COLORS = {
    "DEM": "#1f77b4",
    "REP": "#d62728",
    "UNA": "#7f7f7f",
    "LIB": "#9467bd",
    "GRN": "#2ca02c",
    "WCP": "#ff7f0e",
    "NLM": "#17becf",
    "OTH": "#636363",
}


st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)


def friendly_party_name(code: str) -> str:
    return PARTY_LABELS.get(code, code)


def normalize_party_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "UNA" not in df.columns and "UNAF" in df.columns:
        df = df.rename(columns={"UNAF": "UNA"})

    for col in [*PARTY_COLUMNS, "TOTAL"]:
        if col not in df.columns:
            df[col] = pd.NA

    return df


@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("MSR-*.csv"))
    frames: list[pd.DataFrame] = []
    for path in files:
        df = pd.read_csv(path)
        df = normalize_party_columns(df)
        df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
        df["source_file"] = path.name
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    data = pd.concat(frames, ignore_index=True)
    data = data.dropna(subset=["report_date", "county"]).copy()
    data = normalize_party_columns(data)

    for col in [*PARTY_COLUMNS, "TOTAL"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    data["county"] = data["county"].astype(str).str.strip()
    data = data.sort_values(["report_date", "county"]).reset_index(drop=True)
    return data


@st.cache_data(show_spinner=False)
def build_statewide_summary(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()

    grouped = data.groupby("report_date", as_index=False)[[*PARTY_COLUMNS, "TOTAL"]].sum(numeric_only=True)
    grouped = grouped.sort_values("report_date").reset_index(drop=True)

    party_total = grouped[PARTY_COLUMNS].sum(axis=1)
    grouped["party_total"] = party_total
    for col in PARTY_COLUMNS:
        grouped[f"{col}_pct"] = grouped[col] / grouped["TOTAL"] * 100.0
    grouped["party_total_pct"] = grouped["party_total"] / grouped["TOTAL"] * 100.0

    return grouped


@st.cache_data(show_spinner=False)
def build_county_summary(data: pd.DataFrame, county: str) -> pd.DataFrame:
    county_df = data[data["county"] == county].copy()
    if county_df.empty:
        return county_df

    county_df = county_df.sort_values("report_date").reset_index(drop=True)
    for col in PARTY_COLUMNS:
        county_df[f"{col}_pct"] = county_df[col] / county_df["TOTAL"] * 100.0
    county_df["party_total"] = county_df[PARTY_COLUMNS].sum(axis=1)
    return county_df


def metric_card(label: str, value: str, delta: str | None = None) -> None:
    st.metric(label, value, delta)


def fmt_int(value: float | int | None) -> str:
    if pd.isna(value) if value is not None else True:
        return "n/a"
    return f"{int(round(float(value))):,}"


def fmt_pct(value: float | int | None) -> str:
    if pd.isna(value) if value is not None else True:
        return "n/a"
    return f"{float(value):.1f}%"


def add_party_traces(fig: go.Figure, df: pd.DataFrame, use_pct: bool = False, title_suffix: str = "") -> None:
    for col in PARTY_COLUMNS:
        if col not in df.columns:
            continue
        series = df[col]
        if use_pct:
            series = df[f"{col}_pct"]
            y_title = "Percent of total"
        else:
            y_title = "Voter count"

        if series.dropna().empty:
            continue

        if not use_pct and series.max() < 100:
            continue

        fig.add_trace(
            go.Scatter(
                x=df["report_date"],
                y=series,
                mode="lines+markers",
                name=friendly_party_name(col),
                line=dict(width=2, color=PARTY_COLORS.get(col, None)),
                hovertemplate=(
                    "%{x|%Y-%m}<br>"
                    + f"{friendly_party_name(col)}: %{{y:,.2f}}"
                    + title_suffix
                    + "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        hovermode="x unified",
        legend_title_text="Party",
        margin=dict(l=20, r=20, t=40, b=20),
        template="plotly_white",
        xaxis_title="Month",
        yaxis_title=y_title,
        height=500,
    )


def get_visible_party_columns(only_major_parties: bool) -> list[str]:
    if only_major_parties:
        return ["DEM", "REP", "UNA"]
    return PARTY_COLUMNS


def render_overview(data: pd.DataFrame, statewide: pd.DataFrame, visible_party_columns: list[str]) -> None:
    st.subheader("Statewide Overview")

    latest = statewide.iloc[-1]
    prev = statewide.iloc[-2] if len(statewide) > 1 else None
    latest_date = latest["report_date"].strftime("%Y-%m")

    total_reg = latest["TOTAL"]
    party_total = latest["party_total"]
    top_party = max(visible_party_columns, key=lambda c: float(latest.get(c, 0) or 0))
    top_party_share = latest[f"{top_party}_pct"]

    cols = st.columns(3)
    cols[0].metric("Latest statewide total", fmt_int(total_reg), latest_date)
    cols[1].metric("Top party", friendly_party_name(top_party), fmt_pct(top_party_share))
    cols[2].metric("Counties covered", str(data["county"].nunique()), None)

    if prev is not None:
        total_delta = total_reg - prev["TOTAL"]
        party_delta = party_total - prev["party_total"]
        st.caption(
            f"Latest month-over-month change: total {fmt_int(total_delta)}, party-summed total {fmt_int(party_delta)}"
        )

    st.markdown("### Total registration trend")
    total_fig = go.Figure()
    total_fig.add_trace(
        go.Scatter(
            x=statewide["report_date"],
            y=statewide["TOTAL"],
            mode="lines+markers",
            name="Statewide TOTAL",
            line=dict(color="#1f77b4", width=3),
        )
    )
    total_fig.update_layout(
        template="plotly_white",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=20, b=20),
        height=420,
        xaxis_title="Month",
        yaxis_title="Voter count",
    )
    st.plotly_chart(total_fig, use_container_width=True)

    st.markdown("### Party composition over time")
    share_fig = go.Figure()
    for col in visible_party_columns:
        pct_col = f"{col}_pct"
        if pct_col not in statewide.columns:
            continue
        if statewide[col].max() < 100:
            continue
        share_fig.add_trace(
            go.Scatter(
                x=statewide["report_date"],
                y=statewide[pct_col],
                mode="lines+markers",
                name=friendly_party_name(col),
                line=dict(width=2, color=PARTY_COLORS.get(col, None)),
            )
        )
    share_fig.update_layout(
        template="plotly_white",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=20, b=20),
        height=500,
        xaxis_title="Month",
        yaxis_title="Share of statewide total (%)",
    )
    st.plotly_chart(share_fig, use_container_width=True)

    st.markdown("### Latest month snapshot")
    snapshot = statewide.iloc[-1][["TOTAL", *visible_party_columns]].to_frame("value").reset_index()
    snapshot.columns = ["metric", "value"]
    snapshot["metric"] = snapshot["metric"].replace({"TOTAL": "TOTAL"})
    st.dataframe(snapshot, use_container_width=True, hide_index=True)


def render_county_explorer(data: pd.DataFrame, county: str, visible_party_columns: list[str]) -> None:
    st.subheader(f"County Explorer: {county}")
    county_df = build_county_summary(data, county)
    if county_df.empty:
        st.warning("No data available for the selected county.")
        return

    latest = county_df.iloc[-1]
    prev = county_df.iloc[-2] if len(county_df) > 1 else None

    cols = st.columns(4)
    cols[0].metric("Latest county total", fmt_int(latest["TOTAL"]), latest["report_date"].strftime("%Y-%m"))
    cols[1].metric(
        "Largest party",
        friendly_party_name(max(visible_party_columns, key=lambda c: float(latest.get(c, 0) or 0))),
        None,
    )
    cols[2].metric("Months available", str(len(county_df)), None)
    cols[3].empty()

    if prev is not None:
        st.caption(
            f"Latest month-over-month change: total {fmt_int(latest['TOTAL'] - prev['TOTAL'])}"
        )

    st.markdown("### Voter counts by month")
    count_fig = go.Figure()
    for col in visible_party_columns:
        if county_df[col].dropna().empty:
            continue
        # Hide very small parties for clarity, per requirement.
        if county_df[col].max() < 100:
            continue
        count_fig.add_trace(
            go.Scatter(
                x=county_df["report_date"],
                y=county_df[col],
                mode="lines+markers",
                name=friendly_party_name(col),
                line=dict(width=2, color=PARTY_COLORS.get(col, None)),
            )
        )
    count_fig.update_layout(
        template="plotly_white",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=20, b=20),
        height=500,
        xaxis_title="Month",
        yaxis_title="Voter count",
    )
    st.plotly_chart(count_fig, use_container_width=True)

    st.markdown("### Month-over-month change percentage")
    mom_fig = go.Figure()
    mom_series = ["TOTAL", "DEM", "REP", "UNA"]
    mom_labels = {
        "TOTAL": "TOTAL",
        "DEM": "Democratic",
        "REP": "Republican",
        "UNA": "Unaffiliated",
    }
    for col in mom_series:
        if county_df[col].dropna().empty:
            continue
        pct_change = county_df[col].pct_change() * 100.0
        if pct_change.dropna().empty:
            continue
        mom_fig.add_trace(
            go.Scatter(
                x=county_df["report_date"],
                y=pct_change,
                mode="lines+markers",
                name=mom_labels[col],
                line=dict(width=2, color=PARTY_COLORS.get(col, None)),
                hovertemplate="%{x|%Y-%m}<br>%{fullData.name}: %{y:.1f}%<extra></extra>",
            )
        )
    mom_fig.update_layout(
        template="plotly_white",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=20, b=20),
        height=500,
        xaxis_title="Month",
        yaxis_title="Month-over-month change (%)",
    )
    st.plotly_chart(mom_fig, use_container_width=True)

    st.markdown("### County monthly table")
    display_cols = ["report_date", "TOTAL", *visible_party_columns]
    display_df = county_df[display_cols].copy()
    display_df["report_date"] = display_df["report_date"].dt.strftime("%Y-%m")
    st.dataframe(display_df, use_container_width=True, hide_index=True)


def main() -> None:
    data = load_data()
    if data.empty:
        st.error(f"No parsed CSV files found in {DATA_DIR}.")
        st.stop()

    statewide = build_statewide_summary(data)
    if statewide.empty:
        st.error("Could not build statewide summary from parsed data.")
        st.stop()

    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Page", ["Overview", "County Explorer"], index=0)
        only_major_parties = st.checkbox("Only display DEM/REP/UNA", value=True)
        st.markdown("---")
        st.caption(f"Loaded {len(data):,} county-month rows from {data['report_date'].nunique()} months.")
        st.caption(f"Counties: {data['county'].nunique()}")

    visible_party_columns = get_visible_party_columns(only_major_parties)

    if page == "Overview":
        render_overview(data, statewide, visible_party_columns)
    else:
        counties = sorted(data["county"].dropna().unique().tolist())
        county = st.selectbox("Select county", counties, index=0)
        render_county_explorer(data, county, visible_party_columns)


if __name__ == "__main__":
    main()
