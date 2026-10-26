---
description: Crawl a website into clean Markdown files for research or a knowledge base
argument-hint: "URL [max pages]"
---
Crawl $ARGUMENTS into clean Markdown (inspired by Firecrawl). Respect robots.txt, stay on the same site, and fetch at most 40 pages unless I give a number. Strip navigation, cookie banners and ads. Save each page under knowledge/<site>/<path>.md with its title and URL at the top, then write knowledge/<site>/index.md summarizing what is there and linking every page.
