"""Generates a one-page text PDF for E2E tests.

Usage: python gen_pdf.py <output-path> <text>
"""

import sys

import fitz

path = sys.argv[1]
text = sys.argv[2] if len(sys.argv) > 2 else "Sample notes for testing."

doc = fitz.open()
page = doc.new_page()
# insert_text needs single-line input; wrap roughly at 80 chars.
y = 72
for line in [text[i : i + 80] for i in range(0, len(text), 80)]:
    page.insert_text((72, y), line, fontsize=11)
    y += 16
doc.save(path)
doc.close()
print(path)
