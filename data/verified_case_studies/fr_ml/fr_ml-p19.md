# Internal FinTech Tool (code-verified)

Project: fr_ml-p19  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_ml/repos/fr_ml-p19

## Summary
The internal tool for a fintech client exposes a FastAPI endpoint that uses Pinecone for vector storage and LangGraph to orchestrate agent workflows, all built in Python. Python code imports FastAPI, Pinecone, and LangGraph to create a lightweight API that handles agent interactions and vector queries.

## Code-verified stack
- Python: `agent.py: from langgraph.graph import StateGraph`
- LangGraph: `agent.py: from langgraph.graph import StateGraph`
- Pinecone: `app.py: from pinecone import Pinecone`
- FastAPI: `app.py: from fastapi import FastAPI`
