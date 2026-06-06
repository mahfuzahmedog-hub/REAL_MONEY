# Issue Tracker — GitHub

This repo uses **GitHub Issues** as its issue tracker.

## Setup

Requires the `gh` CLI authenticated to the repo:

```
gh auth login
```

## Usage

| Action | Command |
|--------|----------|
| Create issue | `gh issue create --title "..." --body "..." --label "..."` |
| List open issues | `gh issue list` |
| View issue | `gh issue view <number>` |
| Close issue | `gh issue close <number>` |
| Add label | `gh issue edit <number> --add-label "..."` |

## Repo

`https://github.com/mahfuzahmedog-hub/REAL_MONEY.git`

## Labels used by skills

- `needs-triage` — maintainer needs to evaluate
- `needs-info` — waiting on reporter
- `ready-for-agent` — fully specified, AFK-ready
- `ready-for-human` — needs human implementation
- `wontfix` — will not be actioned
