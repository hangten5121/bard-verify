import os
import io
import time
import zipfile

import pandas as pd
import streamlit as st

from find_entity_websites import find_best_website_for_entity


# ----------------------------
# Load Google API keys safely (env vars OR Streamlit secrets)
# ----------------------------
def get_secret(key: str, default: str = "") -> str:
    # st.secrets raises if no secrets.toml exists, so guard it
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


google_api_key = get_secret("GOOGLE_API_KEY", "")
google_cx = get_secret("GOOGLE_CX", "")

# Optional debug (you can remove once confirmed)
st.write("API Key Loaded:", bool(google_api_key))
st.write("CX Loaded:", bool(google_cx))

if not google_api_key or not google_cx:
    st.warning("Google API keys not set. Running in guess-only mode (.com/.org/.net).")


# ----------------------------
# Streamlit UI
# ----------------------------
st.set_page_config(page_title="Bard Verify Entity Website Finder", layout="wide")
st.title("Bard Verify Entity Website Finder")
st.write("Upload a CSV, run website checks grouped by mailing state, and download results.")

with st.sidebar:
    st.header("Settings")
    name_col = st.text_input("Entity name column", value="entity_name")
    state_col = st.text_input("Mailing state column", value="mailing_state")
    limit = st.number_input("Row limit (0 = no limit)", min_value=0, value=0, step=50)
    sleep_s = st.number_input("Sleep between Google calls (sec)", min_value=0.0, value=0.2, step=0.1)
    timeout = st.number_input("HTTP timeout (sec)", min_value=1.0, value=8.0, step=1.0)

uploaded = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded:
    st.stop()

df = pd.read_csv(uploaded)

st.subheader("Preview")
st.dataframe(df.head(20), use_container_width=True)

# Validate columns
missing = [c for c in (name_col, state_col) if c not in df.columns]
if missing:
    st.error(f"Missing columns: {missing}. Found: {list(df.columns)}")
    st.stop()

run = st.button("Run website checks")
if run:
    results = []
    progress = st.progress(0)
    status = st.empty()

    total = len(df) if limit == 0 else min(len(df), int(limit))

    for i, (_, row) in enumerate(df.head(total).iterrows(), start=1):
        entity_name = str(row.get(name_col, "")).strip()
        mailing_state = str(row.get(state_col, "")).strip() or "UNKNOWN"

        if not entity_name:
            continue

        # Pass mailing_state as a location hint into the search query
        res = find_best_website_for_entity(
            entity_name=entity_name,
            mailing_state=mailing_state,
            google_api_key=google_api_key or None,
            google_cx=google_cx or None,
            timeout=float(timeout),
        )

        results.append({
            "mailing_state": mailing_state,          # use actual grouping value
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

        progress.progress(min(1.0, i / max(1, total)))
        status.write(f"Processed {i}/{total}")

    out_df = pd.DataFrame(results)

    st.subheader("Results")
    st.dataframe(out_df, use_container_width=True)

    # Download master results
    st.download_button(
        "Download master_results.csv",
        data=out_df.to_csv(index=False).encode("utf-8"),
        file_name="master_results.csv",
        mime="text/csv",
    )

    # Download per-state ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for state, state_df in out_df.groupby(out_df["mailing_state"].fillna("UNKNOWN")):
            safe_state = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(state))
            zf.writestr(f"results_state_{safe_state}.csv", state_df.to_csv(index=False))
    zip_buf.seek(0)

    st.download_button(
        "Download per-state CSVs (zip)",
        data=zip_buf,
        file_name="by_mailing_state.zip",
        mime="application/zip",
    )
