# Job Ops Console Showcase

This branch is a showcase-only presentation of **Job Ops Console**.

The production source code is intentionally kept private. This public branch exists so reviewers can quickly understand the product through a short demo video and selected screenshots, without exposing the full implementation.

## Project Summary

Job Ops Console is one of my portfolio projects and represents part of my broader experience as a developer across:

- backend engineering
- workflow automation
- practical product delivery
- browser-driven operational tooling
- local CI/CD and deployment orchestration

Automation is central to the project, from collecting job data to tracking progress in a single workflow. For this presentation, I also controlled the video creation flow itself through browser automation and scripted media generation. The narration used in the demo is synthetic and is included only for presentation purposes.

In addition to the application workflow itself, I also built a practical local deployment flow around the project: a sanitized publisher repository, a local bare Git remote, a runtime vault for sensitive files, and a scheduled Windows deployment loop that continuously syncs a stable local environment without exposing private runtime data.

## Demo Video

- [Watch the project showcase video in this repo](showcase_assets/video/job_ops_project_showcase.mp4)
- [Public GitHub video link](https://github.com/ThanhDC-FSD/Job-Ops-Console/blob/showcase/showcase_assets/video/job_ops_project_showcase.mp4)

## Screenshots

### Dashboard Overview

![Dashboard Overview](showcase_assets/images/dashboard_overview.png)

### Jobs Density Map

![Jobs Density Map](showcase_assets/images/jobs_density_map.png)

### Jobs Workspace

![Jobs Workspace](showcase_assets/images/jobs_workspace.png)

### Automation Console

![Automation Console](showcase_assets/images/automation_console.png)

## Selected Code Snippets

These excerpts are intentionally partial and are provided only to show implementation style, design choices, and technical depth. They are not enough to run the full application.

- [Backend design patterns excerpt](showcase_assets/code/backend_patterns_excerpt.md)
- [Backend API and filtering excerpt](showcase_assets/code/backend_api_excerpt.md)
- [CV generation and artifact workflow excerpt](showcase_assets/code/cv_generation_excerpt.md)
- [Frontend analytics and interaction excerpt](showcase_assets/code/frontend_analytics_excerpt.md)

## Architecture Overview

This note is intentionally written at a showcase level. It highlights the main system layers and runtime flows, including job crawling, evaluation, automation, and LLM-assisted artifact generation.

- [Project architecture overview](showcase_assets/architecture/basic_project_architecture.md)

## Notes

- This branch is intended for review and presentation only.
- Full source code, infrastructure details, and operational logic are not published in this repository.
- Additional technical discussion or deeper code walkthroughs can be shared separately if needed.
