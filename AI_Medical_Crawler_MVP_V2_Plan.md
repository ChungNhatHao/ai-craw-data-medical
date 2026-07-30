# AI Medical Crawler - MVP + V2 Technical Plan

## Project Goal

Build an AI Browser Agent to crawl medical content from
**genre-manuals.com** (using a site plugin), then export structured data
for future Knowledge Base/RAG.

> Scope: Login -\> Navigate -\> Crawl -\> Extract -\> Clean -\> Parse
> -\> Export. No RAG, Vector DB or Chatbot in this phase.

------------------------------------------------------------------------

# Tech Stack

-   Python 3.12
-   FastAPI
-   LangGraph
-   GPT-5.5 + Vision (fallback)
-   Playwright
-   Trafilatura
-   BeautifulSoup4 + lxml
-   Pydantic v2
-   Loguru
-   python-dotenv
-   Docker Compose

------------------------------------------------------------------------

# Project Structure

``` text
medical-crawler/
├── app/
│   ├── api/
│   ├── agents/
│   ├── browser/
│   ├── parser/
│   ├── prompts/
│   ├── models/
│   ├── utils/
│   └── plugins/
│       └── genre_manuals/
│           ├── login.py
│           ├── navigator.py
│           ├── parser.py
│           └── prompts/
├── output/
├── logs/
├── tests/
└── main.py
```

# MVP (9 Working Days)

## Day 1

-   Project setup
-   FastAPI
-   Playwright
-   LangGraph
-   Logging

Deliverable: Project runs.

## Day 2

-   Login
-   Cookie persistence
-   Session validation

Deliverable: cookies.json

## Day 3

-   AI navigation
-   Find disease menu
-   Detect current page type
-   Navigation loop: keep searching until a disease-detail page is confirmed
-   Loop guard: max hops, repeated URL/fingerprint and no-progress detection
-   Popup handling
-   Retry

Deliverable: Reach disease list and reliably recognize disease-detail pages.

## Day 4

-   Crawl disease list
-   Export disease-list.json

## Day 5-6

-   Crawl disease detail
-   Only crawl after the page classifier confirms `DISEASE_DETAIL`
-   Save raw.html
-   Save screenshot

## Day 7

-   Clean HTML
-   Convert to Markdown

## Day 8-9

-   GPT structured parsing
-   Export disease.json

Output:

``` text
output/
├── disease-list.json
└── Diseases/
    └── DiseaseName/
        ├── raw.html
        ├── markdown.md
        ├── disease.json
        └── screenshot.png
```

Definition of Done: - Auto login - Auto navigate - Crawl all diseases -
Export HTML/Markdown/JSON

------------------------------------------------------------------------

# V2 (5-7 Working Days)

## Goal

Make the crawler production-ready while keeping genre-manuals.com as the
first plugin.

## Day 1

-   Plugin architecture
-   Core + genre_manuals plugin

## Day 2

-   Resume crawling
-   Checkpoint after each disease

## Day 3

-   Retry strategy
-   Error classification
-   Failed task queue

## Day 4

-   Vision fallback
-   Use GPT-5.5 Vision only when Playwright cannot locate elements

## Day 5

-   Incremental crawling
-   Duplicate detection
-   Hash comparison

## Day 6

-   CLI
-   crawl login
-   crawl run
-   crawl resume
-   crawl export

## Day 7

-   Docker packaging
-   Configuration
-   Crawl report

Deliverables: - Plugin-based crawler - Resume support - Retry support -
Incremental crawl - Vision fallback - Docker deployment

------------------------------------------------------------------------

# Prompt Modules

-   login_prompt.md
-   navigation_prompt.md
-   discovery_prompt.md
-   extraction_prompt.md
-   parser_prompt.md
-   recovery_prompt.md

------------------------------------------------------------------------

# Future V3

-   Knowledge Base
-   Embedding
-   Vector Database
-   RAG
-   Chatbot
