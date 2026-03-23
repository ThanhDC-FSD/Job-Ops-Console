# GitHub Branch Protection For Public Showcase

This repository should expose only the `showcase` branch publicly. The `development` branch must never be recreated or updated on the remote.

## Local Protection

Add the repository hook path so Git uses the tracked `pre-push` guard:

```bash
git config core.hooksPath .githooks
```

What it does:

- blocks any push targeting `refs/heads/development`
- allows normal pushes to `showcase`
- prevents accidental `git push origin development`

## GitHub Remote Ruleset

Create a branch ruleset in GitHub so the remote also rejects `development` even if someone bypasses local hooks.

GitHub path:

1. Open `Settings`
2. Open `Rules`
3. Click `Rulesets`
4. Click `New ruleset`
5. Choose `New branch ruleset`

Recommended configuration:

- Ruleset name: `Block development branch`
- Enforcement status: `Active`
- Target branches:
  - Include by pattern: `development`
- Bypass list:
  - Leave empty if possible

Recommended rules to enable:

- `Restrict creations`
  - prevents recreating `development` after deletion
- `Restrict updates`
  - blocks direct pushes if the branch somehow exists
- `Block force pushes`
- `Block deletions`
  - optional; enable only if you prefer branch state to be handled by admins manually

## Repository Settings Checklist

- Default branch should remain `showcase`
- Do not use `development` in branch sync automation
- Do not configure CI to publish from `development`

## Quick Validation

Local test:

```bash
git push origin development
```

Expected result:

- local `pre-push` hook rejects the command before network push

Remote test after ruleset is active:

- even if local hooks are skipped, GitHub should reject creation or updates to `development`
