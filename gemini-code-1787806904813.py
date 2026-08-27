import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Aplikasi Struktur Organisasi Online", layout="wide"
)

st.title("🏢 Aplikasi Struktur Organisasi & Manajemen Gudang")


@st.cache_resource
def init_connection():
  # Membaca kredensial aman langsung dari fitur Secrets Streamlit Cloud
  cred_dict = dict(st.secrets["gcp_service_account"])
  return gspread.service_account_from_dict(cred_dict)


try:
  gc = init_connection()
  spreadsheet_id = "1WSsinlygfTsSyokgfNYu_FX2BhZ0lJubrhttvXQcsdU"
  sh = gc.open_by_key(spreadsheet_id)
  worksheet_list = [ws.title for ws in sh.worksheets()]
except Exception as e:
  st.error(
      f"Gagal terhubung ke Google Sheets. Pastikan konfigurasi Secrets sudah"
      f" benar. Error: {e}"
  )
  st.stop()

# Pilihan Worksheet
selected_sheet_name = st.selectbox(
    "📌 Pilih Worksheet / Cabang Gudang:", worksheet_list
)
worksheet = sh.worksheet(selected_sheet_name)
data_df = get_as_dataframe(worksheet, evaluate_formulas=True)
data_df = data_df.dropna(how="all").dropna(axis=1, how="all")

col1, col2 = st.columns([1.2, 1])

with col1:
  st.subheader(f"📝 Edit Data: {selected_sheet_name}")
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

with col2:
  st.subheader(f"📊 Pratinjau Data: {selected_sheet_name}")
  st.dataframe(edited_df, use_container_width=True)