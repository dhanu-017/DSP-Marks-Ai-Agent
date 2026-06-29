
# ============================================================
# DSP Marks AI Agent - Gemini Vision
# Upload MULTIPLE photos → Get ONE combined Excel.
# Works on BOTH local (.env) AND Streamlit Cloud (secrets)
# ============================================================

import streamlit as st
import pandas as pd
import numpy as np
import io
import json
import re
import os
import google.generativeai as genai
from PIL import Image
from datetime import datetime

# ============================================================
# API KEY - Works both locally and on Streamlit Cloud
# ============================================================
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    API_KEY = os.getenv("GEMINI_API_KEY")

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="DSP Marks AI Agent",
    page_icon="📝",
    layout="centered"
)

# ============================================================
# CORE FUNCTIONS
# ============================================================

def get_gemini_model():
    """Initialize Gemini Vision model."""
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")
    return model


def extract_marks_from_image(model, image: Image.Image) -> pd.DataFrame:
    """Send image to Gemini → Get structured marks data."""

    prompt = """Look at this marks sheet image carefully. Extract ALL student data from it.

Return ONLY a valid JSON array with this exact format (no other text):
[
  {"roll_no": "CS101", "name": "Student Name", "marks": {"Subject1": 18, "Subject2": 16, "Total": 34}},
  {"roll_no": "CS102", "name": "Another Student", "marks": {"Subject1": 20, "Subject2": 19, "Total": 39}}
]

Rules:
- Extract EVERY student row you can see
- Use the actual column headers from the sheet (like IA1, IA2, Q1, Q2, Maths, Physics, etc.)
- If there's a Total column, include it
- If you can't read a value clearly, use your best guess
- Roll numbers can be numeric (101) or alphanumeric (CS101)
- Return ONLY the JSON array, nothing else"""

    response = model.generate_content([prompt, image])

    # Parse JSON from response
    response_text = response.text.strip()

    # Clean markdown code blocks if present
    if response_text.startswith("```"):
        response_text = re.sub(r'^```[a-z]*\n?', '', response_text)
        response_text = re.sub(r'\n?```$', '', response_text)

    response_text = response_text.strip()
    students = json.loads(response_text)

    if not students:
        return pd.DataFrame()

    # Convert to DataFrame
    rows = []
    for student in students:
        row = {
            "Roll No": student.get("roll_no", ""),
            "Student Name": student.get("name", "")
        }
        marks = student.get("marks", {})
        for subject, mark in marks.items():
            row[subject] = mark
        rows.append(row)

    df = pd.DataFrame(rows)

    # Add Total if not present
    if "Total" not in df.columns:
        mark_cols = [c for c in df.columns if c not in ["Roll No", "Student Name"]]
        numeric_cols = df[mark_cols].select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            df["Total"] = df[numeric_cols].sum(axis=1)

    return df


# ============================================================
# STREAMLIT APP
# ============================================================

def main():
    st.title("📝 DSP Marks AI Agent")
    st.write("**Upload marks sheet photos → Download Excel**")
    st.caption("Powered by Google Gemini Vision • Supports multiple files")

    # Check if API key exists
    if not API_KEY:
        st.error("❌ API key not found!")
        st.info("**Local:** Add key in `.env` file\n\n**Streamlit Cloud:** Add key in Settings → Secrets")
        st.code('GEMINI_API_KEY = "your_key_here"', language="toml")
        st.stop()

    st.divider()

    # Multiple file upload
    uploaded_files = st.file_uploader(
        "📸 Upload marks sheets (one or multiple)",
        type=["jpg", "jpeg", "png", "bmp", "tiff"],
        accept_multiple_files=True,
        help="Upload one or more photos/scans of marks sheets"
    )

    if uploaded_files:
        # Show all uploaded images
        st.subheader(f"📎 {len(uploaded_files)} file(s) uploaded")
        cols = st.columns(min(len(uploaded_files), 3))
        for i, file in enumerate(uploaded_files):
            with cols[i % 3]:
                img = Image.open(file)
                st.image(img, caption=file.name, use_column_width=True)

        st.divider()

        if st.button("🚀 Extract All & Generate Excel", type="primary", use_container_width=True):

            all_dfs = []
            model = None

            progress = st.progress(0, text="Starting extraction...")

            for idx, file in enumerate(uploaded_files):
                progress.progress(
                    (idx) / len(uploaded_files),
                    text=f"🤖 Reading file {idx + 1}/{len(uploaded_files)}: {file.name}"
                )

                try:
                    if model is None:
                        model = get_gemini_model()

                    image = Image.open(file)
                    df = extract_marks_from_image(model, image)

                    if not df.empty:
                        #df["Source File"] = file.name
                        all_dfs.append(df)
                        st.success(f"✅ {file.name} → {len(df)} students extracted")
                    else:
                        st.warning(f"⚠️ {file.name} → No data found")

                except json.JSONDecodeError:
                    st.error(f"❌ {file.name} → Could not parse. Try a clearer photo.")
                except Exception as e:
                    st.error(f"❌ {file.name} → Error: {str(e)}")

            progress.progress(1.0, text="✅ All files processed!")

            # Combine all DataFrames
            if all_dfs:
                combined_df = pd.concat(all_dfs, ignore_index=True)

                st.divider()
                st.success(f"✅ Total: {len(combined_df)} students from {len(all_dfs)} file(s)")

                # Editable table
                st.subheader("📊 Review & Edit")
                edited_df = st.data_editor(combined_df, use_container_width=True, num_rows="dynamic")

                st.divider()

                # Generate Excel with multiple sheets
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                    # Combined sheet (all students)
                    edited_df.to_excel(writer, sheet_name="All_Marks", index=False)
                    ws = writer.sheets["All_Marks"]
                    for col in ws.columns:
                        max_len = max(len(str(cell.value or "")) for cell in col)
                        ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 25)

                    # Individual sheets per file
                    for i, df in enumerate(all_dfs):
                        sheet_name = f"Sheet_{i+1}"
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
                        ws = writer.sheets[sheet_name]
                        for col in ws.columns:
                            max_len = max(len(str(cell.value or "")) for cell in col)
                            ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 25)

                excel_buffer.seek(0)

                # Download
                st.download_button(
                    "📥 Download Excel (All Combined)",
                    data=excel_buffer,
                    file_name=f"marks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True
                )
            else:
                st.error("❌ No data extracted from any file. Try clearer photos.")


if __name__ == "__main__":
    main()
