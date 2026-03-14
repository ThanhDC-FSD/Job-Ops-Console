# Basic Project Architecture

This document is intentionally kept at a **basic showcase level**. It is meant to help reviewers understand the overall structure of the project without exposing full implementation or operational details.

## Purpose

Job Ops Console is designed as an internal-style workflow application for:

- collecting job data
- organizing and filtering opportunities
- evaluating fit against a CV profile
- generating application artifacts
- tracking application progress in one operational interface

## High-Level Structure

```text
Browser UI (React / Vite)
    |
    v
Backend API (FastAPI)
    |
    +--> SQLite data store
    |
    +--> Automation actions / scheduled jobs
    |
    +--> CV rewrite and artifact generation
    |
    +--> Analytics and reporting views
```

## Main Layers

### 1. Frontend

The frontend is a React-based operator console.

It is responsible for:

- dashboard visualization
- jobs table and filters
- analytics views
- automation controls
- previewing CV, portfolio, and related artifacts

This layer is designed for repeated operational use rather than a public-facing marketing interface.

### 2. Backend API

The backend is built around FastAPI and exposes endpoints for:

- job listing and filtering
- job detail retrieval
- analytics queries
- automation triggers
- CV rewrite/generation workflows
- file preview and artifact access

This layer acts as the orchestration point between the UI, stored data, and generation/automation logic.

### 3. Data Layer

SQLite is used as the working datastore for:

- crawled job records
- normalized location and language metadata
- fit evaluation results
- application tracking status
- generated artifact paths
- schedule and automation run history

For showcase purposes, this is presented as a lightweight operational datastore.

### 4. Automation Layer

Automation is a core part of the project.

It covers workflows such as:

- crawl execution
- post-processing
- fit evaluation
- CV generation
- apply-flow support
- scheduled operational tasks

This is one of the main areas that reflects my developer workflow and product-delivery style.

### 5. Artifact Generation Layer

The application can generate and manage artifacts such as:

- tailored CV text
- DOCX/PDF CV output
- cover letter files
- portfolio PDF
- showcase video references

This layer combines rule-based processing, rendering scripts, and LLM-assisted content generation where appropriate.

## Simplified Flow

```text
1. Job data is collected or refreshed
2. Backend stores and normalizes the data
3. UI presents jobs and analytics
4. Fit evaluation and CV generation can be triggered
5. Generated artifacts are stored and linked back to the job record
6. Operators review, track, and continue the application workflow
```

## Showcase Note

This architecture file is intentionally basic and is included only for showcase purposes.

It is not intended to document:

- full deployment topology
- production secrets or infrastructure
- internal implementation details
- proprietary automation logic

If needed, a deeper technical walkthrough can be shared separately in a controlled setting.
