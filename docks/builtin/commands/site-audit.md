---
description: Lighthouse-style performance, accessibility and SEO audit, then fix what you can
argument-hint: "[URL]"
---
Audit $ARGUMENTS (or this project's running site if no URL is given) like Lighthouse plus an SEO expert (inspired by Lighthouse, claude-seo and Clinic.js).
1. If Node is available run `npx lighthouse <url> --output=json --quiet --chrome-flags=--headless` and read the scores; otherwise inspect the page with the browser tool.
2. Report performance (LCP, CLS, INP, bundle size), accessibility, SEO (titles, meta descriptions, headings, structured data, sitemap, robots.txt, Open Graph) and best practices, ranked by impact.
3. Fix the issues that live in this project, then re-check.
