# Internal Tool for E-Commerce Client (code-verified)

Project: fr_ml-p03  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_ml/repos/fr_ml-p03

## Summary
This repository contains an internal tool built for an e‑commerce client. It uses Python and LangGraph to orchestrate a RAG pipeline, retrieving relevant information and generating responses. The data processing leverages scikit‑learn pipelines, while the OpenAI API powers the language model calls. Docker is used to containerise the application for easy deployment.

## Code-verified stack
- Python: `agent.py: from langgraph.graph import StateGraph`
- LangGraph: `agent.py: from langgraph.graph import StateGraph`
- RAG: `agent.py: def retrieve_then_generate(question, store, llm):`
- scikit-learn: `train.py: from sklearn.pipeline import Pipeline`
- OpenAI API: `app.py: from openai import OpenAI`
- Docker: `Dockerfile: FROM python:3.12-slim`
