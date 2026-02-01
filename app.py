import os
import io
import time
import zipfile

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from find_entity_websites import find_best_website_for_entity


# ----------------------------
# Brand
# (Pulled from your SVG: #777b7a)
# ----------------------------
BRAND_HEX = "#777b7a"


# ----------------------------
# Streamlit Page Config
# ----------------------------
st.set_page_config(
    page_title="BardVerify Entity Website Finder",
    page_icon="assets/logo.svg",  # use assets/favicon.png here if you add one
    layout="wide",
)

# ----------------------------
# Load Google API keys safely - Supports Streamlit secrets and env vars
# ----------------------------

def get_secret(key: str, default: str = ""):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


google_api_key = get_secret("GOOGLE_API_KEY", "")
google_cx = get_secret("GOOGLE_CX", "")


# ----------------------------
# Sidebar
# ----------------------------
with st.sidebar:
    st.image("assets/logo.svg", width=140)
    st.header("Settings")

    name_col = st.text_input("Entity name column", value="entity_name")
    state_col = st.text_input("Mailing state column", value="mailing_state")

    limit = st.number_input("Row limit (0 = no limit)", min_value=0, value=0, step=50)
    sleep_s = st.number_input("Sleep between Google calls (sec)", min_value=0.0, value=0.2, step=0.1)
    timeout = st.number_input("HTTP timeout (sec)", min_value=1.0, value=8.0, step=1.0)

    st.divider()
    anim_speed = st.slider("3D animation speed", min_value=0.1, max_value=3.0, value=1.0, step=0.1)

if not google_api_key or not google_cx:
    st.warning(
        "Google API keys not detected. Running in guess-only mode (.com/.org/.net). "
        "Add GOOGLE_API_KEY and GOOGLE_CX for better results."
    )


# ----------------------------
# Header (Logo + Title)
# ----------------------------
col1, col2 = st.columns([1, 7])
with col1:
    st.image("assets/logo.svg", width=120)
with col2:
    st.title("BardVerify Entity Website Finder")
    st.caption("Internal tool to verify business websites grouped by mailing state.")


# ----------------------------
# Three.js Scene: BardVerify 3D Text (speed tied to slider)
# ----------------------------
def render_bardverify_three_scene(speed: float, height: int = 320):
    html = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      html, body {{
        margin: 0; padding: 0;
        background: transparent;
        overflow: hidden;
      }}
      #wrap {{
        width: 100%;
        height: {height}px;
        border-radius: 16px;
        overflow: hidden;
      }}
      canvas {{
        width: 100%;
        height: 100%;
        display: block;
      }}
      .fallback {{
        position: absolute;
        inset: 0;
        display: none;
        align-items: center;
        justify-content: center;
        color: #aaa;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        font-size: 14px;
      }}
    </style>
  </head>
  <body>
    <div id="wrap" style="position:relative;">
      <canvas id="c"></canvas>
      <div id="fallback" class="fallback">3D scene failed to load (check browser console / Brave Shields).</div>
    </div>

    <!-- Non-module build = much more compatible inside Streamlit iframe -->
    <script src="https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js"></script>

    <script>
      (function () {{
        const BRAND = "{BRAND_HEX}";
        const SPEED = {float(speed)};

        const canvas = document.getElementById("c");
        const fallback = document.getElementById("fallback");

        try {{
          const renderer = new THREE.WebGLRenderer({{ canvas, antialias: true, alpha: true }});
          renderer.setPixelRatio(window.devicePixelRatio);

          const scene = new THREE.Scene();

          // Camera
          const camera = new THREE.PerspectiveCamera(45, 2, 0.1, 100);
          camera.position.set(0, 0.6, 5.2);

          // Lights
          scene.add(new THREE.HemisphereLight(0xffffff, 0x222222, 1.1));
          const key = new THREE.DirectionalLight(0xffffff, 1.1);
          key.position.set(3, 4, 6);
          scene.add(key);

          // Subtle ring (beacon vibe)
          const ringGeo = new THREE.TorusGeometry(2.05, 0.06, 18, 90);
          const ringMat = new THREE.MeshStandardMaterial({{
            color: BRAND,
            metalness: 0.25,
            roughness: 0.35,
            transparent: true,
            opacity: 0.45
          }});
          const ring = new THREE.Mesh(ringGeo, ringMat);
          ring.rotation.x = Math.PI / 2.2;
          ring.position.y = -0.35;
          scene.add(ring);

          // --- "3D text" via canvas texture on a thin box (robust, no font loaders) ---
          function makeTextTexture(text) {{
            const c = document.createElement("canvas");
            c.width = 1024;
            c.height = 256;
            const ctx = c.getContext("2d");

            // transparent background
            ctx.clearRect(0, 0, c.width, c.height);

            // text styling
            ctx.font = "bold 132px system-ui, -apple-system, Segoe UI, Roboto, Arial";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";

            // subtle shadow / glow to mimic bevel
            ctx.shadowColor = "rgba(0,0,0,0.45)";
            ctx.shadowBlur = 18;
            ctx.shadowOffsetX = 0;
            ctx.shadowOffsetY = 8;

            // fill
            ctx.fillStyle = BRAND;
            ctx.fillText(text, c.width / 2, c.height / 2);

            // a light highlight stroke
            ctx.shadowBlur = 0;
            ctx.lineWidth = 6;
            ctx.strokeStyle = "rgba(255,255,255,0.20)";
            ctx.strokeText(text, c.width / 2, c.height / 2);

            const tex = new THREE.CanvasTexture(c);
            tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
            tex.needsUpdate = true;
            return tex;
          }}

          const textTex = makeTextTexture("BardVerify");

          // Box with textured front + branded sides to read as 3D
          const w = 3.6, h = 0.95, d = 0.18;
          const geo = new THREE.BoxGeometry(w, h, d);

          const sideMat = new THREE.MeshStandardMaterial({{
            color: new THREE.Color(BRAND).multiplyScalar(0.85),
            metalness: 0.15,
            roughness: 0.55
          }});

          const frontMat = new THREE.MeshStandardMaterial({{
            map: textTex,
            transparent: true,
            metalness: 0.05,
            roughness: 0.35
          }});

          const backMat = new THREE.MeshStandardMaterial({{
            color: 0x111111,
            metalness: 0.0,
            roughness: 0.9,
            transparent: true,
            opacity: 0.0
          }});

          // Materials order for BoxGeometry:
          // +X, -X, +Y, -Y, +Z, -Z
          const mats = [sideMat, sideMat, sideMat, sideMat, frontMat, backMat];
          const textBlock = new THREE.Mesh(geo, mats);
          textBlock.position.y = 0.10;
          scene.add(textBlock);

          // Resize helper
          function resize() {{
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            const need = canvas.width !== width || canvas.height !== height;
            if (need) {{
              renderer.setSize(width, height, false);
              camera.aspect = width / height;
              camera.updateProjectionMatrix();
            }}
          }}

          let last = performance.now();
          function animate(now) {{
            resize();

            const dt = (now - last) * 0.001;
            last = now;

            const t = now * 0.001 * SPEED;

            // Animate
            textBlock.rotation.y = t * 0.55;
            textBlock.rotation.x = Math.sin(t * 0.9) * 0.10;
            textBlock.position.y = 0.10 + Math.sin(t * 1.1) * 0.08;

            ring.rotation.z = t * 0.35;
            ring.rotation.x = Math.PI / 2.2 + Math.sin(t * 0.7) * 0.05;

            renderer.render(scene, camera);
            requestAnimationFrame(animate);
          }}

          requestAnimationFrame(animate);

        }} catch (e) {{
          console.error(e);
          fallback.style.display = "flex";
        }}
      }})();
    </script>
  </body>
</html>
"""
    components.html(html, height=height)

with st.expander("BardVerify 3D", expanded=True):
    render_bardverify_three_scene(speed=anim_speed, height=320)


st.write("Upload a CSV, run website checks grouped by mailing state, and download the results.")


# ----------------------------
# File Upload
# ----------------------------
uploaded = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded:
    st.stop()

df = pd.read_csv(uploaded)

st.subheader("Preview")
st.dataframe(df.head(20), use_container_width=True)

missing = [c for c in (name_col, state_col) if c not in df.columns]
if missing:
    st.error(f"Missing required columns: {missing}. Found: {list(df.columns)}")
    st.stop()


# ----------------------------
# Run
# ----------------------------
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

        res = find_best_website_for_entity(
            entity_name=entity_name,
            mailing_state=mailing_state,
            google_api_key=google_api_key or None,
            google_cx=google_cx or None,
            timeout=float(timeout),
        )

        results.append(
            {
                "mailing_state": mailing_state,
                "entity_name": res.entity_name,
                "search_query": res.search_query,
                "best_domain": res.best_domain,
                "best_url": res.best_url,
                "best_http_status": res.best_http_status,
                "method": res.method,
                "other_candidates": res.other_candidates,
            }
        )

        if google_api_key and google_cx:
            time.sleep(float(sleep_s))

        progress.progress(min(1.0, i / max(1, total)))
        status.write(f"Processed {i}/{total}")

    out_df = pd.DataFrame(results)

    st.subheader("Results")
    st.dataframe(out_df, use_container_width=True)

    st.download_button(
        "Download master_results.csv",
        data=out_df.to_csv(index=False).encode("utf-8"),
        file_name="master_results.csv",
        mime="text/csv",
    )

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
