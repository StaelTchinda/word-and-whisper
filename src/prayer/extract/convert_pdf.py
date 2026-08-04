#!/usr/bin/env python3

import sys
from pathlib import Path
import fitz
from pdf2image import convert_from_path
import pytesseract
from PIL import Image
import textstat
import io

def get_text_quality_score(text):
    """Score text quality (0-100). Higher = better quality."""
    if not text or len(text.strip()) < 10:
        return 0

    lines = text.split('\n')
    word_count = len(text.split())

    # Check average line length
    avg_line_len = sum(len(line) for line in lines) / len(lines) if lines else 0

    # Score: penalize if too many short/garbled lines
    short_lines = sum(1 for line in lines if len(line.strip()) < 5)
    short_line_ratio = short_lines / len(lines) if lines else 1

    # Check for common OCR artifacts
    ocr_artifacts = ['ffl', 'Iffl', '|', '^', 'rn', 'rH', '|fl']
    artifact_count = sum(text.count(a) for a in ocr_artifacts)

    # Base score on word count and readability
    score = 100
    score -= short_line_ratio * 30  # Penalize short lines
    score -= min(artifact_count * 2, 30)  # Penalize OCR artifacts
    score += min(textstat.flesch_kincaid_grade(text) * 2, 20)  # Bonus for readable text

    return max(0, min(100, score))

def extract_with_pymupdf(pdf_path):
    """Extract text using PyMuPDF (fitz) - fast, for text-based PDFs."""
    try:
        markdown_lines = []
        doc = fitz.open(str(pdf_path))

        for page_num in range(len(doc)):
            page = doc[page_num]
            markdown_lines.append(f"\n<!-- Page {page_num + 1} -->\n")

            # Try dict extraction for better layout preservation
            try:
                text_dict = page.get_text("dict")
                blocks_text = []
                for block in text_dict.get("blocks", []):
                    if block.get("type") == 0:  # Text block
                        block_text = "\n".join(
                            "".join(span["text"] for span in line.get("spans", []))
                            for line in block.get("lines", [])
                        )
                        if block_text.strip():
                            blocks_text.append(block_text)
                text = "\n".join(blocks_text)
            except:
                text = page.get_text(sort=True)

            if text.strip():
                markdown_lines.append(text)

        doc.close()
        return "\n".join(markdown_lines)
    except Exception as e:
        print(f"PyMuPDF extraction failed: {e}", file=sys.stderr)
        return None

def extract_with_ocr(pdf_path, use_tesseract=True, dpi=150):
    """Extract text using OCR on PDF pages."""
    try:
        markdown_lines = []

        # Convert PDF pages to images (lower DPI for speed)
        print(f"  Converting PDF to images for OCR (DPI={dpi})...", file=sys.stderr)
        images = convert_from_path(str(pdf_path), dpi=dpi)

        for page_num, image in enumerate(images, 1):
            markdown_lines.append(f"\n<!-- Page {page_num} (OCR) -->\n")

            if use_tesseract:
                # Use Tesseract OCR
                text = pytesseract.image_to_string(image, lang='eng')
            else:
                # Fallback (shouldn't reach here with use_tesseract=True)
                text = ""

            if text.strip():
                markdown_lines.append(text)

        return "\n".join(markdown_lines)
    except Exception as e:
        print(f"OCR extraction failed: {e}", file=sys.stderr)
        return None

def convert_pdf_to_markdown(pdf_path, use_ocr=False):
    """
    Convert PDF to Markdown with text validation.
    Tries multiple extraction methods and picks the best result.
    """
    pdf_path = Path(pdf_path).resolve()

    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    if not pdf_path.suffix.lower() == '.pdf':
        print(f"Error: File is not a PDF: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    # Extract source directory and filename
    try:
        parts = pdf_path.parts
        raw_idx = parts.index('raw')
        source_idx = raw_idx - 1
        source_name = parts[source_idx]
        filename = pdf_path.stem + '.md'

        output_dir = pdf_path.parent.parent / 'clean'
        output_path = output_dir / filename

        output_dir.mkdir(parents=True, exist_ok=True)
    except (ValueError, IndexError):
        print(f"Error: PDF path doesn't follow expected structure: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Converting: {pdf_path.name}")
    print(f"Output: {output_path}")

    # Try extraction methods
    results = {}

    # Method 1: PyMuPDF (fast)
    print("  Trying PyMuPDF extraction...", file=sys.stderr)
    pymupdf_text = extract_with_pymupdf(pdf_path)
    if pymupdf_text:
        pymupdf_score = get_text_quality_score(pymupdf_text)
        results['pymupdf'] = (pymupdf_text, pymupdf_score)
        print(f"    PyMuPDF quality score: {pymupdf_score:.1f}", file=sys.stderr)

    # Method 2: Tesseract OCR (slower, but better for scanned/complex layouts)
    if use_ocr or (pymupdf_text and results['pymupdf'][1] < 60):
        print("  Trying Tesseract OCR extraction...", file=sys.stderr)
        ocr_text = extract_with_ocr(pdf_path, dpi=150)  # Lower DPI for faster processing
        if ocr_text:
            ocr_score = get_text_quality_score(ocr_text)
            results['ocr'] = (ocr_text, ocr_score)
            print(f"    OCR quality score: {ocr_score:.1f}", file=sys.stderr)

    if not results:
        print("Error: All extraction methods failed", file=sys.stderr)
        sys.exit(1)

    # Pick the best result
    best_method = max(results.items(), key=lambda x: x[1][1])
    markdown_content = best_method[1][0]
    best_score = best_method[1][1]
    print(f"  Using {best_method[0].upper()} (quality: {best_score:.1f})", file=sys.stderr)

    # Save to file
    try:
        output_path.write_text(markdown_content, encoding='utf-8')
        output_size = output_path.stat().st_size
        input_size = pdf_path.stat().st_size
        size_ratio = (output_size / input_size) * 100 if input_size > 0 else 0
        print(f"✓ Conversion complete")
        print(f"  Input size:  {input_size:,} bytes")
        print(f"  Output size: {output_size:,} bytes ({size_ratio:.1f}%)")
        print(f"  Quality score: {best_score:.1f}/100")
    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python convert_pdf_to_markdown.py <pdf_path> [--use-ocr]", file=sys.stderr)
        sys.exit(1)

    use_ocr = '--use-ocr' in sys.argv
    pdf_path = sys.argv[1]

    convert_pdf_to_markdown(pdf_path, use_ocr=use_ocr)
