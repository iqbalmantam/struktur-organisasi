import datetime
import json
import re

import gspread
from gspread_dataframe import get_as_dataframe
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import graphviz
import altair as alt

st.set_page_config(
    page_title="Org Chart - WEST Warehouse", layout="wide"
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

st.title("ðŸ¢ WEST Chart Dashboard")

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
    st.caption(f"ðŸ•’ Sheet terakhir diupdate: **{last_modified}**")

st.info(
    "ðŸ“‹ Pilih worksheet yang berisi **tabel data terstruktur** dengan kolom:"
    " `Nama`, `Jabatan`, `Level` (opsional), `Atasan` (nama atasan langsung â€”"
    " kosongkan untuk posisi paling atas)."
)
selected_sheet_name = st.selectbox(
    "ðŸ“Œ Pilih Worksheet Data Org Chart:", worksheet_list
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
data_df.loc[data_df["Atasan"].isin(["-", "â€”", "â€“"]), "Atasan"] = ""
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
) -> tuple[graphviz.Digraph, dict]:
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
    has_children = set(df_use["Atasan"]) - {""}
    grouped_rows = []  # rows whose Level is collapsed -> summarized instead
    expanded_rows = []
    for _, row in df_use.iterrows():
        if not row["Nama"]:
            continue
        # Orang yang jadi atasan bagi orang lain TIDAK BOLEH diringkas,
        # walaupun levelnya masuk daftar collapse â€” kalau diringkas, node-nya
        # hilang dan anak buahnya jadi tidak punya tempat nempel (orphan).
        if row["Level"] in collapse_levels and row["Nama"] not in has_children:
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
        g = groups.setdefault(key, {"count": 0, "names": []})
        g["count"] += 1
        g["names"].append(row["Nama"])

    group_details: dict[str, dict] = {}
    for i, ((parent, jabatan, level), g) in enumerate(groups.items()):
        node_id = f"grp_{i}"
        label = f"{jabatan or level}\n({g['count']} orang)"
        graph.node(node_id, label, fillcolor=color_for(level), fontsize=fsize)
        if parent and parent in names_seen:
            graph.edge(parent, node_id, style="dashed")
        group_details[node_id] = {"jabatan": jabatan or level, "names": g["names"]}

    return graph, group_details


# ============================================================
# HELPER: Build hierarchy maps for JS interaction
# ============================================================
def build_hierarchy_maps(df: pd.DataFrame) -> dict:
    """Build parent_map and node_info for JavaScript breadcrumb + highlighting."""
    parent_map = {}  # child -> parent
    node_info = {}   # name -> {jabatan, level}
    children_map = {}  # parent -> [children]

    for _, row in df.iterrows():
        name = str(row["Nama"]).strip()
        if not name:
            continue
        jabatan = str(row.get("Jabatan", "")).strip()
        level = str(row.get("Level", "")).strip()
        atasan = str(row.get("Atasan", "")).strip()

        node_info[name] = {"jabatan": jabatan, "level": level}
        if atasan:
            parent_map[name] = atasan
            children_map.setdefault(atasan, []).append(name)

    return {
        "parent_map": parent_map,
        "node_info": node_info,
        "children_map": children_map,
    }


# ============================================================
# LAYOUT â€” TABS
# ============================================================
tab_chart, tab_editor = st.tabs(["ðŸ“Š Bagan Organisasi", "ðŸ“„ Lihat Data Sheets"])

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
    stat_cols[0].metric("ðŸ‘¥ Total Posisi", total_posisi)
    stat_cols[1].metric("âœ… Terisi", total_terisi)
    stat_cols[2].metric("ðŸ”´ Vacant", total_vacant)
    level_counts = data_df[~vacant_mask]["Level"].value_counts()
    top_level = level_counts.idxmax() if not level_counts.empty else "-"
    stat_cols[3].metric("ðŸ“Œ Level Terbanyak", top_level)

    with st.expander("ðŸ“Š Rincian jumlah per level"):
        st.dataframe(
            data_df[data_df["Nama"] != ""]["Level"]
            .value_counts()
            .rename_axis("Level")
            .reset_index(name="Jumlah"),
            use_container_width=True, hide_index=True,
        )

    # ---------- SPAN OF CONTROL ----------
    with st.expander("ðŸ† Papan Span of Control (anak buah langsung terbanyak)"):
        span_df = (
            data_df[(data_df["Atasan"] != "") & (~vacant_mask)]
            .groupby("Atasan").size().rename("Jumlah Anak Buah")
            .sort_values(ascending=False).head(15).reset_index()
            .rename(columns={"Atasan": "Nama"})
        )
        jabatan_map = dict(zip(data_df["Nama"], data_df["Jabatan"]))
        span_df["Jabatan"] = span_df["Nama"].map(jabatan_map)
        if not span_df.empty:
            click_selection = alt.selection_point(
                name="bar_select", fields=["Nama"], on="click", empty=False,
            )
            chart = (
                alt.Chart(span_df)
                .mark_bar(color="#3b82f6")
                .encode(
                    x=alt.X(
                        "Jumlah Anak Buah:Q", title="Jumlah Anak Buah",
                        axis=alt.Axis(format="d", tickMinStep=1),
                    ),
                    y=alt.Y("Nama:N", sort="-x", title=None),
                    opacity=alt.condition(click_selection, alt.value(1), alt.value(0.65)),
                    tooltip=["Nama", "Jabatan", "Jumlah Anak Buah"],
                )
                .add_params(click_selection)
                .properties(height=max(28 * len(span_df), 200))
            )
            span_event = st.altair_chart(
                chart, use_container_width=True, on_select="rerun", key="span_chart",
            )
            clicked = []
            if span_event and "selection" in span_event:
                clicked = span_event["selection"].get("bar_select", [])
            if clicked:
                clicked_name = clicked[0]["Nama"]
                reports = data_df[
                    (data_df["Atasan"] == clicked_name) & (~vacant_mask)
                ][["Nama", "Jabatan"]].reset_index(drop=True)
                st.caption(f"ðŸ‘¥ Anak buah langsung â€” **{clicked_name}** ({len(reports)} orang):")
                st.dataframe(reports, use_container_width=True, hide_index=True)
            else:
                st.caption("ðŸ’¡ Klik salah satu batang untuk lihat daftar anak buahnya.")

            st.dataframe(
                span_df[["Nama", "Jabatan", "Jumlah Anak Buah"]],
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption("Belum ada data hubungan atasan-bawahan.")

    # ---------- PENCARIAN NAMA ----------
    search_query = st.text_input("ðŸ” Cari nama", placeholder="Ketik nama, mis. Firmansyah")
    search_matched: set = set()
    if search_query.strip():
        search_matched = set(
            data_df[data_df["Nama"].str.contains(search_query.strip(), case=False, na=False)]["Nama"]
        )
        if not search_matched:
            st.warning(f"Tidak ditemukan nama yang cocok dengan '{search_query}'.")

    # ---------- FILTER PROJECT ----------
    project_selected = None
    if "Project" in data_df.columns:
        projects_present = sorted(p for p in data_df["Project"].unique() if p)
        if projects_present:
            project_selected = st.selectbox(
                "ðŸ—ï¸ Filter per Project", ["Semua"] + projects_present, key="project_filter",
            )
            if project_selected == "Semua":
                project_selected = None

    levels_present = [l for l in data_df["Level"].unique() if l]
    if levels_present:
        st.caption("ðŸ‘‰ Klik level untuk fokus ke bagian itu saja (lebih mudah dibaca):")
        cols = st.columns(len(levels_present) + 1)
        for i, lvl in enumerate(levels_present):
            is_active = st.session_state.focus_level == lvl
            with cols[i]:
                if st.button(
                    ("â— " if is_active else "") + lvl, key=f"btn_{lvl}",
                    type="primary" if is_active else "secondary",
                ):
                    st.session_state.focus_level = None if is_active else lvl
                    st.rerun()
        with cols[-1]:
            if st.button("â†º Semua", key="btn_reset"):
                st.session_state.focus_level = None
                st.rerun()

    # Prioritas: pencarian nama > filter project > fokus level
    if search_matched:
        active_matched = search_matched
        active_label = f"Hasil pencarian '{search_query}'"
    elif project_selected:
        active_matched = set(data_df[data_df["Project"] == project_selected]["Nama"])
        active_label = f"Project: {project_selected}"
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
            "âš ï¸ Mode Kiri ke Kanan menumpuk banyak anak-buah secara vertikal,"
            " jadi untuk tampilan 'Semua' bisa jadi sangat panjang ke bawah."
            " Lebih pas dipakai saat fokus ke satu level (klik salah satu"
            " tombol level di atas)."
        )

    MANAGEMENT_LEVELS = {"Head", "Manager", "Asst. Manager", "Supervisor", "Leader"}
    default_collapse = [l for l in levels_present if l not in MANAGEMENT_LEVELS]
    with st.expander("ðŸ—œï¸ Atur level yang diringkas (khusus tampilan 'Semua')", expanded=False):
        collapse_choice = st.multiselect(
            "Level ini akan ditampilkan sebagai 1 kotak ringkasan (n orang),"
            " bukan nama satu-satu:",
            options=levels_present, default=default_collapse,
        )
    collapse_levels = set(collapse_choice) if not active_matched else set()

    frame_height = 550  # batas maksimal tinggi area chart (px); tinggi asli tetap dipakai jika lebih pendek

    org_graph, group_details = build_org_graph(
        data_df, active_matched, rankdir, collapse_levels,
        nodesep=0.3, ranksep=0.55,
    )

    # Build hierarchy data for JS breadcrumb + highlight
    hierarchy_data = build_hierarchy_maps(data_df)
    hierarchy_json = json.dumps(hierarchy_data, ensure_ascii=False)

    try:
        svg_source = org_graph.pipe(format="svg").decode("utf-8")
        height_match = re.search(r'height="(\d+)pt"', svg_source)
        native_height_px = int(int(height_match.group(1)) * 1.3333) if height_match else frame_height
        display_height = min(native_height_px + 20, frame_height)
        group_details_json = json.dumps(group_details, ensure_ascii=False)
        frame_html = f"""
        <div style="position: relative; width: 100%;">

            <!-- BREADCRUMB BAR -->
            <div id="orgBreadcrumb" style="
                display: none;
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px 14px;
                margin-bottom: 8px;
                font-family: Helvetica, sans-serif;
                animation: fadeIn 0.3s ease;
            ">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <div style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">
                            Reporting Chain
                        </div>
                        <div id="orgBreadcrumbPath" style="font-size: 13px; color: #e2e8f0; line-height: 1.6;"></div>
                        <div id="orgBreadcrumbInfo" style="font-size: 11px; color: #94a3b8; margin-top: 4px;"></div>
                    </div>
                    <span onclick="orgClearHighlight()" style="
                        cursor: pointer; color: #94a3b8; font-size: 18px;
                        padding: 0 4px; margin-left: 12px; line-height: 1;
                        border-radius: 4px; transition: color 0.2s;
                    " onmouseover="this.style.color='#f8fafc'" onmouseout="this.style.color='#94a3b8'"
                    title="Tutup & reset highlight">&times;</span>
                </div>
            </div>

            <!-- LEGEND FOR HIGHLIGHT COLORS -->
            <div id="orgHighlightLegend" style="
                display: none;
                padding: 6px 14px;
                margin-bottom: 6px;
                font-family: Helvetica, sans-serif;
                font-size: 11px;
                color: #94a3b8;
            ">
                <span style="display: inline-flex; align-items: center; margin-right: 16px;">
                    <span style="width: 14px; height: 14px; border-radius: 3px; background: #f59e0b; display: inline-block; margin-right: 5px; border: 2px solid #fbbf24;"></span>
                    Ke atas (atasan)
                </span>
                <span style="display: inline-flex; align-items: center; margin-right: 16px;">
                    <span style="width: 14px; height: 14px; border-radius: 3px; background: #06b6d4; display: inline-block; margin-right: 5px; border: 2px solid #22d3ee;"></span>
                    Ke bawah (bawahan)
                </span>
                <span style="display: inline-flex; align-items: center;">
                    <span style="width: 14px; height: 14px; border-radius: 3px; background: #ef4444; display: inline-block; margin-right: 5px; border: 2px solid #f87171;"></span>
                    Orang yang diklik
                </span>
            </div>

            <!-- ZOOM CONTROLS -->
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
                ">-</button>
                <button onclick="orgZoom(0)" title="Reset zoom" style="
                    width: 26px; height: 26px; border-radius: 4px; border: none;
                    background: #1e293b; color: #94a3b8; font-size: 11px; cursor: pointer;
                ">&#x27F2;</button>
            </div>

            <!-- SVG CHART CONTAINER -->
            <div id="orgScrollBox" style="
                width: 100%; height: {display_height}px; overflow: auto;
                border: 1px solid #334155; border-radius: 8px;
            ">
                <div id="orgSvgWrap" style="zoom: 1;">{svg_source}</div>
            </div>

            <!-- EXPORT BUTTONS (client-side â€” captures the chart exactly as displayed) -->
            <div id="orgExportBar" style="
                display: flex; gap: 8px; padding: 10px 0 4px 0;
                font-family: Helvetica, sans-serif;
            ">
                <button onclick="orgExportChart('pdf')" style="
                    flex: 1; padding: 10px 0; border-radius: 8px; border: 1px solid #334155;
                    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
                    color: #e2e8f0; font-size: 13px; font-weight: 600; cursor: pointer;
                    transition: all 0.2s;
                " onmouseover="this.style.borderColor='#3b82f6'" onmouseout="this.style.borderColor='#334155'">
                    &#x1F4C4; Download PDF
                </button>
                <button onclick="orgExportChart('png')" style="
                    flex: 1; padding: 10px 0; border-radius: 8px; border: 1px solid #334155;
                    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
                    color: #e2e8f0; font-size: 13px; font-weight: 600; cursor: pointer;
                    transition: all 0.2s;
                " onmouseover="this.style.borderColor='#3b82f6'" onmouseout="this.style.borderColor='#334155'">
                    &#x1F5BC; Download PNG
                </button>
            </div>
            <div id="orgExportStatus" style="
                display: none; text-align: center; padding: 6px;
                font-family: Helvetica, sans-serif; font-size: 12px; color: #94a3b8;
            "></div>

            <!-- MODAL FOR GROUPED NODES -->
            <div id="orgModalOverlay" onclick="orgCloseModal(event)" style="
                display: none; position: fixed; inset: 0; z-index: 1000;
                background: rgba(0,0,0,0.55); align-items: center; justify-content: center;
            ">
                <div style="
                    background: #0f172a; border: 1px solid #334155; border-radius: 10px;
                    padding: 16px 18px; max-width: 320px; max-height: 70vh; overflow-y: auto;
                    font-family: Helvetica, sans-serif; box-shadow: 0 8px 24px rgba(0,0,0,0.5);
                ">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <strong id="orgModalTitle" style="color:#f8fafc; font-size:14px;"></strong>
                        <span onclick="orgCloseModal(event, true)" style="cursor:pointer; color:#94a3b8; font-size:16px; padding-left:12px;">&times;</span>
                    </div>
                    <ol id="orgModalList" style="margin:0; padding-left:18px; color:#cbd5e1; font-size:13px; line-height:1.7;"></ol>
                </div>
            </div>
        </div>

        <!-- jsPDF for PDF export -->
        <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.2/jspdf.umd.min.js"></script>

        <style>
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(-6px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            .org-node-clickable {{
                cursor: pointer;
                transition: opacity 0.2s;
            }}
            .org-node-clickable:hover {{
                opacity: 0.85;
            }}
        </style>

        <script>
            // â”€â”€ Zoom â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            let orgZoomLevel = 1;
            function orgZoom(delta) {{
                orgZoomLevel = delta === 0 ? 1 : Math.min(3, Math.max(0.3, orgZoomLevel + delta));
                document.getElementById('orgSvgWrap').style.zoom = orgZoomLevel;
                document.getElementById('orgZoomLabel').innerText = Math.round(orgZoomLevel * 100) + '%';
            }}

            // â”€â”€ Group details modal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            const orgGroupDetails = {group_details_json};

            function orgOpenModal(nodeId) {{
                const info = orgGroupDetails[nodeId];
                if (!info) return;
                document.getElementById('orgModalTitle').innerText = info.jabatan + ' (' + info.names.length + ' orang)';
                const list = document.getElementById('orgModalList');
                list.innerHTML = '';
                info.names.forEach(n => {{
                    const li = document.createElement('li');
                    li.innerText = n;
                    list.appendChild(li);
                }});
                document.getElementById('orgModalOverlay').style.display = 'flex';
            }}
            function orgCloseModal(e, force) {{
                if (force || e.target.id === 'orgModalOverlay') {{
                    document.getElementById('orgModalOverlay').style.display = 'none';
                }}
            }}

            // â”€â”€ Hierarchy data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            const orgHierarchy = {hierarchy_json};
            const parentMap = orgHierarchy.parent_map;       // child -> parent
            const nodeInfo = orgHierarchy.node_info;         // name -> {{jabatan, level}}
            const childrenMap = orgHierarchy.children_map;   // parent -> [children]

            // â”€â”€ State tracking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            let orgOriginalStyles = [];  // saved styles to restore
            let orgHighlightActive = false;

            // â”€â”€ Compute ancestor chain (bottom-up) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            function getAncestors(name) {{
                const chain = [];
                let cur = parentMap[name];
                while (cur) {{
                    chain.push(cur);
                    cur = parentMap[cur] || null;
                }}
                return chain;  // nearest first, top last
            }}

            // â”€â”€ Compute all descendants (top-down BFS) â”€â”€â”€â”€â”€â”€
            function getDescendants(name) {{
                const result = [];
                const queue = childrenMap[name] ? [...childrenMap[name]] : [];
                while (queue.length > 0) {{
                    const n = queue.shift();
                    result.push(n);
                    if (childrenMap[n]) {{
                        queue.push(...childrenMap[n]);
                    }}
                }}
                return result;
            }}

            // â”€â”€ Build breadcrumb HTML â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            function buildBreadcrumb(name) {{
                const ancestors = getAncestors(name);
                ancestors.reverse();  // top first
                const chain = [...ancestors, name];

                let html = '';
                chain.forEach((n, i) => {{
                    const info = nodeInfo[n] || {{}};
                    const isTarget = (n === name);
                    const color = isTarget ? '#ef4444' : (i < chain.length - 1 ? '#fbbf24' : '#e2e8f0');
                    const weight = isTarget ? '700' : '400';

                    if (i > 0) {{
                        html += '<span style="color: #475569; margin: 0 5px;">&#x2192;</span>';
                    }}
                    html += '<span style="color:' + color + '; font-weight:' + weight + ';">' + n;
                    if (info.jabatan) {{
                        html += ' <span style="color:#64748b; font-size:11px;">(' + info.jabatan + ')</span>';
                    }}
                    html += '</span>';
                }});

                return html;
            }}

            // â”€â”€ Dim all nodes and edges â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            function dimAll() {{
                orgOriginalStyles = [];

                // Save & dim all nodes
                document.querySelectorAll('#orgSvgWrap .node').forEach(g => {{
                    const poly = g.querySelector('polygon, ellipse, rect, path');
                    const texts = g.querySelectorAll('text');
                    if (poly) {{
                        orgOriginalStyles.push({{
                            el: poly,
                            fill: poly.getAttribute('fill'),
                            stroke: poly.getAttribute('stroke'),
                            strokeWidth: poly.getAttribute('stroke-width'),
                        }});
                        poly.setAttribute('opacity', '0.2');
                    }}
                    texts.forEach(t => {{
                        orgOriginalStyles.push({{ el: t, opacity: t.getAttribute('opacity') }});
                        t.setAttribute('opacity', '0.2');
                    }});
                }});

                // Save & dim all edges
                document.querySelectorAll('#orgSvgWrap .edge').forEach(g => {{
                    const path = g.querySelector('path');
                    const arrow = g.querySelector('polygon');
                    if (path) {{
                        orgOriginalStyles.push({{
                            el: path,
                            stroke: path.getAttribute('stroke'),
                            strokeWidth: path.getAttribute('stroke-width'),
                            opacity: path.getAttribute('opacity'),
                        }});
                        path.setAttribute('opacity', '0.1');
                    }}
                    if (arrow) {{
                        orgOriginalStyles.push({{
                            el: arrow,
                            fill: arrow.getAttribute('fill'),
                            stroke: arrow.getAttribute('stroke'),
                            opacity: arrow.getAttribute('opacity'),
                        }});
                        arrow.setAttribute('opacity', '0.1');
                    }}
                }});
            }}

            // â”€â”€ Highlight specific node â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            function highlightNode(name, borderColor) {{
                document.querySelectorAll('#orgSvgWrap .node').forEach(g => {{
                    const titleEl = g.querySelector('title');
                    if (!titleEl) return;
                    const nodeId = titleEl.textContent.trim();
                    if (nodeId !== name) return;

                    const poly = g.querySelector('polygon, ellipse, rect, path');
                    const texts = g.querySelectorAll('text');
                    if (poly) {{
                        poly.setAttribute('opacity', '1');
                        poly.setAttribute('stroke', borderColor);
                        poly.setAttribute('stroke-width', '3');
                    }}
                    texts.forEach(t => t.setAttribute('opacity', '1'));
                }});
            }}

            // â”€â”€ Highlight specific edge â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            function highlightEdge(parentName, childName, color) {{
                document.querySelectorAll('#orgSvgWrap .edge').forEach(g => {{
                    const titleEl = g.querySelector('title');
                    if (!titleEl) return;
                    const edgeTitle = titleEl.textContent.trim();
                    // Graphviz edge title format: "parent->child"
                    // Handle both with and without spaces
                    const expected1 = parentName + '->' + childName;
                    const expected2 = parentName + ' -> ' + childName;
                    if (edgeTitle !== expected1 && edgeTitle !== expected2) return;

                    const path = g.querySelector('path');
                    const arrow = g.querySelector('polygon');
                    if (path) {{
                        path.setAttribute('stroke', color);
                        path.setAttribute('stroke-width', '2.5');
                        path.setAttribute('opacity', '1');
                    }}
                    if (arrow) {{
                        arrow.setAttribute('fill', color);
                        arrow.setAttribute('stroke', color);
                        arrow.setAttribute('opacity', '1');
                    }}
                }});
            }}

            // â”€â”€ Main highlight function â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            function orgHighlightChain(name) {{
                // If clicking same node again, clear
                if (orgHighlightActive === name) {{
                    orgClearHighlight();
                    return;
                }}

                // Dim everything first
                dimAll();

                const ancestors = getAncestors(name);
                const descendants = getDescendants(name);

                // Highlight ancestors (gold/amber) â€” ke atas
                ancestors.forEach(a => highlightNode(a, '#fbbf24'));

                // Highlight ancestor edges (gold)
                const ancestorChain = [...ancestors.reverse(), name];
                for (let i = 0; i < ancestorChain.length - 1; i++) {{
                    highlightEdge(ancestorChain[i], ancestorChain[i + 1], '#fbbf24');
                }}

                // Highlight descendants (cyan) â€” ke bawah
                descendants.forEach(d => highlightNode(d, '#22d3ee'));

                // Highlight descendant edges (cyan) using BFS
                const queue = [name];
                while (queue.length > 0) {{
                    const cur = queue.shift();
                    const kids = childrenMap[cur] || [];
                    kids.forEach(kid => {{
                        if (descendants.includes(kid)) {{
                            highlightEdge(cur, kid, '#22d3ee');
                            queue.push(kid);
                        }}
                    }});
                }}

                // Highlight clicked node itself (red â€” paling menonjol)
                highlightNode(name, '#f87171');

                // Show breadcrumb
                const breadcrumbEl = document.getElementById('orgBreadcrumb');
                const pathEl = document.getElementById('orgBreadcrumbPath');
                const infoEl = document.getElementById('orgBreadcrumbInfo');
                const legendEl = document.getElementById('orgHighlightLegend');

                pathEl.innerHTML = buildBreadcrumb(name);

                const directReports = (childrenMap[name] || []).length;
                const totalDown = descendants.length;
                const depth = getAncestors(name).length;
                let infoText = 'Level kedalaman: ' + depth + ' dari atas';
                if (directReports > 0) {{
                    infoText += ' | Anak buah langsung: ' + directReports;
                    if (totalDown > directReports) {{
                        infoText += ' | Total bawahan: ' + totalDown;
                    }}
                }}
                infoEl.innerText = infoText;

                breadcrumbEl.style.display = 'block';
                legendEl.style.display = 'block';

                orgHighlightActive = name;
            }}

            // â”€â”€ Clear all highlights â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            function orgClearHighlight() {{
                // Restore opacity for all nodes and edges
                document.querySelectorAll('#orgSvgWrap .node').forEach(g => {{
                    const poly = g.querySelector('polygon, ellipse, rect, path');
                    const texts = g.querySelectorAll('text');
                    if (poly) {{
                        poly.setAttribute('opacity', '1');
                    }}
                    texts.forEach(t => t.setAttribute('opacity', '1'));
                }});

                document.querySelectorAll('#orgSvgWrap .edge').forEach(g => {{
                    const path = g.querySelector('path');
                    const arrow = g.querySelector('polygon');
                    if (path) path.setAttribute('opacity', '1');
                    if (arrow) arrow.setAttribute('opacity', '1');
                }});

                // Restore original styles (stroke, fill, etc.)
                orgOriginalStyles.forEach(s => {{
                    if (s.fill !== undefined && s.el.tagName !== 'text') s.el.setAttribute('fill', s.fill || '');
                    if (s.stroke !== undefined) s.el.setAttribute('stroke', s.stroke || '');
                    if (s.strokeWidth !== undefined) s.el.setAttribute('stroke-width', s.strokeWidth || '');
                }});
                orgOriginalStyles = [];

                // Hide breadcrumb
                document.getElementById('orgBreadcrumb').style.display = 'none';
                document.getElementById('orgHighlightLegend').style.display = 'none';

                orgHighlightActive = false;
            }}

            // â”€â”€ Attach click handlers to all nodes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            document.querySelectorAll('#orgSvgWrap .node').forEach(g => {{
                const titleEl = g.querySelector('title');
                if (!titleEl) return;
                const nodeId = titleEl.textContent.trim();

                // Group nodes: open modal
                if (orgGroupDetails[nodeId]) {{
                    g.style.cursor = 'pointer';
                    g.addEventListener('click', () => orgOpenModal(nodeId));
                }}
                // Individual nodes: highlight chain + breadcrumb
                else if (nodeInfo[nodeId]) {{
                    g.style.cursor = 'pointer';
                    g.classList.add('org-node-clickable');
                    g.addEventListener('click', (e) => {{
                        e.stopPropagation();
                        orgHighlightChain(nodeId);
                    }});
                }}
            }});

            // â”€â”€ EXPORT: Capture SVG as displayed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            function orgShowExportStatus(msg) {{
                const el = document.getElementById('orgExportStatus');
                el.innerText = msg;
                el.style.display = 'block';
                setTimeout(() => {{ el.style.display = 'none'; }}, 3000);
            }}

            function orgGetSvgForExport() {{
                const svgEl = document.querySelector('#orgSvgWrap svg');
                if (!svgEl) return null;

                // Clone SVG to avoid mutating the displayed version
                const clone = svgEl.cloneNode(true);

                // Remove transparent bg, add white background rect
                clone.removeAttribute('style');
                const bbox = svgEl.getBBox ? svgEl.getBBox() : null;
                const w = clone.getAttribute('width') || (bbox ? bbox.width + 20 : 800);
                const h = clone.getAttribute('height') || (bbox ? bbox.height + 20 : 600);

                // Insert white rect as first child for background
                const ns = 'http://www.w3.org/2000/svg';
                const bgRect = document.createElementNS(ns, 'rect');
                bgRect.setAttribute('width', '100%');
                bgRect.setAttribute('height', '100%');
                bgRect.setAttribute('fill', '#ffffff');
                clone.insertBefore(bgRect, clone.firstChild);

                // Inline all computed styles onto SVG elements for faithful export
                const allEls = clone.querySelectorAll('*');
                const srcEls = svgEl.querySelectorAll('*');
                for (let i = 0; i < Math.min(allEls.length, srcEls.length); i++) {{
                    const computed = window.getComputedStyle(srcEls[i]);
                    // Copy key visual styles
                    ['fill', 'stroke', 'stroke-width', 'opacity', 'font-family', 'font-size',
                     'font-weight', 'fill-opacity', 'stroke-opacity'].forEach(prop => {{
                        const val = computed.getPropertyValue(prop);
                        if (val) allEls[i].style[prop.replace(/-([a-z])/g, (m,c) => c.toUpperCase())] = val;
                    }});
                    // Copy explicit attributes that JS may have changed
                    ['fill', 'stroke', 'stroke-width', 'opacity'].forEach(attr => {{
                        const v = srcEls[i].getAttribute(attr);
                        if (v !== null) allEls[i].setAttribute(attr, v);
                    }});
                }}

                return {{ clone, w, h }};
            }}

            function orgSvgToCanvas(svgClone, w, h) {{
                return new Promise((resolve, reject) => {{
                    const serializer = new XMLSerializer();
                    const svgString = serializer.serializeToString(svgClone);
                    const svgBlob = new Blob([svgString], {{type: 'image/svg+xml;charset=utf-8'}});
                    const url = URL.createObjectURL(svgBlob);

                    const img = new Image();
                    img.onload = function() {{
                        // 2x scale for crisp export
                        const scale = 2;
                        const canvas = document.createElement('canvas');
                        canvas.width = img.naturalWidth * scale;
                        canvas.height = img.naturalHeight * scale;
                        const ctx = canvas.getContext('2d');
                        ctx.scale(scale, scale);
                        ctx.fillStyle = '#ffffff';
                        ctx.fillRect(0, 0, img.naturalWidth, img.naturalHeight);
                        ctx.drawImage(img, 0, 0);
                        URL.revokeObjectURL(url);
                        resolve({{ canvas, imgW: img.naturalWidth, imgH: img.naturalHeight }});
                    }};
                    img.onerror = function(e) {{
                        URL.revokeObjectURL(url);
                        reject(e);
                    }};
                    img.src = url;
                }});
            }}

            function orgExportChart(format) {{
                const result = orgGetSvgForExport();
                if (!result) {{
                    orgShowExportStatus('Error: SVG tidak ditemukan');
                    return;
                }}

                orgShowExportStatus('Memproses export...');

                const {{ clone, w, h }} = result;

                if (format === 'png') {{
                    orgSvgToCanvas(clone, w, h).then(({{ canvas }}) => {{
                        canvas.toBlob(function(blob) {{
                            const a = document.createElement('a');
                            a.href = URL.createObjectURL(blob);
                            a.download = 'org_chart_{selected_sheet_name}.png';
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                            orgShowExportStatus('PNG berhasil didownload!');
                        }}, 'image/png');
                    }}).catch(() => {{
                        orgShowExportStatus('Gagal export PNG');
                    }});
                }}
                else if (format === 'pdf') {{
                    orgSvgToCanvas(clone, w, h).then(({{ canvas, imgW, imgH }}) => {{
                        try {{
                            const {{ jsPDF }} = window.jspdf;
                            const padding = 30;
                            const pageW = imgW + padding * 2;
                            const pageH = imgH + padding * 2;
                            const isLandscape = imgW > imgH;

                            const pdf = new jsPDF({{
                                orientation: isLandscape ? 'landscape' : 'portrait',
                                unit: 'px',
                                format: [pageW, pageH],
                                hotfixes: ['px_scaling']
                            }});

                            const imgData = canvas.toDataURL('image/png', 1.0);
                            pdf.addImage(imgData, 'PNG', padding, padding, imgW, imgH);
                            pdf.save('org_chart_{selected_sheet_name}.pdf');
                            orgShowExportStatus('PDF berhasil didownload!');
                        }} catch(e) {{
                            console.error(e);
                            orgShowExportStatus('Gagal export PDF, coba PNG');
                        }}
                    }}).catch(() => {{
                        orgShowExportStatus('Gagal export PDF');
                    }});
                }}
            }}
        </script>
        """
        components.html(frame_html, height=display_height + 140, scrolling=False)
    except Exception:
        st.info(
            "âš ï¸ Belum bisa render mode frame-scroll (kemungkinan `packages.txt`"
            " berisi `graphviz` belum ter-deploy di server). Menampilkan mode"
            " biasa untuk sementara."
        )
        st.graphviz_chart(org_graph, use_container_width=False)

    if active_matched:
        st.markdown(f"##### ðŸ“‹ Detail â€” {active_label}")
        detail_cols = ["Nama", "Jabatan", "Atasan"]
        if "Project" in data_df.columns:
            detail_cols.append("Project")
        detail_df = data_df[data_df["Nama"].isin(active_matched)][
            detail_cols
        ].reset_index(drop=True)
        st.dataframe(detail_df, use_container_width=True, hide_index=True)

with tab_editor:
    st.subheader("ðŸ“„ Data Google Sheets")
    st.info(
        "Tampilan ini hanya untuk melihat data (read-only) â€” tidak ada"
        " perubahan yang bisa disimpan kembali ke Google Sheets dari sini."
    )
    st.dataframe(data_df, use_container_width=True, hide_index=True)
