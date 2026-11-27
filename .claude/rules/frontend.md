---
paths:
  - "app/static/**"
---
# Frontend rules
- No build step and no frameworks: one HTML file with inline CSS and JS.
- Escape every server value with `esc()` before inserting it into HTML.
- Mobile first (375 px wide); the label must also be written as text, not shown by colour alone.
- The data source badge ("Demo data" or "Live idealo data") must stay visible.
