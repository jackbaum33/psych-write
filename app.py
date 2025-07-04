# app.py
from flask import Flask, render_template, request, send_file
from docx import Document
import tempfile, os, platform, subprocess
from openai import OpenAI
from docx2pdf import convert
import json

client = OpenAI()

app = Flask(__name__)

SECTIONS = {
    "referral": "Reason for Referral",
    "family_details": "Family Details",
    "birth_history": "Birth/Developmental History",
    "school_history": "School History",
    "previous_evals": "Previous Evaluations",
    "observations": "Behavioral Observations",
    "recommendations": "Recommendations"
}

def create_batched_prompt(sections, appendix):
    entries = []
    for section in sections:
        entries.append({
            "heading": section["heading"],
            "bullets": section["bullets"]
        })
    return (
        f"Generate a JSON object where each key is the heading of a neuropsychological report section and the value is a paragraph based on the given bullet points and appendix.\n"
        f"Only return JSON.\n\n"
        f"Data: {json.dumps({'sections': entries, 'appendix': appendix})}"
    )

def create_test_prompt(test_sections, appendix):
    entries = []
    for test in test_sections:
        entries.append({
            "test_name": test["test_name"],
            "bullets": test["bullets"]
        })
    return (
        f"Generate a JSON object where each key is the test name and the value is a paragraph interpreting the bullet points and appendix.\n"
        f"Only return JSON.\n\n"
        f"Data: {json.dumps({'tests': entries, 'appendix': appendix})}"
    )

@app.route("/")
def index():
    return render_template("form.html", sections=SECTIONS)

@app.route("/generate", methods=["POST"])
def generate():
    data = request.form
    doc = Document("doc_templates/report_template.docx")

    # Basic fields
    for field in ["name", "dob", "age", "grade", "school", "eval_dates"]:
        placeholder = f"{{{{{field}}}}}"
        for paragraph in doc.paragraphs:
            if placeholder in paragraph.text:
                paragraph.text = paragraph.text.replace(placeholder, data.get(field, ""))

    psychologist_name = data.get("psychologist_name", "")
    footer_information = data.get("footer_information", psychologist_name)
    appendix = data.get("appendix", "")

    # Prepare section bullets
    sections_with_bullets = []
    for key, label in SECTIONS.items():
        bullets = [b for b in data.getlist(key) if b.strip()]
        if bullets:
            sections_with_bullets.append({"key": key, "heading": label, "bullets": bullets})

    # Generate all paragraphs in one call
    if sections_with_bullets:
        prompt = create_batched_prompt(sections_with_bullets, appendix)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        paragraphs_json = json.loads(response.choices[0].message.content.strip())

        for section in sections_with_bullets:
            key = section["key"]
            heading = section["heading"]
            paragraph_text = paragraphs_json.get(heading, "")
            placeholder = f"{{{{{key}_paragraph}}}}"
            for paragraph_obj in doc.paragraphs:
                if placeholder in paragraph_obj.text:
                    paragraph_obj.text = paragraph_obj.text.replace(placeholder, paragraph_text)

    # Prepare test sections
    test_sections = [ts for ts in data.getlist("test_types") if ts.strip()]
    test_data = []
    for i, test_name in enumerate(test_sections, start=1):
        test_bullets = [b for b in data.getlist(f"test_{i}_bullets") if b.strip()]
        test_data.append({"test_name": test_name, "bullets": test_bullets})

    # Generate test paragraphs in one call
    full_test_section = ""
    if test_data:
        test_prompt = create_test_prompt(test_data, appendix)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": test_prompt}],
            temperature=0.7,
        )
        test_paragraphs = json.loads(response.choices[0].message.content.strip())
        for test in test_data:
            test_name = test["test_name"]
            paragraph = test_paragraphs.get(test_name, "")
            full_test_section += f"\n\n{test_name}:\n{paragraph}\n"

    test_list_string = ", ".join(test_sections)

    for paragraph_obj in doc.paragraphs:
        if "{{test_paragraphs}}" in paragraph_obj.text:
            paragraph_obj.text = paragraph_obj.text.replace("{{test_paragraphs}}", full_test_section)
        if "{{test_list}}" in paragraph_obj.text:
            paragraph_obj.text = paragraph_obj.text.replace("{{test_list}}", test_list_string)
        if "{{footer_information}}" in paragraph_obj.text:
            paragraph_obj.text = paragraph_obj.text.replace("{{footer_information}}", footer_information)

    # Footer
    section = doc.sections[-1]
    footer = section.footer
    footer_paragraph = footer.paragraphs[0]
    footer_paragraph.text = f"Report generated by: {psychologist_name}"

    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = os.path.join(tmpdir, "report.docx")
        doc.save(docx_path)

        if "pdf" in data:
            sys = platform.system()
            pdf_path = os.path.join(tmpdir, "report.pdf")
            if sys in ["Windows", "Darwin"]:
                convert(docx_path, pdf_path)
            elif sys == "Linux":
                subprocess.run(["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", tmpdir, docx_path], check=True)
            else:
                return "Unsupported OS for PDF conversion", 500
            return send_file(pdf_path, as_attachment=True, download_name="neuropsych_report.pdf")
        else:
            return send_file(docx_path, as_attachment=True, download_name="neuropsych_report.docx")

if __name__ == "__main__":
    app.run(debug=True)
