from flask import Flask, render_template, request
import os
import pytesseract
import fitz  # PyMuPDF
import cv2
import numpy as np

app = Flask(__name__)
pytesseract.pytesseract.tesseract_cmd = r"D:\Downloads\tesseract\tesseract.exe"  # update path if needed

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    if request.method == "POST":
        files = request.files.getlist("files[]") # multiple files support
        for file in files:
            if file:
                filepath = os.path.join(UPLOAD_FOLDER, file.filename)
                file.save(filepath)

                # OCR based on file type
                if filepath.lower().endswith((".png", ".jpg", ".jpeg")):
                    text = ocr_image(filepath)
                elif filepath.lower().endswith(".pdf"):
                    text = ocr_pdf(filepath)
                else:
                    text = "❌ Unsupported file type"

                classification = classify_text(text)
                results.append({
                    "filename": file.filename,
                    "classification": classification,
                    "text": text
                })

    return render_template("index.html", results=results)


def ocr_image(path):
    img = cv2.imread(path)
    if img is None:
        return "❌ Could not read image"
    text = pytesseract.image_to_string(img)
    return text


def ocr_pdf(path):
    text = ""
    doc = fitz.open(path)
    for page in doc:
        pix = page.get_pixmap()
        img = cv2.imdecode(
            np.frombuffer(pix.tobytes(), np.uint8), cv2.IMREAD_COLOR
        )
        text += pytesseract.image_to_string(img)
    return text


def classify_text(text):
    text_lower = text.lower()
    if any(word in text_lower for word in ["id", "passport", "aadhar"]):
        return "🪪 ID Proof"
    elif any(word in text_lower for word in ["invoice", "payment", "amount", "bill"]):
        return "🧾 Bill / Invoice"
    else:
        return "📂 Other Document"


if __name__ == "__main__":
    app.run(debug=True)
