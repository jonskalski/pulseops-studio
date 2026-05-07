# Tickets

This folder contains work tickets for the Claude/Codex collaborative workflow.

## Folder structure

tickets/
  <TICKET-ID>/
    brief.md       <- Jon's original ask
    plan.md        <- Claude's implementation spec (Codex reads this)
    review.md      <- Claude's peer review after implementation

## Workflow

1. Jon drops a brief.md describing the task
2. Claude reads it and writes plan.md — a precise spec for Codex to execute
3. Claude dispatches Codex via: codex exec "Read tickets/<id>/plan.md and implement it exactly"
4. Codex implements, commits
5. Claude reviews the diff and writes review.md
6. Jon does client review and approves

## Naming

Tickets are named POPS-CP-### (CP = Control Panel project).
Increment from the last ticket in this folder.
