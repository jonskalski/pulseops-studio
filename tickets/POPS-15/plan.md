# POPS-CP-001: Scaffold Ticket System
**Assigned to:** Codex  
**Planned by:** Claude  
**Status:** Ready for implementation

---

## Objective

Create the scaffolding for a file-based collaborative workflow between Claude (planning/review) and Codex (execution) inside `/root/pulseops-studio`.

---

## What to build

### 1. Ticket template file
Create `/root/pulseops-studio/tickets/TICKET_TEMPLATE.md` with this exact content:

```
# <TICKET-ID>: <Title>
**Assigned to:** Codex  
**Planned by:** Claude  
**Status:** Ready for implementation

---

## Objective

<What this ticket accomplishes and why>

---

## What to build

<Exact implementation steps>

---

## Constraints

<What NOT to do, what NOT to change>

---

## Definition of done

<How we know this is complete>
```

### 2. README for the tickets folder
Create `/root/pulseops-studio/tickets/README.md` with this exact content:

```
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
```

### 3. Review placeholder for this ticket
Create `/root/pulseops-studio/tickets/POPS-CP-001/review.md` with this content:

```
# POPS-CP-001: Peer Review
**Reviewer:** Claude  
**Status:** Pending — awaiting implementation
```

---

## Constraints

- Do not modify any existing files
- Do not create anything outside of `/root/pulseops-studio/tickets/`
- Do not install packages or run pip
- No Python files needed — this is markdown scaffolding only

---

## Definition of done

These files exist with the correct content:
- `/root/pulseops-studio/tickets/TICKET_TEMPLATE.md`
- `/root/pulseops-studio/tickets/README.md`
- `/root/pulseops-studio/tickets/POPS-CP-001/review.md`
