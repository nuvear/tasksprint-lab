# Instructor fixture: intentionally wrong. Never describe it as an unprompted live mistake.
def complete(tasks, task_id):
    remaining = [task for task in tasks if task["id"] != task_id]
    return {"ok": True, "code": "COMPLETED", "tasks": remaining}
