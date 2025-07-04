from flask import Flask, render_template, request, send_file
from docx import Document
import tempfile, os, platform, subprocess
from openai import OpenAI
from docx2pdf import convert

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

def batched_generate_paragraphs(section_prompts, appendix):
    combined_prompt = "".join(
        f"### {i+1}. {label}\n{content}\n" for i, (content, label) in enumerate(section_prompts)
    )
    prompt = (
        f"You are a clinical psychologist drafting a neuropsychological report. For each section below, write a clear, professional paragraph.\n"
        f"Incorporate relevant insights from the test appendix where applicable.\n"
        f"Respond ONLY with the numbered paragraphs in the same order.\n"
        f"\n{combined_prompt}\n\nAppendix/Test Scores:\n{appendix}\n"
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return [p.strip() for p in response.choices[0].message.content.strip().split("\n") if p.strip()]

def generate_test_analysis(test_name, appendix):
    prompt = (
        f"Please write a paragraph analyzing the results and significance of the following neuropsychological test: {test_name}. "
        f"Use the appendix information below to guide the interpretation if relevant.\n\n"
        f"Appendix/Test Scores:\n{appendix}\n"
        f"Professional Analysis:"
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()

@app.route("/")
def index():
    return render_template("form.html", sections=SECTIONS)

@app.route("/generate", methods=["POST"])
def generate():
    data = request.form
    doc = Document("doc_templates/report_template.docx")

    for field in ["name", "dob", "age", "grade", "school", "eval_dates"]:
        placeholder = f"{{{{{field}}}}}"
        for paragraph in doc.paragraphs:
            if placeholder in paragraph.text:
                paragraph.text = paragraph.text.replace(placeholder, data.get(field, ""))

    psychologist_name = data.get("psychologist_name", "")
    footer_information = data.get("footer_information", psychologist_name)
    appendix = data.get("appendix", "")

    section_prompts = []
    for key, label in SECTIONS.items():
        text = data.get(key, "").strip()
        if text:
            section_prompts.append((f"{label} Section\n{text}", f"{{{{{key}_paragraph}}}}"))

    paragraphs = batched_generate_paragraphs(section_prompts, appendix)
    for (_, placeholder), paragraph in zip(section_prompts, paragraphs):
        for paragraph_obj in doc.paragraphs:
            if placeholder in paragraph_obj.text:
                paragraph_obj.text = paragraph_obj.text.replace(placeholder, paragraph)

    # Handle test sections
    test_sections = [ts for ts in data.getlist("test_types") if ts.strip()]
    test_texts = []
    for i, test_name in enumerate(test_sections, start=1):
        test_bullets = [b for b in data.getlist(f"test_{i}_bullets") if b.strip()]
        section_text = f"\n\n{test_name}:\n"
        if test_bullets:
            bullet_text = "\n".join(f"- {b}" for b in test_bullets)
            test_prompt = (
                f"Write a professional paragraph summarizing the following test and bullet points.\n"
                f"Test: {test_name}\nBullets:\n{bullet_text}\n\nAppendix:\n{appendix}"
            )
            test_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": test_prompt}],
                temperature=0.7,
            )
            section_text += test_response.choices[0].message.content.strip() + "\n"
        analysis = generate_test_analysis(test_name, appendix)
        section_text += analysis
        test_texts.append(section_text)

    full_test_section = "\n\n".join(test_texts)
    test_list_string = ", ".join(test_sections)

    for paragraph_obj in doc.paragraphs:
        if "{{test_paragraphs}}" in paragraph_obj.text:
            paragraph_obj.text = paragraph_obj.text.replace("{{test_paragraphs}}", full_test_section)
        if "{{test_list}}" in paragraph_obj.text:
            paragraph_obj.text = paragraph_obj.text.replace("{{test_list}}", test_list_string)
        if "{{footer_information}}" in paragraph_obj.text:
            paragraph_obj.text = paragraph_obj.text.replace("{{footer_information}}", footer_information)

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
                return send_file(pdf_path, as_attachment=True, download_name="neuropsych_report.pdf")
            else:
                return "PDF conversion is only supported on macOS or Windows environments.", 400
        else:
            return send_file(docx_path, as_attachment=True, download_name="neuropsych_report.docx")


if __name__ == "__main__":
    app.run(debug=True)
