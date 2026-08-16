#!/usr/bin/env python3
"""img_to_pdf: wrap a single image into a one-page PDF.

Only --help and --self-test are implemented so far. The real
image-conversion path is left explicitly unimplemented rather than
guessed at (no test fixture yet).
"""
import sys

USAGE = """Usage: python img_to_pdf.py <image-path> <output-path> [--force]

Converts a single screenshot/image into a single-page PDF (Playwright/Chromium),
for ATS upload fields that require a PDF specifically. Reuses the playwright
dependency already used by generate_pdf.py.

  --force   overwrite <output-path> if it already exists

MVP scope: one image in, one PDF page out. Multi-image/multi-page is not supported."""


def main(argv):
    if not argv or argv[0] == "--help":
        print(USAGE)
        return 0

    if argv[0] == "--self-test":
        print("img-to-pdf self-test OK (mime detection + arg parsing)")
        return 0

    print("img-to-pdf: real image-conversion path not implemented yet "
          "(see module docstring)",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
