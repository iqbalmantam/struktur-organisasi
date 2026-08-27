import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
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
    .card-top {
        background: linear-gradient(135deg, #1e3a8a 0%, #1e293b 100%);
        border-left: 6px solid #3b82f6;
        border-radius: 10px;
        padding: 18px;
        margin-bottom: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.4);
        text-align: center;
    }
    .badge-role {
        font-size: 10px;
        font-weight: bold;
        text-transform: uppercase;
        padding: 3px 8px;
        border-radius: 12px;
        background-color: rgba(255, 255, 255, 0.1);
        color: #94a3b8;
        letter-spacing: 0.5px;
    }
    .name-text {
        font-size: 15px;
        font-weight: bold;
        color: #f8fafc;
        margin-top: 6px;
    }
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
    "Visualisasi struktur organisasi hierarkis yang rapi dan terhubung"
    " langsung dengan Google Sheets Anda."
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

selected_sheet_name = st.selectbox(
    "📌 Pilih Cabang / Worksheet Gudang:", worksheet_list
)
worksheet = sh.worksheet(selected_sheet_name)
data_df = get_as_dataframe(worksheet, evaluate_formulas=True)
data_df = data_df.dropna(how="all").dropna(axis=1, how="all")

# ============================================================
# ROLE CLASSIFICATION
# ============================================================
HEAD_LABEL = "Head Of Department"
HEAD_NAME = "Han Mintak / Edwin Indra Saputra"

ROLE_KEYWORDS = {
    "manager": ["manager", "manajer"],
    "supervisor": ["supervisor", "spv", "leader", "asst", "asisten", "firmansyah", "agus"],
}

ROLE_COLORS = {
    "head": "#1e3a8a",
    "manager": "#7c3aed",
    "supervisor": "#0f766e",
    "staff": "#1e293b",
}


def classify_role(text: str) -> str:
    t = text.lower()
    for role, kws in ROLE_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return role
    return "staff"


def clean_row_values(row) -> list[str]:
    return [
        str(val).strip()
        for val in row.values
        if pd.notna(val)
        and str(val).strip() != ""
        and not str(val).startswith("Unnamed")
    ]


# ============================================================
# SIDEBAR — TAMPILAN
# ============================================================
with st.sidebar:
    st.header("⚙️ Pengaturan Tampilan")
    max_staff_shown = st.slider(
        "Batas staff ditampilkan per cabang", min_value=5, max_value=100, value=30
    )
    show_unassigned_head = st.checkbox(
        "Tampilkan baris tanpa supervisor sebagai staf umum di bawah Head",
        value=True,
    )
    st.caption(
        "Bagan dibangun otomatis dari struktur baris di sheet: nama dengan kata"
        " kunci jabatan (Supervisor/Leader/Manager) menjadi cabang dari Head,"
        " dan nama lain pada baris yang sama menjadi anak dari nama tersebut."
    )

# ============================================================
# BUILD ORG TREE (graphviz)
# ============================================================
def build_org_graph(df: pd.DataFrame) -> graphviz.Digraph:
    graph = graphviz.Digraph()
    graph.attr(rankdir="TB", bgcolor="transparent", nodesep="0.35", ranksep="0.6")
    graph.attr(
        "node",
        shape="box",
        style="rounded,filled",
        fontname="Helvetica",
        fontcolor="white",
        color="#334155",
    )
    graph.attr("edge", color="#475569", arrowsize="0.6")

    graph.node(
        "HEAD",
        f"{HEAD_LABEL}\n{HEAD_NAME}",
        fillcolor=ROLE_COLORS["head"],
        fontsize="13",
        penwidth="2",
    )

    supervisor_nodes: dict[str, str] = {}
    supervisor_counter = 0
    staff_counter = 0
    branch_staff_count: dict[str, int] = {}

    for _, row in df.iterrows():
        row_vals = clean_row_values(row)
        if not row_vals:
            continue

        row_supervisors = [v for v in row_vals if classify_role(v) in ("supervisor", "manager")]
        row_staff = [v for v in row_vals if classify_role(v) == "staff"]

        if row_supervisors:
            for sup in row_supervisors:
                if sup not in supervisor_nodes:
                    node_id = f"spv_{supervisor_counter}"
                    supervisor_counter += 1
                    supervisor_nodes[sup] = node_id
                    role = classify_role(sup)
                    graph.node(node_id, sup, fillcolor=ROLE_COLORS[role], fontsize="11")
                    graph.edge("HEAD", node_id)

            anchor_name = row_supervisors[0]
            anchor_id = supervisor_nodes[anchor_name]
            branch_staff_count.setdefault(anchor_id, 0)

            for name in row_staff:
                if branch_staff_count[anchor_id] >= max_staff_shown:
                    continue
                node_id = f"staff_{staff_counter}"
                staff_counter += 1
                branch_staff_count[anchor_id] += 1
                graph.node(
                    node_id, name, fillcolor=ROLE_COLORS["staff"], fontsize="9", fontcolor="#cbd5e1"
                )
                graph.edge(anchor_id, node_id, style="dashed", color="#64748b")

        elif show_unassigned_head:
            for name in row_staff:
                node_id = f"staff_{staff_counter}"
                staff_counter += 1
                graph.node(
                    node_id, name, fillcolor=ROLE_COLORS["staff"], fontsize="9", fontcolor="#cbd5e1"
                )
                graph.edge("HEAD", node_id, style="dotted", color="#94a3b8")

    return graph


# ============================================================
# LAYOUT — TABS
# ============================================================
tab_chart, tab_editor = st.tabs(["📊 Bagan Organisasi", "📝 Edit Data Sheets"])

with tab_chart:
    st.subheader(f"Struktur: {selected_sheet_name}")

    st.markdown(
        f"""
        <div>
            <span class="legend-box" style="background-color:{ROLE_COLORS['head']}">Head</span>
            <span class="legend-box" style="background-color:{ROLE_COLORS['manager']}">Manager</span>
            <span class="legend-box" style="background-color:{ROLE_COLORS['supervisor']}">Supervisor / Leader</span>
            <span class="legend-box" style="background-color:{ROLE_COLORS['staff']}">Staff</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")

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
