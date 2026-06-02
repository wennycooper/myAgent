---
name: git
description: Git workflow — commits, branches, diffs, conflict resolution
tags: vcs
---

## Git Workflow

### Inspect state
```bash
git status
git log --oneline -10
git diff
git diff --staged
```

### Common operations
- Stage and commit: `git add -p && git commit -m "msg"`
- New branch: `git checkout -b feature/name`
- Stash: `git stash` / `git stash pop`
- Show file history: `git log --follow -p <file>`

### Merge conflicts
1. `git status` to see conflicted files
2. Edit files to resolve `<<<<<<<` / `=======` / `>>>>>>>` markers
3. `git add <file> && git commit`

### Undo
- Unstage: `git restore --staged <file>`
- Discard working changes: `git restore <file>`
- Amend last commit: `git commit --amend --no-edit`
