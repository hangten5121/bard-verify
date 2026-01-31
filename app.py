import os
import io
import time
import pandas as pd
import streamlit as st

# ----------------------------
# Load Google API keys safely - Supports Streamlit secrets and env vars
# ----------------------------

def get_secret(key: str, default: str = ""):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

google_api_key = get_secret("GOOGLE_API_KEY")
google_cx = get_secret("GOOGLE_CX")

st.write("API Key Loaded:", bool(google_api_key))
st.write("CX Loaded:", bool(google_cx))


def get_secret(key: str, default: str = "") -> str:
    # st.secrets raises if no secrets.toml exists, so guard it
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

google_api_key = get_secret("GOOGLE_API_KEY", "")
google_cx = get_secret("GOOGLE_CX", "")

google_api_key = os.getenv("GOOGLE_API_KEY", "")
google_cx = os.getenv("GOOGLE_CX", "")

from find_entity_websites import find_best_website_for_entity  # from your script

st.set_page_config(page_title="Bard Verify Entity Website Finder", layout="wide")
st.title("Bard Verify Entity Website Finder")
st.write("Upload a CSV, run checks by area code, and download the results.")

with st.sidebar:
    st.header("Settings")
    name_col = st.text_input("Entity name column", value="entity_name")
    area_col = st.text_input("Area code column", value="area_code")
    limit = st.number_input("Row limit (0 = no limit)", min_value=0, value=0, step=50)
    sleep_s = st.number_input("Sleep between Google calls (sec)", min_value=0.0, value=0.2, step=0.1)
    timeout = st.number_input("HTTP timeout (sec)", min_value=1.0, value=8.0, step=1.0)

uploaded = st.file_uploader("Upload CSV", type=["csv"])

if not uploaded:
    st.stop()

df = pd.read_csv(uploaded)
st.subheader("Preview")
st.dataframe(df.head(20), use_container_width=True)

if name_col not in df.columns or area_col not in df.columns:
    st.error(f"Missing columns. Found: {list(df.columns)}")
    st.stop()

run = st.button("Run website checks")

if run:
    results = []
    progress = st.progress(0)
    status = st.empty()

    total = len(df) if limit == 0 else min(len(df), int(limit))
    for idx, row in df.head(total).iterrows():
        entity_name = str(row.get(name_col, "")).strip()
        area_code = str(row.get(area_col, "")).strip()

        if not entity_name:
            continue

        res = find_best_website_for_entity(
            entity_name=entity_name,
            area_code=area_code,
            google_api_key=google_api_key if google_api_key else None,
            google_cx=google_cx if google_cx else None,
            timeout=float(timeout),
        )

        results.append({
            "area_code": res.area_code,
            "entity_name": res.entity_name,
            "search_query": res.search_query,
            "best_domain": res.best_domain,
            "best_url": res.best_url,
            "best_http_status": res.best_http_status,
            "method": res.method,
            "other_candidates": res.other_candidates,
        })

        if google_api_key and google_cx:
            time.sleep(float(sleep_s))

        done = len(results)
        progress.progress(min(1.0, done / max(1, total)))
        status.write(f"Processed {done}/{total}")

    out_df = pd.DataFrame(results)

    st.subheader("Results")
    st.dataframe(out_df, use_container_width=True)

    # Download master results
    csv_bytes = out_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download master_results.csv",
        data=csv_bytes,
        file_name="master_results.csv",
        mime="text/csv",
    )

    # Download per-area ZIP
    import zipfile

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for area, area_df in out_df.groupby(out_df["area_code"].fillna("UNKNOWN")):
            safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(area))
            zf.writestr(f"results_area_{safe}.csv", area_df.to_csv(index=False))
    zip_buf.seek(0)

    st.download_button(
        "Download per-area CSVs (zip)",
        data=zip_buf,
        file_name="by_area_code.zip",
        mime="application/zip",
    )
