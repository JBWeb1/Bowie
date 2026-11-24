---
description: Make a real Word, Excel or PowerPoint file (opens in Microsoft 365)
argument-hint: "WHAT, e.g. a quote for 3 websites as Word, or a cash-flow sheet for 2027"
---
Make this as a real Microsoft Office file: $ARGUMENTS

- Word (.docx) with python-docx: proper headings, styles, tables and page numbers, not a wall of text.
- Excel (.xlsx) with openpyxl: real formulas (not typed-in results), number and currency formats, a frozen,
  bold header row, sensible column widths, and a chart where it helps.
- PowerPoint (.pptx) with python-pptx: one idea per slide, large readable text, a title slide, and speaker notes.

Install a missing library with pip first. Save the file under office/, then open it again with the same library
and check it (headings, sheets and formulas, slide count) before telling me it's done and where it is.
If my Microsoft 365 is connected (Connect apps), offer to save it to OneDrive or attach it to an email draft, and
ask before sending anything.
