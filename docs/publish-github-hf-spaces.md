# Publish To GitHub And Hugging Face Spaces

This guide assumes you are in the repository root.

## 1) Prepare Local Repository

If this folder is not yet a git repository:

```powershell
git init -b main
```

Stage and commit everything:

```powershell
git add .
git commit -m "Initial commit: RDF demo app and pipelines"
```

If git asks for identity, configure it once:

```powershell
git config --global user.name "YOUR_NAME"
git config --global user.email "YOUR_EMAIL"
```

## 2) Push To GitHub

Create an empty GitHub repository first (for example: rdf-solution-workspace), then run:

```powershell
git remote add origin https://github.com/YOUR_GITHUB_USER/rdf-solution-workspace.git
git push -u origin main
```

If `origin` already exists:

```powershell
git remote set-url origin https://github.com/YOUR_GITHUB_USER/rdf-solution-workspace.git
git push -u origin main
```

## 3) Create Hugging Face Space

Create a new Space in the Hugging Face UI with:

- SDK: Gradio
- Python: 3.11
- Visibility: your choice

Recommended Space repo name: rdf-demonstrator

## 4) Authenticate Hugging Face CLI

Install CLI if needed:

```powershell
pip install -U huggingface_hub
```

Login:

```powershell
huggingface-cli login
```

## 5) Push Same Codebase To Space

Add Space as another git remote and push:

```powershell
git remote add hfspace https://huggingface.co/spaces/YOUR_HF_USER/rdf-demonstrator
git push hfspace main
```

If `hfspace` already exists:

```powershell
git remote set-url hfspace https://huggingface.co/spaces/YOUR_HF_USER/rdf-demonstrator
git push hfspace main
```

## 6) Configure Space Secrets And Variables

In Space Settings -> Variables and secrets:

Required secret:

- OPENAI_API_KEY

Optional variables:

- OPENAI_MODEL=gpt-4.1-mini
- QA_USE_LLM_VERBALIZATION=true
- RDFLIB_STORE_DIR=data/graph-store

The app is already Spaces-ready via:

- app.py as entrypoint
- requirements.txt for dependencies
- rdflib local backend defaults in app behavior

## 7) Verify Deployment

After build completes, open the Space and test:

1. QA tab with one competency question
2. Extraction tab in contract-aware mode
3. Reset to startup state and inspect graphs

## Troubleshooting

- Build fails on dependencies:
  - Verify requirements.txt exists at repository root.
- Space runs but LLM features fail:
  - Check OPENAI_API_KEY secret is set.
- Git push rejected:
  - Pull remote first if it has an initial commit from UI.
  - Example: git pull --rebase origin main
