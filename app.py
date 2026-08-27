import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Professional Org Chart - Google Sheets", layout="wide"
)

st.title("🏢 Interactive Organizational Chart & Management")
st.write(
    "Aplikasi ini terhubung langsung ke Google Sheet baru Anda dan menampilkan"
    " diagram struktur organisasi visual secara otomatis."
)


@st.cache_resource
def init_connection():
  cred_dict = dict(st.secrets["gcp_service_account"])
  return gspread.service_account_from_dict(cred_dict)


try:
  gc = init_connection()
  # Menggunakan Spreadsheet ID baru dari link Anda
  spreadsheet_id = "1O04askVDfi_h48tqJ972ZHwQzejPir39rocA9STWivc"
  sh = gc.open_by_key(spreadsheet_id)
  worksheet_list = [ws.title for ws in sh.worksheets()]
except Exception as e:
  st.error(f"Gagal terhubung ke Google Sheets: {e}")
  st.stop()

# Pilih Worksheet / Tab
selected_sheet_name = st.selectbox(
    "📌 Pilih Worksheet / Cabang Gudang:", worksheet_list
)
worksheet = sh.worksheet(selected_sheet_name)
data_df = get_as_dataframe(worksheet, evaluate_formulas=True)
data_df = data_df.dropna(how="all").dropna(axis=1, how="all")

# Layout 2 Kolom: Visual Diagram (Kiri) & Data Editor (Kanan)
col_chart, col_editor = st.columns([1.3, 1])

with col_chart:
  st.subheader(f"📊 Bagan Struktur Organisasi: {selected_sheet_name}")

  # Membangun Diagram Hierarki Profesional menggunakan Graphviz
  graph_code = "digraph OrgChart {\n"
  graph_code += '  node [shape=box, style="filled,rounded", fillcolor="#1e293b", fontcolor="#ffffff", fontname="Arial", margin=0.3];\n'
  graph_code += '  edge [color="#64748b", penwidth=1.5];\n'
  graph_code += "  rankdir=TB;\n"

  # Ekstraksi baris data untuk membentuk node grafik secara dinamis
  valid_rows = []
  for _, row in data_df.iterrows():
    row_vals = [
        str(val).strip()
        for val in row.values
        if pd.notna(val)
        and str(val).strip() != ""
        and not str(val).startswith("Unnamed")
    ]
    if len(row_vals) > 0:
      valid_rows.append(row_vals)

  # Menyusun relasi hierarki antar node secara otomatis dari data sheet
  if len(valid_rows) >= 2:
    parent_node = valid_rows[0][0]
    for r in valid_rows[1:12]:
      child_node = r[0]
      if parent_node != child_node:
        graph_code += f'  "{parent_node}" -> "{child_node}";\n'
        parent_node = child_node
  else:
    graph_code += (
        '  "Head Department" -> "Manager" -> "Supervisor" -> "Staff";\n'
    )

  graph_code += "}"

  # Render diagram grafis di Streamlit
  st.graphviz_chart(graph_code, use_container_width=True)
  st.info(
      "💡 Diagram di atas diperbarui secara otomatis berdasarkan data dalam"
      " sheet."
  )

with col_editor:
  st.subheader(f"📝 Edit Data Google Sheets")

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
