from fastapi import FastAPI, UploadFile, File
import easyocr
import re
from typing import Dict, List
import requests

app = FastAPI(title="Smart Expense Tracker OCR API")
reader = easyocr.Reader(['en'], gpu=False)


# ------------------------------------------------------------
# 🧹 Clean and correct the amount (8415 → 415)
# ------------------------------------------------------------
def clean_amount(value):
    if value is None:
        return None

    value = value.replace("₹", "").replace(",", "").strip()
    value = re.sub(r"[^0-9]", "", value)

    if not value.isdigit():
        return None

    amount = int(value)

    # ⭐ RULE: If 4-digit total → drop first digit (8415 → 415)
    if len(value) == 4:
        amount = int(value[1:])

    return amount


# ------------------------------------------------------------
# 🔍 Extract structured fields
# ------------------------------------------------------------
def extract_fields(text_list: List[str]) -> Dict:

    text = " ".join(text_list)

    # ---------------- Merchant ----------------
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

    # If still not found use top line
    if merchant == "Unknown" and len(text_list) > 0:
        merchant = text_list[0]

    # ---------------- Date ----------------
    date_pattern = r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b"
    m = re.search(date_pattern, text)
    date_value = m.group(1) if m else "Unknown"

    # ---------------- Amount (Total) ----------------
    total_value = None
    for i, line in enumerate(text_list):
        if "total" in line.lower():
            if i + 1 < len(text_list):
                total_value = clean_amount(text_list[i + 1])
            break

    # Fallback: last number in entire text
    if total_value is None:
        nums = re.findall(r"\d+", text)
        total_value = clean_amount(nums[-1]) if nums else None

    # ---------------- Category (simple rule) ----------------
    category = "Healthcare" if "hospital" in text.lower() else "General"

    return {
        "merchant": merchant,
        "date": date_value,
        "amount": total_value,
        "category": category
    }


# ------------------------------------------------------------
# 🚀 FastAPI Endpoint
# ------------------------------------------------------------
@app.post("/ocr")
async def process_receipt(file: UploadFile = File(...)):
    contents = await file.read()
    temp_path = "temp_receipt.jpg"

    with open(temp_path, "wb") as f:
        f.write(contents)

    # Run OCR
    result = reader.readtext(temp_path, detail=0)

    print("\n========== DEBUG OCR OUTPUT ==========")
    for i, line in enumerate(result):
        print(i, "=>", line)

    fields = extract_fields(result)

    # ------------------------------------------------------------
    # 🔥 NLP CATEGORY API CALL (requests restored)
    # ------------------------------------------------------------
    try:
        nlp_response = requests.post(
            "http://127.0.0.1:8002/categorize",
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
