# INIT

Setup steps for getting started with this project.

## Prerequisites

- Git
- Power Platform CLI (`pac`) — `winget install Microsoft.PowerPlatformCLI`
- Access to a Power Platform developer environment
- (Optional) VS Code with the Power Platform Tools extension

## Setup

1. Clone the repository.
2. Authenticate: `pac auth create --environment <environment-url>`
3. Copy any required local settings into a `.env` file (git-ignored).
4. Verify connection: `pac org who`

## Repository layout

_To be defined as the project grows._

| Path | Purpose |
|------|---------|
| `CLAUDE.md` | Instructions for Claude Code |
| `INIT.md` | Setup guide (this file) |
| `PLAN.md` | Roadmap and status |
