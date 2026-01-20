from flask import Flask, render_template, request, url_for, send_file
import os
import shutil
import pytesseract
import fitz             # PyMuPDF
import cv2
import numpy as np
from docx import Document
from PIL import Image, ImageDraw
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = Flask(__name__)

# Set upload folder
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Cache for PDF report
report_cache = []

# Tesseract path - *** UPDATE THIS TO YOUR PATH ***
pytesseract.pytesseract.tesseract_cmd = r"D:\Downloads\tesseract\tesseract.exe"

# ----------------------------------------------------
# Helper: Automatic Cleanup
# ----------------------------------------------------
def clear_old_files():
    """Deletes all files in the upload folder to keep storage clean."""
    for filename in os.listdir(app.config["UPLOAD_FOLDER"]):
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        try:
            if os.path.isfile(file_path) or os.path.is_link(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Cleanup error: {e}")

# ----------------------------------------------------
# Main Route
# ----------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    global report_cache
    results = []

    if request.method == "POST":
        # DELETE old photos as soon as a new upload starts
        clear_old_files()
        report_cache = [] 

        files = request.files.getlist("files[]")

        for file in files:
            if not file or file.filename == '':
                continue

            filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(filepath)

            ext = os.path.splitext(file.filename)[1].lower()
            preview_url = None
            text = ""
            page_count = 1

            # --- Process File Types ---
            if ext in [".png", ".jpg", ".jpeg"]:
                text = ocr_image(filepath)
                preview_url = url_for("static", filename=f"uploads/{file.filename}")
                page_count = 1

            elif ext == ".pdf":
                text, page_count = ocr_pdf(filepath)
                preview_path = pdf_preview(filepath)
                preview_url = url_for("static", filename=f"uploads/{os.path.basename(preview_path)}")

            elif ext == ".docx":
                text = ocr_docx(filepath)
                preview_path = docx_preview(filepath)
                preview_url = url_for("static", filename=f"uploads/{os.path.basename(preview_path)}")
                page_count = 1
            else:
                results.append({
                    "filename": file.filename,
                    "classification": "Unsupported",
                    "text": "Unsupported file type",
                    "img_url": None
                })
                report_cache.append((file.filename, "Unsupported"))
                continue

            # Perform Classification
            classification = classify(text, page_count)

            # Append to results
            results.append({
                "filename": file.filename,
                "classification": classification,
                "text": text,
                "img_url": preview_url
            })

            # Add to report summary
            report_cache.append((file.filename, classification))

    return render_template("index.html", results=results)

# ----------------------------------------------------
# OCR Functions
# ----------------------------------------------------
def ocr_image(path):
    img = cv2.imread(path)
    if img is None: return ""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    return pytesseract.image_to_string(gray)

def ocr_pdf(path):
    text = ""
    doc = fitz.open(path)
    page_count = len(doc)
    for page in doc:
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text += pytesseract.image_to_string(img) + "\n"
    return text, page_count

def ocr_docx(path):
    try:
        doc = Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    except:
        return ""

def pdf_preview(path):
    doc = fitz.open(path)
    page = doc.load_page(0)
    pix = page.get_pixmap()
    preview_path = os.path.join(app.config["UPLOAD_FOLDER"], "preview_" + os.path.basename(path) + ".png")
    pix.save(preview_path)
    return preview_path

def docx_preview(path):
    text = ocr_docx(path)[:600]
    img = Image.new("RGB", (900, 600), "white")
    drawer = ImageDraw.Draw(img)
    drawer.text((20, 20), text, fill="black")
    preview_path = os.path.join(app.config["UPLOAD_FOLDER"], "preview_" + os.path.basename(path) + ".png")
    img.save(preview_path)
    return preview_path

# ----------------------------------------------------
# Classification Logic
# ----------------------------------------------------
def classify(text, page_count=1):
    t = text.lower().strip()

    # 0. Pure image check
    if t == "" or len(t) < 10:
        return "Image"

    # 1. Report Detection
    if page_count > 1:
        return "Report"

    report_keywords = [
        "introduction", "aim", "objective", "experiment", "observation",
        "result", "discussion", "conclusion", "abstract", "reference",
        "faculty", "submitted", "certificate", "types", "theory",
        "methodology", "analysis"
    ]
    if any(w in t for w in report_keywords):
        return "Report"

    # 2. ID Card Detection (Generic & Govt)
    generic_id_words = [
        "id", "dob", "email", "phone", "join", "expire",
        "designation", "department", "employee", "student",
        "roll no", "contact", "graphic designer", "valid"
    ]
    id_count = sum(1 for w in generic_id_words if w in t)
    
    # Check regex for Govt IDs
    is_aadhar = re.search(r"\b\d{4}\s\d{4}\s\d{4}\b", t)
    is_pan = re.search(r"[A-Z]{5}[0-9]{4}[A-Z]", text.upper()) # Check original case for PAN
    is_passport = re.search(r"\b[A-Z][0-9]{7}\b", text.upper())

    if id_count >= 3 or is_aadhar or is_pan or is_passport:
        return "ID Card"

    # 3. Receipt / Bill Detection
    receipt_words = ["bill", "invoice", "total", "tax", "amount", "payment", "price", "qty"]
    if any(w in t for w in receipt_words):
        return "Receipt"

    return "Others"

# ----------------------------------------------------
# Report Download
# ----------------------------------------------------
@app.route("/download_report")
def download_report():
    if not report_cache:
        return "No report available.", 400

    pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], "document_report.pdf")
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, "Document Classification Report")
    
    y = 710
    c.setFont("Helvetica", 12)
    for filename, classification in report_cache:
        c.drawString(50, y, f"File: {filename}")
        c.drawString(50, y - 18, f"Classification: {classification}")
        y -= 50
        if y < 100:
            c.showPage()
            y = 750

    c.save()
    return send_file(pdf_path, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)