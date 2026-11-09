# Internal Tool for FinTech Client (code-verified)

Project: fr_ml-p12  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_ml/repos/fr_ml-p12

## Summary
This internal tool, built in Python, utilizes LangChain to process prompts and integrates Pinecone for vector search capabilities. It runs inside a Docker container, making local development straightforward via `make dev`. The application is designed to serve a fintech client, providing an efficient backend for data retrieval and analysis.

## Code-verified stack
- Python: `app.py: from pinecone import Pinecone`
- LangChain: `app.py: from langchain_core.prompts import ChatPromptTemplate`
- Pinecone: `app.py: from pinecone import Pinecone`
- Docker: `Dockerfile: FROM python:3.12-slim`
