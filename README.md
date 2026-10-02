```markdown
# EntQra — Universal Research Intelligence Engine

> **Search less. Understand more.**

EntQra is a universal, query-driven research intelligence engine designed to transform open-ended user questions into structured, evidence-backed intelligence.

Instead of behaving like a traditional search engine that simply returns links, EntQra dynamically understands the query, identifies entities and intent, researches across multiple sources, fuses evidence, removes duplication, evaluates confidence, and generates an adaptive intelligence response.

---

## 🚀 What is EntQra?

EntQra is built around a simple idea:

> **Any query should receive the research structure it actually needs.**

A question about a company should not receive the same structure as a technical question.

For example:

### Query

```text
Who is NVIDIA?
```

EntQra can generate sections such as:

```text
Intelligence Answer
Company Overview
History
Products & Technology
Leadership
Business
Relationships
Sources
```

While:

```text
How does a Transformer work?
```

can produce:

```text
Intelligence Answer
Core Concept
Architecture
Attention Mechanism
Training
Inference
Applications
Limitations
Sources
```

The response architecture is determined by the research intent rather than a fixed template.

---

# 🧠 Core Architecture

```text
                    USER QUERY
                         │
                         ▼
                Query Understanding
                         │
                         ▼
                 Entity Resolution
                         │
                         ▼
                  Intent Detection
                         │
                         ▼
               Dynamic Research Plan
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       Tavily           Exa           Serper
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                  Source Fusion
                         │
                         ▼
                Evidence Extraction
                         │
                  ┌──────┴──────┐
                  ▼             ▼
             Deduplication   Cross-checking
                  │             │
                  └──────┬──────┘
                         ▼
                 Confidence Engine
                         │
                         ▼
                Adaptive Dossier
                         │
                         ▼
                     Frontend
```

---

# ✨ Key Features

## 🌐 Universal Query Engine

EntQra is designed to work across different types of queries and entities.

Examples:

```text
Google
Microsoft
NVIDIA
Sundar Pichai
Python
Bitcoin
Artificial Intelligence
How does a Transformer work?
Google vs Microsoft
```

The research strategy adapts according to the query.

---

## 🎯 Query-Driven Research

EntQra first determines what the user is actually asking.

The system can reason about:

- Query intent
- Entity type
- Research requirements
- Relevant information categories
- Required research depth

This prevents every query from being forced into the same response format.

---

## 🔎 Multi-Source Research

EntQra integrates multiple research providers.

Current providers include:

- **Tavily**
- **Exa**
- **Serper**

The goal is to combine information from multiple sources instead of relying on a single search provider.

---

## 🧩 Source Fusion

Results from different providers are normalized and combined into a unified research pool.

```text
Tavily
   │
   ├──────────┐
Exa          │
   │         ▼
   └────► Source Fusion
             │
Serper ──────┘
```

This allows EntQra to reason over a broader evidence base.

---

## 🧹 Evidence Deduplication

Multiple search providers can return the same or highly similar sources.

EntQra processes research results to reduce duplication and improve the quality of the evidence pool.

---

## 📊 Confidence Engine

EntQra evaluates the available evidence and generates a confidence assessment for the resulting intelligence.

The long-term goal is to make confidence depend on factors such as:

```text
Source authority
       +
Source independence
       +
Evidence agreement
       +
Evidence coverage
       +
Freshness
       +
Entity relevance
       +
Contradictions
```

Confidence is intended to represent the strength of the evidence rather than simply the number of search results.

---

# 🧠 EntQra Golden Rules

EntQra follows several core architectural principles.

### Golden Rule #1 — Complete, Safe Code Changes

Development follows a controlled replacement workflow:

```text
Design
  ↓
Complete file
  ↓
Copy / Replace
  ↓
Run
  ↓
Test
  ↓
Evaluate
```

This minimizes accidental partial modifications to the working system.

---

### Golden Rule #2 — Use Advanced Technology When It Has a Purpose

EntQra can incorporate advanced technologies when they provide a real architectural benefit.

Potential technologies include:

- RAG
- PostgreSQL
- pgvector
- Embedding models
- Reranking
- Knowledge graphs
- Entity resolution
- Claim verification
- Research loops
- Evaluation pipelines

Technology is introduced based on its purpose, not simply because it is available.

---

### Golden Rule #3 — Universal Intelligence Architecture

> **Universal + query-driven + entity-aware + adaptive + evidence-backed + RAG-powered + multi-source + high-confidence.**

---

### Golden Rule #4 — Answer the Actual Question

> **EntQra answers the search that the user actually asked — completely and in detail — without forcing irrelevant sections or repeating information.**

---

# 🏗️ Project Structure

```text
ENTORA/
│
├── backend/
│   ├── main.py
│   ├── auth.py
│   └── __pycache__/
│
├── database/
│
├── docs/
│
├── extension/
│
├── frontend/
│   ├── public/
│   ├── src/
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.js
│
├── scripts/
│
├── .env
├── .gitignore
└── README.md
```

> The project structure will evolve as EntQra moves toward a more modular research architecture.

---

# ⚙️ Technology Stack

## Backend

- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- PostgreSQL
- Pydantic

## Research

- Tavily
- Exa
- Serper

## AI / NLP

- OpenAI-compatible APIs
- Transformers
- Sentence Transformers
- Hugging Face ecosystem
- Scikit-learn

## Data & Retrieval

- PostgreSQL
- SQLAlchemy
- pgvector *(planned/being integrated)*

## Frontend

- React
- Vite
- JavaScript
- HTML
- CSS

---

# 🔐 Environment Variables

EntQra uses environment variables for API credentials and configuration.

Create a `.env` file in the project root:

```env
TAVILY_API_KEY=your_tavily_api_key
EXA_API_KEY=your_exa_api_key
SERPER_API_KEY=your_serper_api_key

OPENAI_API_KEY=your_openai_api_key

DATABASE_URL=your_postgresql_connection_string
```

Never commit real API keys or passwords to GitHub.

Make sure `.env` is included in `.gitignore`.

---

# 🚀 Running EntQra Locally

## 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/ENTORA.git
cd ENTORA
```

---

# Backend Setup

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the backend:

```bash
python -m uvicorn backend.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

FastAPI documentation:

```text
http://127.0.0.1:8000/docs
```

---

# Frontend Setup

Open another terminal:

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Start the development server:

```bash
npm run dev
```

Vite will provide the local frontend URL, typically:

```text
http://localhost:5173
```

---

# 🗄️ Database

EntQra uses PostgreSQL for persistent application data.

The database architecture is being extended toward:

```text
PostgreSQL
      │
      ├── Application Data
      │
      ├── Research Evidence
      │
      ├── Entities
      │
      ├── Claims
      │
      └── Vector Embeddings
             │
             ▼
          pgvector
```

The pgvector layer is part of the next major development stage.

---

# 🔬 Research Pipeline

A typical EntQra research request follows this process:

```text
1. User Query
       ↓
2. Query Understanding
       ↓
3. Entity Identification
       ↓
4. Intent Detection
       ↓
5. Research Planning
       ↓
6. Multi-Provider Search
       ↓
7. Source Collection
       ↓
8. Evidence Extraction
       ↓
9. Deduplication
       ↓
10. Cross-Source Analysis
       ↓
11. Confidence Evaluation
       ↓
12. Adaptive Intelligence Response
```

---

# 🧠 Development Roadmap

EntQra is being developed progressively rather than attempting to implement the entire intelligence architecture at once.

## Phase 1 — Persistent RAG Memory

```text
Research
   ↓
Clean Evidence
   ↓
Chunking
   ↓
Embeddings
   ↓
PostgreSQL + pgvector
   ↓
EntQra Knowledge Memory
```

The objective is to allow EntQra to retrieve previously researched knowledge while combining it with fresh web research.

---

## Phase 2 — Claim-Level Verification

Move from source-level confidence toward claim-level evidence.

```text
CLAIM
 ├── Source A ✓
 ├── Source B ✓
 └── Source C ?
```

This allows EntQra to identify:

- Strongly supported claims
- Partially supported claims
- Conflicting claims
- Unsupported claims

---

## Phase 3 — Smarter Confidence Engine

Confidence will eventually consider:

```text
Authority
Independence
Agreement
Coverage
Freshness
Relevance
Contradictions
```

Low-confidence results can trigger additional targeted research.

---

## Phase 4 — Dynamic Answer Architecture

The backend will return adaptive sections instead of relying on a permanent response template.

Example:

```json
{
  "query": "...",
  "intent": "...",
  "entity": "...",
  "sections": []
}
```

This allows different queries to generate completely different research structures.

---

## Phase 5 — Evidence-Backed Knowledge Graph

Relationships will evolve from simple connections into evidence-backed relationships.

```text
Entity A
   │
Relationship
   │
Entity B
```

Each relationship can eventually contain:

```text
Entity A
Relationship
Entity B
Evidence
Source
Confidence
Date
```

---

## Phase 6 — Adaptive Frontend

The React frontend will render the structure returned by the intelligence engine.

```text
EntQra Response
       ↓
    sections[]
       ↓
Section Renderer
       ↓
Dynamic UI
```

This means new research sections can be introduced without redesigning the entire frontend.

---

# 🔥 Future Research Modes

EntQra is designed to support different research depths.

### Quick

```text
Fast research
Few strong sources
Concise intelligence
```

### Standard

```text
Multiple sources
Cross-checking
Structured response
```

### Deep

```text
Multiple research rounds
More sources
Evidence verification
RAG retrieval
```

### Expert

```text
Deep research
Primary-source priority
Claim verification
Conflict analysis
Historical/current separation
Maximum evidence coverage
```

---

# 🎯 Vision

The long-term goal of EntQra is to move beyond traditional search.

Traditional search:

```text
Question
   ↓
Search Results
   ↓
User Reads Links
   ↓
User Builds Understanding
```

EntQra:

```text
Question
   ↓
Understand
   ↓
Research
   ↓
Collect Evidence
   ↓
Verify
   ↓
Connect Knowledge
   ↓
Evaluate Confidence
   ↓
Generate Intelligence
```

The objective is to create a system that can research **any meaningful topic**, understand the structure of the question, retrieve relevant evidence, connect entities and claims, and present the resulting intelligence in a format appropriate to the query.

---

# 🧪 Example Queries

EntQra is designed for queries such as:

```text
Who is NVIDIA?

What does OpenAI do?

How does a Transformer work?

Google vs Microsoft

What happened to the semiconductor industry?

How are NVIDIA and TSMC connected?

What are the major applications of computer vision?

Explain the architecture of a modern RAG system.
```

The resulting structure should adapt to the question.

---

# 🛡️ Security

Do not commit:

```text
.env
API keys
Database passwords
Private credentials
Authentication secrets
```

Use environment variables for sensitive configuration.

---

# 📌 Project Status

**EntQra is actively under development.**

### Current foundation

```text
✅ Universal research foundation
✅ Query-driven research
✅ Entity-aware architecture
✅ Multi-source search
✅ Tavily integration
✅ Exa integration
✅ Serper integration
✅ Source fusion
✅ Evidence processing
✅ Deduplication
✅ Confidence scoring
✅ Adaptive intelligence responses
✅ FastAPI backend
✅ React frontend
✅ PostgreSQL integration

🚧 Persistent RAG memory
🚧 pgvector integration
🚧 Claim-level verification
🚧 Advanced confidence engine
🚧 Evidence-backed knowledge graph
🚧 Fully adaptive frontend
🚧 Deep Research modes
🚧 Evaluation framework
🚧 Production hardening
```

---

# 🤝 Contributing

EntQra is currently being developed as an evolving research-intelligence project.

Ideas, improvements, architecture discussions, and technical contributions are welcome.

---

# 📜 License

License information will be added as the project approaches its public release.

---

# 🧠 The Mind Behind EntQra

### Affan Bin Hassan

**Artificial Intelligence & Data Science · Hyderabad, India 🇮🇳**

> *I didn't want another search engine.*
>
> *I wanted a system that could research.*

**EntQra** is the result of that idea —  
an attempt to move from **search → evidence → understanding → intelligence.**

---

<p align="center">
  <strong>Built from curiosity. Engineered with intelligence.</strong>
</p>

---

## ⭐ EntQra

> **From search results to research intelligence.**
```

### One important thing before you push this

I deliberately wrote **pgvector/RAG as upcoming work**, rather than pretending it's already implemented. Your current PostgreSQL setup is working, but `vector` isn't installed yet, so the README should accurately represent the project.

Also, **don't put your real `.env` contents on GitHub**. Your `.gitignore` should contain at minimum:

```gitignore
.env
.venv/
__pycache__/
*.pyc
node_modules/
dist/
```