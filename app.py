import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import streamlit as st
import graphviz

st.set_page_config(
    page_title="Enterprise Org Chart - JDC Warehouse", layout="wide"
)

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


def build_org_graph(df: pd.DataFrame) -> graphviz.Digraph:
    graph = graphviz.Digraph()
    graph.attr(rankdir="TB", bgcolor="transparent", nodesep="0.3", ranksep="0.55")
    graph.attr(
        "node", shape="box", style="rounded,filled", fontname="Helvetica",
        fontcolor="white", color="#1e293b",
    )
    graph.attr("edge", color="#475569", arrowsize="0.6")

    names_seen = set()
    for _, row in df.iterrows():
        name = row["Nama"]
        if not name or name in names_seen:
            continue
        names_seen.add(name)
        label = f"{name}\n{row['Jabatan']}" if row["Jabatan"] else name
        graph.node(name, label, fillcolor=color_for(row["Level"]), fontsize="10")

    for _, row in df.iterrows():
        child = row["Nama"]
        parent = row["Atasan"]
        if not child:
            continue
        if parent and parent in names_seen:
            graph.edge(parent, child)

    return graph


# ============================================================
# LAYOUT — TABS
# ============================================================
tab_chart, tab_editor = st.tabs(["📊 Bagan Organisasi", "📝 Edit Data Sheets"])

with tab_chart:
    st.subheader(f"Struktur: {selected_sheet_name}")

    levels_present = [l for l in data_df["Level"].unique() if l]
    if levels_present:
        legend_html = "".join(
            f'<span class="legend-box" style="background-color:{color_for(l)}">{l}</span>'
            for l in levels_present
        )
        st.markdown(f"<div>{legend_html}</div>", unsafe_allow_html=True)
        st.write("")

    orphans = data_df[
        (data_df["Atasan"] != "") & (~data_df["Atasan"].isin(data_df["Nama"]))
    ]
    if not orphans.empty:
        st.warning(
            "Beberapa baris punya nilai 'Atasan' yang tidak cocok dengan nama"
            " manapun di kolom 'Nama' (kemungkinan typo): "
            + ", ".join(orphans["Atasan"].unique())
        )

    org_graph = build_org_graph(data_df)
    st.graphviz_chart(org_graph, use_container_width=True)

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
