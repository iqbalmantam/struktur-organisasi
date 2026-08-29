import datetime
import re

import gspread
from gspread_dataframe import get_as_dataframe
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import graphviz

st.set_page_config(
    page_title="Org Chart - JDC Warehouse", layout="wide"
)

# Injeksi CSS untuk menyembunyikan header/GitHub logo dan menambahkan watermark
st.markdown(
    """
    <style>
    /* Menyembunyikan header, menu, dan footer bawaan Streamlit */
    [data-testid="stHeader"] {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Styling Box Legend */
    .legend-box {
        display: inline-block;
        padding: 6px 14px;
        border-radius: 8px;
        margin-right: 10px;
        margin-bottom: 8px;
        font-size: 12px;
        font-weight: 600;
        color: white;
    }
    
    /* Styling Watermark di Tengah Bawah */
    .watermark {
        position: fixed;
        bottom: 15px;
        left: 50%; /* Membawa elemen ke tengah layar */
        transform: translateX(-50%); /* Menggeser presisi persis ke tengah */
        font-size: 14px;
        font-family: 'Helvetica', sans-serif;
        font-weight: bold;
        color: #64748b; /* Warna abu-abu slate */
        background-color: rgba(255, 255, 255, 0.85); /* Background agak transparan */
        padding: 6px 12px;
        border-radius: 6px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        z-index: 9999;
        pointer-events: none; /* Supaya tidak memblokir klik pada chart di bawahnya */
    }
    </style>
    
    <!-- Elemen Watermark -->
    <div class="watermark">Developed by iqbalmantam</div>
""",
    unsafe_allow_html=True,
)

st.title("🏢 JDC Chart Dashboard")

# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================
@st.cache_resource
def init_connection():
    cred_dict = dict(st.secrets["gcp_service_account"])
    return gspread.service_account_from_dict(cred_dict)


try:
    gc = init_connection()
    spreadsheet_id = "1O04askVDfi_h48tqJ972ZHwQzejPir39rocA9STWivc"
    sh = gc.open_by_key(spreadsheet_id)
    worksheet_list = [ws.title for ws in sh.worksheets()]
except Exception as e:
    st.error(f"Gagal terhubung ke Google Sheets: {e}")
    st.stop()


def get_last_modified(gc, file_id):
    """Ambil waktu terakhir diupdate via Google Drive API (best-effort)."""
    session = getattr(gc, "session", None) or getattr(
        getattr(gc, "http_client", None), "session", None
    )
    if session is None:
        return None
    try:
        resp = session.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"fields": "modifiedTime"},
            timeout=5,
        )
        resp.raise_for_status()
        modified = resp.json().get("modifiedTime")
        if not modified:
            return None
        dt = datetime.datetime.fromisoformat(modified.replace("Z", "+00:00"))
        dt_wib = dt.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
        return dt_wib.strftime("%d %b %Y, %H:%M WIB")
    except Exception:
        return None


last_modified = get_last_modified(gc, spreadsheet_id)
if last_modified:
    st.caption(f"🕒 Sheet terakhir diupdate: **{last_modified}**")

st.info(
    "📋 Pilih worksheet yang berisi **tabel data terstruktur** dengan kolom:"
    " `Nama`, `Jabatan`, `Level` (opsional), `Atasan` (nama atasan langsung —"
    " kosongkan untuk posisi paling atas)."
)
selected_sheet_name = st.selectbox(
    "📌 Pilih Worksheet Data Org Chart:", worksheet_list
)
worksheet = sh.worksheet(selected_sheet_name)
data_df = get_as_dataframe(worksheet, evaluate_formulas=True)
data_df = data_df.dropna(how="all").dropna(axis=1, how="all")

# ============================================================
# VALIDATE COLUMNS
# ============================================================
required_cols = {"Nama", "Jabatan", "Atasan"}
missing = required_cols - set(data_df.columns.astype(str))
if missing:
    st.error(
        f"Worksheet ini tidak punya kolom {missing}. Pastikan header di baris"
        " pertama persis: Nama, Jabatan, Level (opsional), Atasan."
    )
    st.stop()

data_df["Nama"] = data_df["Nama"].astype(str).str.strip()
data_df["Jabatan"] = data_df["Jabatan"].astype(str).str.strip()
data_df["Atasan"] = data_df["Atasan"].fillna("").astype(str).str.strip()
data_df.loc[data_df["Atasan"].isin(["-", "—", "–"]), "Atasan"] = ""
if "Level" in data_df.columns:
    data_df["Level"] = data_df["Level"].fillna("").astype(str).str.strip()
else:
    data_df["Level"] = ""
if "Project" in data_df.columns:
    data_df["Project"] = data_df["Project"].fillna("").astype(str).str.strip()

# ============================================================
# BUILD ORG TREE
# ============================================================
PALETTE = {
    "Head": "#1e3a8a",
    "Manager": "#4338ca",
    "Asst. Manager": "#7c3aed",
    "Supervisor": "#0f766e",
    "Leader": "#0891b2",
    "Support": "#b45309",
    "Security": "#be123c",
    "Admin": "#a16207",
    "Operator": "#4d7c0f",
    "Operation": "#15803d",
    "Staff": "#334155",
}
DEFAULT_COLOR = "#334155"


def color_for(level: str) -> str:
    return PALETTE.get(level, DEFAULT_COLOR)


def compute_context_names(df: pd.DataFrame, matched: set) -> set:
    """Ancestor chain + direct children dari node yang matched, untuk konteks."""
    parent_map = dict(zip(df["Nama"], df["Atasan"]))
    children_map: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        if row["Nama"] and row["Atasan"]:
            children_map.setdefault(row["Atasan"], []).append(row["Nama"])

    include = set()
    for name in matched:
        cur = name
        while cur:
            include.add(cur)
            cur = parent_map.get(cur, "")
    for name in matched:
        include.update(children_map.get(name, []))
    return include


def build_org_graph(
    df: pd.DataFrame, matched: set, rankdir: str, collapse_levels: set,
    nodesep: float = 0.25, ranksep: float = 0.5,
) -> graphviz.Digraph:
    if matched:
        include = compute_context_names(df, matched)
        df_use = df[df["Nama"].isin(include)]
        collapse_levels = set()  # detail/fokus view selalu ditampilkan penuh
    else:
        df_use = df

    graph = graphviz.Digraph()
    graph.attr(
        rankdir=rankdir, bgcolor="transparent", nodesep=str(nodesep), ranksep=str(ranksep),
        splines="ortho",
    )
    graph.attr(
        "node", shape="box", style="rounded,filled", fontname="Helvetica",
        fontcolor="white", color="#1e293b", margin="0.1,0.06", height="0.35",
    )
    graph.attr("edge", color="#475569", arrowsize="0.5", penwidth="0.8")

    names_seen = set()
    grouped_rows = []  # rows whose Level is collapsed -> summarized instead
    expanded_rows = []
    for _, row in df_use.iterrows():
        if not row["Nama"]:
            continue
        if row["Level"] in collapse_levels:
            grouped_rows.append(row)
        else:
            expanded_rows.append(row)

    fsize = "10" if len(expanded_rows) + len({(r['Atasan'], r['Jabatan']) for r in grouped_rows}) <= 40 else "9"

    for row in expanded_rows:
        name = row["Nama"]
        if name in names_seen:
            continue
        names_seen.add(name)
        label = f"{name}\n{row['Jabatan']}" if row["Jabatan"] else name
        is_focused = name in matched
        graph.node(
            name, label, fillcolor=color_for(row["Level"]), fontsize=fsize,
            penwidth="2.5" if is_focused else "1",
            color="#f8fafc" if is_focused else "#1e293b",
        )

    for row in expanded_rows:
        child, parent = row["Nama"], row["Atasan"]
        if parent and parent in names_seen:
            graph.edge(parent, child)

    # group collapsed rows by (parent, jabatan) -> one summary node with a count
    groups: dict[tuple, dict] = {}
    for row in grouped_rows:
        key = (row["Atasan"], row["Jabatan"], row["Level"])
        g = groups.setdefault(key, {"count": 0})
        g["count"] += 1

    for i, ((parent, jabatan, level), g) in enumerate(groups.items()):
        node_id = f"grp_{i}"
        label = f"{jabatan or level}\n({g['count']} orang)"
        graph.node(node_id, label, fillcolor=color_for(level), fontsize=fsize)
        if parent and parent in names_seen:
            graph.edge(parent, node_id, style="dashed")

    return graph


# ============================================================
# LAYOUT — TABS
# ============================================================
tab_chart, tab_editor = st.tabs(["📊 Bagan Organisasi", "📄 Lihat Data Sheets"])

with tab_chart:
    st.subheader(f"Struktur: {selected_sheet_name}")

    if "focus_level" not in st.session_state:
        st.session_state.focus_level = None

    # ---------- RINGKASAN STATISTIK ----------
    total_posisi = int((data_df["Nama"] != "").sum())
    vacant_mask = data_df["Nama"].str.lower().isin(["vacant", "kosong", "-"])
    total_vacant = int(vacant_mask.sum())
    total_terisi = total_posisi - total_vacant

    stat_cols = st.columns(4)
    stat_cols[0].metric("👥 Total Posisi", total_posisi)
    stat_cols[1].metric("✅ Terisi", total_terisi)
    stat_cols[2].metric("🔴 Vacant", total_vacant)
    level_counts = data_df[~vacant_mask]["Level"].value_counts()
    top_level = level_counts.idxmax() if not level_counts.empty else "-"
    stat_cols[3].metric("📌 Level Terbanyak", top_level)

    with st.expander("📊 Rincian jumlah per level"):
        st.dataframe(
            data_df[data_df["Nama"] != ""]["Level"]
            .value_counts()
            .rename_axis("Level")
            .reset_index(name="Jumlah"),
            use_container_width=True, hide_index=True,
        )

    # ---------- PENCARIAN NAMA ----------
    search_query = st.text_input("🔍 Cari nama", placeholder="Ketik nama, mis. Firmansyah")
    search_matched: set = set()
    if search_query.strip():
        search_matched = set(
            data_df[data_df["Nama"].str.contains(search_query.strip(), case=False, na=False)]["Nama"]
        )
        if not search_matched:
            st.warning(f"Tidak ditemukan nama yang cocok dengan '{search_query}'.")

    levels_present = [l for l in data_df["Level"].unique() if l]
    if levels_present:
        st.caption("👉 Klik level untuk fokus ke bagian itu saja (lebih mudah dibaca):")
        cols = st.columns(len(levels_present) + 1)
        for i, lvl in enumerate(levels_present):
            is_active = st.session_state.focus_level == lvl
            with cols[i]:
                if st.button(
                    ("● " if is_active else "") + lvl, key=f"btn_{lvl}",
                    type="primary" if is_active else "secondary",
                ):
                    st.session_state.focus_level = None if is_active else lvl
                    st.rerun()
        with cols[-1]:
            if st.button("↺ Semua", key="btn_reset"):
                st.session_state.focus_level = None
                st.rerun()

    # Pencarian nama mengambil alih fokus level kalau ada hasil
    if search_matched:
        active_matched = search_matched
        active_label = f"Hasil pencarian '{search_query}'"
    elif st.session_state.focus_level:
        active_matched = set(data_df[data_df["Level"] == st.session_state.focus_level]["Nama"])
        active_label = st.session_state.focus_level
    else:
        active_matched = set()
        active_label = None

    orphans = data_df[
        (data_df["Atasan"] != "") & (~data_df["Atasan"].isin(data_df["Nama"]))
    ]
    if not orphans.empty:
        st.warning(
            "Beberapa baris punya nilai 'Atasan' yang tidak cocok dengan nama"
            " manapun di kolom 'Nama' (kemungkinan typo): "
            + ", ".join(orphans["Atasan"].unique())
        )

    orientation_label = st.radio(
        "Orientasi bagan", ["Atas ke Bawah", "Kiri ke Kanan"],
        horizontal=True, label_visibility="collapsed", key="orientation_choice",
    )
    rankdir = "TB" if orientation_label == "Atas ke Bawah" else "LR"
    if rankdir == "LR" and not active_matched:
        st.caption(
            "⚠️ Mode Kiri ke Kanan menumpuk banyak anak-buah secara vertikal,"
            " jadi untuk tampilan 'Semua' bisa jadi sangat panjang ke bawah."
            " Lebih pas dipakai saat fokus ke satu level (klik salah satu"
            " tombol level di atas)."
        )

    MANAGEMENT_LEVELS = {"Head", "Manager", "Asst. Manager", "Supervisor", "Leader"}
    default_collapse = [l for l in levels_present if l not in MANAGEMENT_LEVELS]
    with st.expander("🗜️ Atur level yang diringkas (khusus tampilan 'Semua')", expanded=False):
        collapse_choice = st.multiselect(
            "Level ini akan ditampilkan sebagai 1 kotak ringkasan (n orang),"
            " bukan nama satu-satu:",
            options=levels_present, default=default_collapse,
        )
    collapse_levels = set(collapse_choice) if not active_matched else set()

    frame_height = 550  # batas maksimal tinggi area chart (px); tinggi asli tetap dipakai jika lebih pendek

    org_graph = build_org_graph(
        data_df, active_matched, rankdir, collapse_levels,
        nodesep=0.3, ranksep=0.55,
    )

    try:
        svg_source = org_graph.pipe(format="svg").decode("utf-8")
        height_match = re.search(r'height="(\d+)pt"', svg_source)
        native_height_px = int(int(height_match.group(1)) * 1.3333) if height_match else frame_height
        display_height = min(native_height_px + 20, frame_height)
        frame_html = f"""
        <div style="position: relative; width: 100%;">
            <div style="
                position: absolute; left: 8px; top: 8px; z-index: 10;
                display: flex; flex-direction: column; align-items: center; gap: 4px;
                background: rgba(15, 23, 42, 0.85); border: 1px solid #334155;
                border-radius: 6px; padding: 4px;
            ">
                <button onclick="orgZoom(0.1)" style="
                    width: 26px; height: 26px; border-radius: 4px; border: none;
                    background: #334155; color: white; font-size: 16px; cursor: pointer;
                ">+</button>
                <span id="orgZoomLabel" style="
                    color: #cbd5e1; font-size: 11px; font-family: Helvetica, sans-serif;
                    text-align: center;
                ">100%</span>
                <button onclick="orgZoom(-0.1)" style="
                    width: 26px; height: 26px; border-radius: 4px; border: none;
                    background: #334155; color: white; font-size: 16px; cursor: pointer;
                ">−</button>
                <button onclick="orgZoom(0)" title="Reset zoom" style="
                    width: 26px; height: 26px; border-radius: 4px; border: none;
                    background: #1e293b; color: #94a3b8; font-size: 11px; cursor: pointer;
                ">⟲</button>
            </div>
            <div id="orgScrollBox" style="
                width: 100%; height: {display_height}px; overflow: auto;
                border: 1px solid #334155; border-radius: 8px;
            ">
                <div id="orgSvgWrap" style="zoom: 1;">{svg_source}</div>
            </div>
        </div>
        <script>
            let orgZoomLevel = 1;
            function orgZoom(delta) {{
                orgZoomLevel = delta === 0 ? 1 : Math.min(3, Math.max(0.3, orgZoomLevel + delta));
                document.getElementById('orgSvgWrap').style.zoom = orgZoomLevel;
                document.getElementById('orgZoomLabel').innerText = Math.round(orgZoomLevel * 100) + '%';
            }}
        </script>
        """
        components.html(frame_html, height=display_height + 12, scrolling=False)
    except Exception:
        st.info(
            "⚠️ Belum bisa render mode frame-scroll (kemungkinan `packages.txt`"
            " berisi `graphviz` belum ter-deploy di server). Menampilkan mode"
            " biasa untuk sementara."
        )
        st.graphviz_chart(org_graph, use_container_width=False)

    if active_matched:
        st.markdown(f"##### 📋 Detail — {active_label}")
        detail_cols = ["Nama", "Jabatan", "Atasan"]
        if "Project" in data_df.columns:
            detail_cols.append("Project")
        detail_df = data_df[data_df["Nama"].isin(active_matched)][
            detail_cols
        ].reset_index(drop=True)
        st.dataframe(detail_df, use_container_width=True, hide_index=True)

with tab_editor:
    st.subheader("📄 Data Google Sheets")
    st.info(
        "Tampilan ini hanya untuk melihat data (read-only) — tidak ada"
        " perubahan yang bisa disimpan kembali ke Google Sheets dari sini."
    )
    st.dataframe(data_df, use_container_width=True, hide_index=True)
