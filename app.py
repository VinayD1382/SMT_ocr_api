from fastapi import FastAPI, UploadFile, File
import easyocr
import re
from typing import Dict, List
import requests

app = FastAPI(title="Smart Expense Tracker OCR API")

# Load EasyOCR model (CPU mode)
reader = easyocr.Reader(['en'], gpu=False)


def clean_amount(value):
    if value is None:
        return None

    value = value.replace("₹", "").replace(",", "").strip()
    value = re.sub(r"[^0-9]", "", value)

    if not value.isdigit():
        return None

    amount = int(value)

    if len(value) == 4:
        amount = int(value[1:])

    return amount


def extract_fields(text_list: List[str]) -> Dict:
    text = " ".join(text_list)

    merchant_keywords = [
        "Dominos", "Domino’s", "Dominos Pizza",
        "Manipal", "Pizza Hut", "CCD", "Haldiram"
    ]

    merchant = "Unknown"
    for line in text_list:
        for key in merchant_keywords:
            if key.lower() in line.lower():
                merchant = key
                break
        if merchant != "Unknown":
            break

    if merchant == "Unknown" and len(text_list) > 0:
        merchant = text_list[0]

    date_pattern = r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b"
    m = re.search(date_pattern, text)
    date_value = m.group(1) if m else "Unknown"

    total_value = None
    for i, line in enumerate(text_list):
        if "total" in line.lower():
            if i + 1 < len(text_list):
                total_value = clean_amount(text_list[i + 1])
            break

    if total_value is None:
        nums = re.findall(r"\d+", text)
        if nums:
            total_value = clean_amount(nums[-1])

    category = "Healthcare" if "hospital" in text.lower() else "General"

    return {
        "merchant": merchant,
        "date": date_value,
        "amount": total_value,
        "category": category
    }


@app.post("/ocr")
async def process_receipt(file: UploadFile = File(...)):
    contents = await file.read()
    temp_path = "temp_receipt.jpg"

    with open(temp_path, "wb") as f:
        f.write(contents)

    result = reader.readtext(temp_path, detail=0)

    fields = extract_fields(result)

    # ===== IMPORTANT CHANGE =====
    # HuggingFace cannot call localhost URL.
    NLP_API_URL = "https://your-nlp-api-url.com/categorize"

    try:
        nlp_response = requests.post(
            NLP_API_URL,
            json={
                "merchant": fields["merchant"],
                "description": " ".join(result),
                "amount": fields["amount"],
            },
            timeout=5
        )

        if nlp_response.status_code == 200:
            data = nlp_response.json()
            fields["category"] = data.get("category", "Unknown")
            fields["confidence"] = data.get("confidence", 0.0)
        else:
            fields["confidence"] = 0.0

    except Exception as e:
        print("❌ NLP Service Error:", e)
        fields["confidence"] = 0.0

    return {
        "success": True,
        "extracted_data": fields,
        "raw_text": result
    }
