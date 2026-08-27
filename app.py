import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Enterprise Org Chart - JDC Warehouse", layout="wide"
)

# Custom CSS untuk membuat kartu struktur organisasi yang modern & mewah
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
    .card-spv {
        background: linear-gradient(135deg, #0f766e 0%, #1e293b 100%);
        border-left: 6px solid #14b8a6;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 12px;
        box-shadow: 0 3px 10px rgba(0,0,0,0.3);
    }
    .card-staff {
        background-color: #1e293b;
        border-left: 4px solid #64748b;
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 8px;
        border: 1px solid #334155;
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
    .connector {
        text-align: center;
        color: #475569;
        font-size: 18px;
        margin: -5px 0 5px 0;
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


@st.cache_resource
def init_connection():
  cred_dict = dict(st.secrets["gcp_service_account"])
  return gspread.service_account_from_dict(cred_dict)


try:
  gc = init_connection()
  # Spreadsheet ID baru Anda
  spreadsheet_id = "1O04askVDfi_h48tqJ972ZHwQzejPir39rocA9STWivc"
  sh = gc.open_by_key(spreadsheet_id)
  worksheet_list = [ws.title for ws in sh.worksheets()]
except Exception as e:
  st.error(f"Gagal terhubung ke Google Sheets: {e}")
  st.stop()

# Pilihan Tab/Worksheet
selected_sheet_name = st.selectbox(
    "📌 Pilih Cabang / Worksheet Gudang:", worksheet_list
)
worksheet = sh.worksheet(selected_sheet_name)
data_df = get_as_dataframe(worksheet, evaluate_formulas=True)
data_df = data_df.dropna(how="all").dropna(axis=1, how="all")

# Layout Utama: 2 Kolom (Bagan Visual di Kiri, Editor Tabel di Kanan)
col_chart, col_editor = st.columns([1.4, 1])

with col_chart:
  st.subheader(f"📊 Bagan Struktur: {selected_sheet_name}")

  # 1. Level Pimpinan / Top Management (Simulasi Berjenjang)
  st.markdown(
      """
        <div class="card-top">
            <span class="badge-role" style="color: #60a5fa; background-color: rgba(59, 130, 246, 0.2);">Head Of Department</span>
            <div class="name-text" style="font-size: 18px;">Han Mintak / Edwin Indra Saputra</div>
        </div>
        <div class="connector">⬇</div>
    """,
      unsafe_allow_html=True,
  )

  # 2. Level Supervisor & Leader (Parsing dinamis dari data spreadsheet)
  st.markdown("##### 👥 Level Pengawas & Leader")
  spv_count = 0
  for _, row in data_df.iterrows():
    row_vals = [
        str(val).strip()
        for val in row.values
        if pd.notna(val)
        and str(val).strip() != ""
        and not str(val).startswith("Unnamed")
    ]
    # Filter baris yang terindikasi sebagai posisi supervisor/leader
    for val in row_vals:
      if any(
          keyword in val.lower()
          for keyword in [
              "supervisor",
              "spv",
              "leader",
              "manager",
              "asst",
              "firmansyah",
              "agus",
          ]
      ):
        spv_count += 1
        if spv_count <= 6:  # Batasi tampilan agar tetap rapi
          st.markdown(
              f"""
                <div class="card-spv">
                    <span class="badge-role" style="color: #2dd4bf; background-color: rgba(20, 184, 166, 0.2);">Supervisor / Leader</span>
                    <div class="name-text">{val}</div>
                </div>
                """,
              unsafe_allow_html=True,
          )

  # 3. Level Staff / Anggota Tim
  st.markdown("##### 📋 Daftar Staff & Anggota Terdaftar")
  staff_container = st.container(height=300)  # Scrollable container yang rapi
  with staff_container:
    for _, row in data_df.iterrows():
      row_vals = [
          str(val).strip()
          for val in row.values
          if pd.notna(val)
          and str(val).strip() != ""
          and not str(val).startswith("Unnamed")
      ]
      for val in row_vals:
        # Tampilkan item lain yang bertindak sebagai staff/anggota
        if not any(
            k in val.lower()
            for k in [
                "supervisor",
                "spv",
                "leader",
                "manager",
                "asst",
                "head",
                "han mintak",
            ]
        ):
          st.markdown(
              f"""
                <div class="card-staff">
                    <span style="color: #cbd5e1; font-size: 13px;">👤 {val}</span>
                </div>
                """,
              unsafe_allow_html=True,
          )

with col_editor:
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
