import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import streamlit as st
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
st.write(
    "Bagan organisasi dibangun dari tabel data eksplisit (Nama, Jabatan,"
    " Level, Atasan) — setiap baris = satu orang, jadi tidak ada tebakan"
    " posisi baris/kolom dan hasilnya selalu akurat."
)

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

st.info(
    "📋 Pilih worksheet yang berisi **tabel data terstruktur** dengan kolom:"
    " `Nama`, `Jabatan`, `Level` (opsional), `Atasan` (nama atasan langsung —"
    " kosongkan untuk posisi paling atas). Ini BUKAN worksheet 'JDC Warehouse'"
    " mentah yang formatnya visual/bebas."
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

# ============================================================
# BUILD ORG TREE
# ============================================================
PALETTE = {
    "Head": "#1e3a8a",
    "Manager": "#4338ca",
    "Asst. Manager": "#7c3aed",
    "Supervisor": "#0f766e",
    "Leader": "#0891b2",
    "Staff": "#334155",
}
DEFAULT_COLOR = "#334155"


def color_for(level: str) -> str:
    return PALETTE.get(level, DEFAULT_COLOR)


def build_org_graph(
    df: pd.DataFrame, focus_level: str | None, rankdir: str, collapse_levels: set,
    nodesep: float = 0.25, ranksep: float = 0.5,
) -> tuple[graphviz.Digraph, set]:
    parent_map = dict(zip(df["Nama"], df["Atasan"]))
    children_map: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        if row["Nama"] and row["Atasan"]:
            children_map.setdefault(row["Atasan"], []).append(row["Nama"])

    matched: set = set()
    if focus_level:
        matched = set(df[df["Level"] == focus_level]["Nama"])
        include = set()
        for name in matched:
            cur = name
            while cur:
                include.add(cur)
                cur = parent_map.get(cur, "")
        for name in matched:
            include.update(children_map.get(name, []))
        df_use = df[df["Nama"].isin(include)]
        collapse_levels = set()  # detail view is always fully expanded
    else:
        df_use = df

    graph = graphviz.Digraph()
    graph.attr(
        rankdir=rankdir, bgcolor="transparent", nodesep=str(nodesep), ranksep=str(ranksep),
        splines="line",
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

    return graph, matched


# ============================================================
# LAYOUT — TABS
# ============================================================
tab_chart, tab_editor = st.tabs(["📊 Bagan Organisasi", "📝 Edit Data Sheets"])

with tab_chart:
    st.subheader(f"Struktur: {selected_sheet_name}")

    if "focus_level" not in st.session_state:
        st.session_state.focus_level = None

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
    if rankdir == "LR" and not st.session_state.focus_level:
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
    collapse_levels = set(collapse_choice) if not st.session_state.focus_level else set()

    zcol1, zcol2 = st.columns(2)
    with zcol1:
        nodesep = st.slider(
            "↔️ Perbesar jarak horizontal (antar kotak sejajar)",
            min_value=0.1, max_value=1.5, value=0.25, step=0.05, key="nodesep_slider",
        )
    with zcol2:
        ranksep = st.slider(
            "↕️ Perbesar jarak vertikal (antar level)",
            min_value=0.2, max_value=2.0, value=0.5, step=0.05, key="ranksep_slider",
        )

    org_graph, matched = build_org_graph(
        data_df, st.session_state.focus_level, rankdir, collapse_levels,
        nodesep=nodesep, ranksep=ranksep,
    )
    st.graphviz_chart(org_graph, use_container_width=False)

    if st.session_state.focus_level and matched:
        st.markdown(f"##### 📋 Detail — {st.session_state.focus_level}")
        detail_df = data_df[data_df["Nama"].isin(matched)][
            ["Nama", "Jabatan", "Atasan"]
        ].reset_index(drop=True)
        st.dataframe(detail_df, use_container_width=True, hide_index=True)

with tab_editor:
    st.subheader("📝 Edit Data Google Sheets")
    st.info(
        "Setiap perubahan pada tabel di bawah akan memperbarui database Google"
        " Sheet Anda."
    )

    edited_df = st.data_editor(
        data_df, num_rows="dynamic", key=f"editor_{selected_sheet_name}"
    )

    if st.button("💾 Simpan Perubahan ke Google Sheets", type="primary"):
        try:
            worksheet.clear()
            set_with_dataframe(worksheet, edited_df)
            st.success("Berhasil memperbarui Google Sheets! 🎉")
            st.rerun()
        except Exception as e:
            st.error(f"Gagal menyimpan: {e}")
