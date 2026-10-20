# Blender Cloud Agent

Mobile-first cloud Blender automation MVP.

## Goal
Create, inspect, revise and export a 3D scene from an Android browser, with no local Blender installation.

## MVP components
- FastAPI backend for jobs and projects
- Headless Blender worker isolated from API
- Mobile PWA with chat and touch-enabled GLB preview
- Deterministic scene operations before optional LLM integration
- Versioned scene artifacts and explicit approval for paid execution

## Security
Never execute generated Python in the API process. Isolate workers, restrict network access, enforce resource limits, and do not expose secrets to Blender.

## Status
Scaffolding in progress; not yet deployed.
