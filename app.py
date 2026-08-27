import re
from collections import defaultdict

import gspread
from gspread_dataframe import set_with_dataframe
import pandas as pd
import streamlit as st
import graphviz

st.set_page_config(
    page_title="Enterprise Org Chart - JDC Warehouse", layout="wide"
)

# ============================================================
# STYLING
# ============================================================
st.markdown(
    """
    <style>
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
    </style>
""",
    unsafe_allow_html=True,
)

st.title("🏢 Enterprise Organizational Chart Dashboard")
st.write(
    "Bagan organisasi otomatis dari layout grid Google Sheets Anda"
    " (judul jabatan di atas, nama di bawahnya, per kolom = per cabang)."
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

default_index = (
    worksheet_list.index("JDC Warehouse") if "JDC Warehouse" in worksheet_list else 0
)
selected_sheet_name = st.selectbox(
    "📌 Pilih Cabang / Worksheet Gudang:", worksheet_list, index=default_index
)
worksheet = sh.worksheet(selected_sheet_name)
raw_values = worksheet.get_all_values()  # list[list[str]], index 0 = baris sheet ke-1
n_rows = len(raw_values)
n_cols = max((len(r) for r in raw_values), default=0)

# ============================================================
# SIDEBAR — KONFIGURASI LEVEL (SESUAIKAN DENGAN NOMOR BARIS SHEET ANDA)
# ============================================================
st.sidebar.header("⚙️ Konfigurasi Level Hierarki")
st.sidebar.caption(
    "Setiap level dimulai di baris ini (nomor baris asli di Google Sheets)."
    " Sesuaikan angkanya jika bagan yang muncul kurang tepat — level terakhir"
    " otomatis dianggap sebagai staff/anggota individu, bukan blok jabatan."
)

default_levels = [
    ("Head", 4),
    ("Manager", 8),
    ("Asst. Manager", 12),
    ("Supervisor", 17),
    ("Leader", 21),
    ("Staff / Admin", 27),
]

level_defs = []
for label, default_row in default_levels:
    row = st.sidebar.number_input(
        f"Mulai baris — {label}", min_value=1, max_value=max(n_rows, 1),
        value=min(default_row, max(n_rows, 1)), key=f"lvl_{label}",
    )
    level_defs.append((label, int(row)))

ignore_after_row = st.sidebar.number_input(
    "Abaikan baris setelah (catatan/footer)", min_value=1,
    max_value=max(n_rows, 1), value=min(82, max(n_rows, 1)),
)
max_members_shown = st.sidebar.slider(
    "Maks. nama ditampilkan per kotak jabatan", 1, 20, 5
)

level_defs_sorted = sorted(level_defs, key=lambda x: x[1])
STAFF_LEVEL = level_defs_sorted[-1][0]

# ============================================================
# HELPERS
# ============================================================
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def is_number(s: str) -> bool:
    return NUM_RE.match(s.strip()) is not None


def clean(s: str) -> str:
    s = s.strip()
    if s.startswith("-"):
        s = s[1:].strip()
    return s


def cell(r0: int, c0: int) -> str:
    if r0 < 0 or r0 >= n_rows:
        return ""
    row = raw_values[r0]
    if c0 < 0 or c0 >= len(row):
        return ""
    return row[c0].strip()


def level_row_ranges():
    ranges = {}
    for i, (label, start) in enumerate(level_defs_sorted):
        end = (
            level_defs_sorted[i + 1][1] - 1
            if i + 1 < len(level_defs_sorted)
            else min(n_rows, ignore_after_row)
        )
        end = min(end, ignore_after_row)
        ranges[label] = (start, end)
    return ranges


# ============================================================
# PARSE GRID -> ANCHORS (title blocks) & STAFF PEOPLE
# ============================================================
def parse_sheet():
    ranges = level_row_ranges()
    anchors_by_level = defaultdict(list)

    for label, _ in level_defs_sorted:
        if label == STAFF_LEVEL:
            continue
        start, end = ranges[label]
        for c in range(n_cols):
            title = None
            members = []
            for r1 in range(start, end + 1):
                val = cell(r1 - 1, c)
                if val == "" or is_number(val):
                    continue
                val = clean(val)
                if title is None:
                    title = val
                else:
                    members.append(val)
            if title:
                anchors_by_level[label].append(
                    {"col": c, "title": title, "members": members}
                )

    staff_start, staff_end = ranges[STAFF_LEVEL]
    staff_people = []
    for r1 in range(staff_start, staff_end + 1):
        for c in range(n_cols):
            val = cell(r1 - 1, c)
            if val == "" or is_number(val):
                continue
            val = clean(val)
            if val.upper().startswith("NOTE"):
                continue
            staff_people.append({"col": c, "name": val})

    return anchors_by_level, staff_people


anchors_by_level, staff_people = parse_sheet()

# ============================================================
# BUILD GRAPHVIZ TREE
# ============================================================
PALETTE = ["#1e3a8a", "#4338ca", "#7c3aed", "#0f766e", "#0891b2", "#334155"]


def build_org_graph():
    graph = graphviz.Digraph()
    graph.attr(rankdir="TB", bgcolor="transparent", nodesep="0.3", ranksep="0.55")
    graph.attr(
        "node", shape="box", style="rounded,filled", fontname="Helvetica",
        fontcolor="white", color="#334155",
    )
    graph.attr("edge", color="#475569", arrowsize="0.6")

    level_labels_ordered = [l for l, _ in level_defs_sorted]
    level_anchor_nodes: dict[str, list[tuple[int, str, str]]] = {}
    counter = 0

    def nearest_parent(idx: int, col: int):
        for prev_idx in range(idx - 1, -1, -1):
            prev_label = level_labels_ordered[prev_idx]
            candidates = level_anchor_nodes.get(prev_label)
            if candidates:
                return min(candidates, key=lambda p: abs(p[0] - col))
        return None

    for idx, label in enumerate(level_labels_ordered):
        color = PALETTE[min(idx, len(PALETTE) - 1)]

        if label == STAFF_LEVEL:
            for person in staff_people:
                node_id = f"n{counter}"
                counter += 1
                graph.node(node_id, person["name"], fillcolor=color, fontsize="9")
                parent = nearest_parent(idx, person["col"])
                if parent:
                    graph.edge(parent[1], node_id, style="dashed")
            continue

        anchors = anchors_by_level.get(label, [])
        this_level_nodes = []
        for a in anchors:
            label_text = a["title"]
            shown = a["members"][:max_members_shown]
            if shown:
                label_text += "\n" + ", ".join(shown)
                if len(a["members"]) > max_members_shown:
                    label_text += f" +{len(a['members']) - max_members_shown}"
            node_id = f"n{counter}"
            counter += 1
            graph.node(node_id, label_text, fillcolor=color, fontsize="10")
            this_level_nodes.append((a["col"], node_id, a["title"]))
            parent = nearest_parent(idx, a["col"])
            if parent:
                graph.edge(parent[1], node_id)
        level_anchor_nodes[label] = this_level_nodes

    return graph


# ============================================================
# LAYOUT — TABS
# ============================================================
tab_chart, tab_editor = st.tabs(["📊 Bagan Organisasi", "📝 Edit Data Sheets"])

with tab_chart:
    st.subheader(f"Struktur: {selected_sheet_name}")

    legend_html = "".join(
        f'<span class="legend-box" style="background-color:{PALETTE[min(i, len(PALETTE)-1)]}">{label}</span>'
        for i, (label, _) in enumerate(level_defs_sorted)
    )
    st.markdown(f"<div>{legend_html}</div>", unsafe_allow_html=True)
    st.write("")

    total_anchors = sum(len(v) for v in anchors_by_level.values())
    if total_anchors == 0 and not staff_people:
        st.warning(
            "Tidak ada data yang terbaca pada rentang baris ini. Cek kembali"
            " nomor baris di sidebar — kemungkinan tidak cocok dengan"
            " sheet aktual."
        )
    else:
        org_graph = build_org_graph()
        st.graphviz_chart(org_graph, use_container_width=True)

    with st.expander("ℹ️ Cara kerja & cara menyesuaikan"):
        st.markdown(
            "- Setiap **kolom** di sheet dianggap satu jalur/cabang.\n"
            "- Sel teks pertama yang ditemukan pada rentang baris suatu level"
            " dianggap **judul jabatan**; sel teks berikutnya di kolom yang"
            " sama dianggap **nama** pemegang jabatan tersebut.\n"
            "- Level terakhir (**Staff / Admin**) diperlakukan berbeda: semua"
            " sel terisi dianggap individu, lalu disambungkan ke kotak jabatan"
            " terdekat (berdasarkan posisi kolom) dari level di atasnya.\n"
            "- Jika bagan terlihat salah sambung, sesuaikan **nomor baris awal**"
            " tiap level di sidebar sampai cocok dengan sheet Anda."
        )

with tab_editor:
    st.subheader("📝 Edit Data Google Sheets")
    st.info(
        "Ini adalah tampilan mentah grid sheet (tanpa header). Perubahan pada"
        " tabel akan menimpa seluruh isi worksheet saat disimpan."
    )

    raw_df = pd.DataFrame(raw_values)
    edited_df = st.data_editor(
        raw_df, num_rows="dynamic", key=f"editor_{selected_sheet_name}"
    )

    if st.button("💾 Simpan Perubahan ke Google Sheets", type="primary"):
        try:
            worksheet.clear()
            set_with_dataframe(
                worksheet, edited_df, include_column_header=False
            )
            st.success("Berhasil memperbarui Google Sheets! 🎉")
            st.rerun()
        except Exception as e:
            st.error(f"Gagal menyimpan: {e}")
