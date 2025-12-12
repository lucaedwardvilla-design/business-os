---
description: Generate daily brief with TOP 2 priorities and quick win. Start each day with clarity.
---

Start the day by generating a focused daily brief.

## Data Sources

Read these files (if they exist):
- `workspace/foundations/tasks.md` - Current task list
- `workspace/foundations/gains.md` - Recent wins for context
- `workspace/foundations/daily-brief.md` - Yesterday's brief

## Process

1. **Gather Context**: Understand current priorities and recent progress
2. **Select TOP 2 Tasks**: Choose the two most important tasks based on:
   - Revenue impact
   - Strategic importance
   - What will move the needle most
3. **Break Down Tasks**: For each TOP 2, create 2-4 concrete subtasks
4. **Choose Quick Win**: Select one 10-15 minute task for momentum

## Output

Write to `workspace/foundations/daily-brief.md`:

```markdown
## Daily Brief - {Day, Month Date, Year}

### Quick Win (10-15 min)
- [ ] [Chosen activity]

---

### Today's Focus (TOP 2)

**1. [Primary Task Name]**
- [ ] Step 1: [subtask]
- [ ] Step 2: [subtask]
- **Done when**: [specific outcome]

**2. [Secondary Task Name]**
- [ ] Step 1: [subtask]
- [ ] Step 2: [subtask]
- **Done when**: [specific outcome]

---

### If Time Permits
- [Task from backlog]

---

### Context
- **Recent win**: [from gains.md if available]
```

## Confirm

After generating, ask:
> "Here's your focus for today. Does this feel right? Any adjustments?"
