
# ============================================================
# DSP Marks AI Agent - Gemini Vision
# Upload MULTIPLE photos/PDFs → Get ONE combined Excel.
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


def pdf_to_images(pdf_file) -> list:
    """Convert a PDF file to a list of PIL Images (one per page)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        st.error("❌ PyMuPDF not installed. Run: `pip install pymupdf`")
        return []

    images = []
    pdf_bytes = pdf_file.read()
    pdf_file.seek(0)  # Reset file pointer

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        # Render at 2x resolution for better OCR accuracy
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    doc.close()

    return images


def extract_marks_from_image(model, image: Image.Image) -> pd.DataFrame:
    """Send image to Gemini → Get structured marks data with EXACT column names from source."""

    prompt = """Look at this marks sheet image carefully. Extract ALL student data from it.

Return ONLY a valid JSON object with this exact format (no other text):
{
  "columns": ["exact_col1_name", "exact_col2_name", "exact_col3_name", ...],
  "students": [
    {"values": ["value1", "value2", 18, 16, ...]},
    {"values": ["value3", "value4", 20, 19, ...]}
  ]
}

Rules:
- The "columns" array MUST contain the EXACT column header names as written in the image (e.g., "Register No", "Name", "1.a", "1.b", "Total" — whatever is actually written)
- Do NOT rename or standardize column names. Use them EXACTLY as they appear in the image.
- If there's a heading like "Marks for Individual Questions" spanning multiple columns, ignore it — only use the actual sub-column headers.
- Extract EVERY student row you can see
- If you can't read a value clearly, use your best guess
- Numeric marks should be integers, text values should be strings
- Return ONLY the JSON object, nothing else"""

    response = model.generate_content([prompt, image])

    # Parse JSON from response
    response_text = response.text.strip()

    # Clean markdown code blocks if present
    if response_text.startswith("```"):
        response_text = re.sub(r'^```[a-z]*\n?', '', response_text)
        response_text = re.sub(r'\n?```$', '', response_text)

    response_text = response_text.strip()
    data = json.loads(response_text)

    if not data or not data.get("students"):
        return pd.DataFrame()

    # Build DataFrame using exact column names from the image
    columns = data["columns"]
    rows = [student["values"] for student in data["students"]]

    df = pd.DataFrame(rows, columns=columns)

    # Convert numeric columns to numbers where possible
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass

    # Add Total if not already present
    if "Total" not in df.columns and "total" not in [c.lower() for c in df.columns]:
        # Identify numeric mark columns (skip first two which are usually ID and Name)
        mark_cols = df.columns[2:]
        numeric_cols = df[mark_cols].select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            df["Total"] = df[numeric_cols].sum(axis=1)

    return df


# ============================================================
# STREAMLIT APP
# ============================================================

def main():
    st.title("📝 DSP Marks AI Agent")
    st.write("**Upload marks sheet photos or PDFs → Download Excel**")
    st.caption("Powered by Google Gemini Vision • Supports images & PDFs • Multiple files")

    # Check if API key exists
    if not API_KEY:
        st.error("❌ API key not found!")
        st.info("**Local:** Add key in `.env` file\n\n**Streamlit Cloud:** Add key in Settings → Secrets")
        st.code('GEMINI_API_KEY = "your_key_here"', language="toml")
        st.stop()

    st.divider()

    # Multiple file upload - now includes PDF
    uploaded_files = st.file_uploader(
        "📸 Upload marks sheets (images or PDFs)",
        type=["jpg", "jpeg", "png", "bmp", "tiff", "pdf"],
        accept_multiple_files=True,
        help="Upload one or more photos, scans, or PDF files of marks sheets"
    )

    if uploaded_files:
        # Show all uploaded files
        st.subheader(f"📎 {len(uploaded_files)} file(s) uploaded")

        # Separate images and PDFs for preview
        image_files = [f for f in uploaded_files if not f.name.lower().endswith('.pdf')]
        pdf_files = [f for f in uploaded_files if f.name.lower().endswith('.pdf')]

        # Preview images
        if image_files:
            cols = st.columns(min(len(image_files), 3))
            for i, file in enumerate(image_files):
                with cols[i % 3]:
                    img = Image.open(file)
                    st.image(img, caption=file.name, use_column_width=True)

        # Preview PDFs
        if pdf_files:
            for file in pdf_files:
                st.info(f"📄 **{file.name}** (PDF - will process all pages)")

        st.divider()

        if st.button("🚀 Extract All & Generate Excel", type="primary", use_container_width=True):

            all_dfs = []
            model = None

            # Build a list of (image, source_name) tuples to process
            images_to_process = []

            # Collect images from image files
            for file in image_files:
                img = Image.open(file)
                images_to_process.append((img, file.name))

            # Collect images from PDF files
            for file in pdf_files:
                pdf_images = pdf_to_images(file)
                if pdf_images:
                    for page_num, img in enumerate(pdf_images, 1):
                        source_name = f"{file.name} (Page {page_num})"
                        images_to_process.append((img, source_name))
                else:
                    st.warning(f"⚠️ {file.name} → Could not convert PDF to images")

            if not images_to_process:
                st.error("❌ No processable images found.")
                return

            total = len(images_to_process)
            progress = st.progress(0, text="Starting extraction...")

            for idx, (image, source_name) in enumerate(images_to_process):
                progress.progress(
                    idx / total,
                    text=f"🤖 Reading {idx + 1}/{total}: {source_name}"
                )

                try:
                    if model is None:
                        model = get_gemini_model()

                    df = extract_marks_from_image(model, image)

                    if not df.empty:
                        all_dfs.append(df)
                        st.success(f"✅ {source_name} → {len(df)} students extracted")
                    else:
                        st.warning(f"⚠️ {source_name} → No data found")

                except json.JSONDecodeError:
                    st.error(f"❌ {source_name} → Could not parse. Try a clearer image.")
                except Exception as e:
                    st.error(f"❌ {source_name} → Error: {str(e)}")

            progress.progress(1.0, text="✅ All files processed!")

            # Combine all DataFrames
            if all_dfs:
                combined_df = pd.concat(all_dfs, ignore_index=True)

                st.divider()
                st.success(f"✅ Total: {len(combined_df)} students from {len(all_dfs)} source(s)")

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

                    # Individual sheets per source
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

