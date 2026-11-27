---
name: spec-interview
description: Interview the user about a new feature and write a self-contained spec before any code.
disable-model-invocation: true
---
Feature: $ARGUMENTS

Interview me with the AskUserQuestion tool about the hard parts: data needed from idealo,
edge cases, what the shopper sees, what's out of scope, and how we'll verify it. Skip obvious
questions. When done, append a section to `docs/SPEC.md` that names the files and interfaces
involved, states what is out of scope, and ends with an end-to-end verification step.
Then stop: implementation happens in a fresh session.
