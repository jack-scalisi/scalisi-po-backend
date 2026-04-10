import os
import math
import json
import base64
from datetime import date
 
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import requests
 
app = Flask(__name__)
CORS(app)
 
VENDORS = {
    "kss": {"name": "KSS", "email": "kennettspec.sales2@gmail.com"},
    "basciani": {"name": "Basciani", "email": None},
}
 
 
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})
 
 
@app.route("/generate-po", methods=["POST"])
def generate_po():
    try:
        vendor_id = request.form.get("vendor")
        pdf_file = request.files.get("pdf")
 
        if not vendor_id or vendor_id not in VENDORS:
            return jsonify({"error": "Invalid vendor"}), 400
        if not pdf_file:
            return jsonify({"error": "No PDF uploaded"}), 400
 
        vendor = VENDORS[vendor_id]
        if not vendor["email"]:
            return jsonify({"error": f"{vendor['name']} is not configured yet"}), 400
 
        pdf_bytes = pdf_file.read()
        pdf_base64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
 
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
 
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "From this buy guide PDF, extract ONLY the rightmost Avail column "
                            "(the second Avail, forecasted through the end date). "
                            "Return ONLY a JSON array, no other text, no markdown. "
                            'Format: [{"item": "201645", "desc": "Mushrooms Button 10lb", "unit": "CASE", "avail": -10.7}]. '
                            "Exclude these item numbers entirely: 201715, 201646, 201765, 201766, 201841. "
                            "Include all other items."
                        )
                    }
                ]
            }]
        )
 
        raw = response.content[0].text.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        items = json.loads(clean)
 
        short_items = [it for it in items if it["avail"] < 0]
 
        if not short_items:
            return jsonify({"message": "No short items — no PO needed today!", "items": [], "total": 0})
 
        for it in short_items:
            it["order_qty"] = math.ceil(-it["avail"] + 4)
 
        total_cases = sum(it["order_qty"] for it in short_items)
        po_date = date.today().strftime("%m/%d/%Y")
 
        table_rows = "".join([
            f'<tr>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #eee;">{it["item"]}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #eee;">{it["desc"]}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center;">{it["unit"]}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center;font-weight:bold;">{it["order_qty"]}</td>'
            f'</tr>'
            for it in short_items
        ])
 
        email_html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
          <div style="background:#1F4E79;color:white;padding:20px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;font-size:18px;">Purchase Order — {vendor['name']}</h2>
            <p style="margin:6px 0 0;font-size:13px;opacity:0.85;">Scalisi Produce | {po_date}</p>
          </div>
          <div style="padding:20px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
              <thead>
                <tr style="background:#f5f5f5;">
                  <th style="padding:8px 12px;text-align:left;">Item #</th>
                  <th style="padding:8px 12px;text-align:left;">Description</th>
                  <th style="padding:8px 12px;text-align:center;">Unit</th>
                  <th style="padding:8px 12px;text-align:center;">Order Qty</th>
                </tr>
              </thead>
              <tbody>{table_rows}</tbody>
              <tfoot>
                <tr style="background:#E2EFDA;">
                  <td colspan="3" style="padding:10px 12px;font-weight:bold;">Total Cases</td>
                  <td style="padding:10px 12px;text-align:center;font-weight:bold;">{total_cases}</td>
                </tr>
              </tfoot>
            </table>
            <p style="font-size:12px;color:#888;margin-top:16px;">
              Generated automatically by Scalisi Produce PO System
            </p>
          </div>
        </div>
        """
 
        sg_response = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {os.environ.get('SENDGRID_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "personalizations": [{
                    "to": [{"email": vendor["email"]}],
                    "cc": [{"email": "jacks@scalisiproduce.com"}]
                }],
                "from": {"email": "jacks@scalisiproduce.com", "name": "Scalisi Produce"},
                "subject": f"Purchase Order — {vendor['name']} | {po_date}",
                "content": [{"type": "text/html", "value": email_html}]
            }
        )
 
        if sg_response.status_code == 202:
            return jsonify({
                "message": f"PO sent to {vendor['email']}!",
                "items": short_items,
                "total": total_cases
            })
        else:
            return jsonify({"error": f"SendGrid error: {sg_response.text}"}), 500
 
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
 
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
