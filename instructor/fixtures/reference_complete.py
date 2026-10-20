# Instructor-only reference. A fallback using this must be visibly labelled.
def complete(tasks, task_id):
    for task in tasks:
        if task["id"] == task_id:
            task["completed"] = True
            return {"ok": True, "code": "COMPLETED", "tasks": tasks}
    return {"ok": False, "code": "TASK_NOT_FOUND", "tasks": tasks}
