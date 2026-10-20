---
id: tasksprint-product-brief
version: "1.0"
status: approved
effective_from: "2026-10-01"
owner: TaskSprint human Product Owner
classification: synthetic-workshop
---
# TaskSprint product brief

## Product goal
Help workshop participants track a short list of tasks. The interface for this
training app is a deterministic command console inside Langflow Playground.

## Starter
The starter can add and list tasks. Every task has a stable ID, title and completed
boolean. The starter returns FEATURE_UNAVAILABLE for the completion operation.
The starter is the known healthy rollback baseline for this workshop.

## Completion story
As a workshop participant, I want to mark a task complete while retaining it in
my list, so I can distinguish finished work from unfinished work.

## Acceptance criteria
AC1: A known task becomes completed and remains stored with the same ID/title.
AC2: Other task records are unchanged.
AC3: Completing an already completed task is safe and has no additional data effect.
AC4: An unknown task ID returns TASK_NOT_FOUND and changes no task data.
AC5: Add and list continue to work; list includes completed and incomplete tasks.
AC6: Stored records and completion flags survive a backend restart.

## Scope
One completion feature only. No reminders, dates, notifications, authentication
feature development, mobile UI, external emails, or real personal information.
Human Product Owner confirmation is required before treating proposed scope as agreed.
