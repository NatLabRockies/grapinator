---
description: "Analyze the codebase for security vulnerabilities, produce a remediation plan, and file it as a new GitHub issue."
name: "Security Audit Plan"
argument-hint: "Optional: focus area (e.g. auth, db, deps) — leave blank for full audit"
agent: "agent"
tools: [codebase, search, usages, problems, runCommands, githubRepo]
---

# Security Audit Plan

Your task is to **plan** (not implement) a security review of this workspace and then **open a new GitHub issue** containing that plan so the user can review and prioritize it.

## Scope

The user may pass a focus area as `${input:focus}` (e.g. `auth`, `db`, `deps`, `docker`). If blank or absent, perform a full-codebase audit covering all areas below.

## Procedure

1. **Survey the codebase** (read-only). Identify:
   - Languages, frameworks, and runtime entry points (look at [pyproject.toml](pyproject.toml), [grapinator/app.py](grapinator/app.py), [grapinator/auth.py](grapinator/auth.py), [grapinator/middleware.py](grapinator/middleware.py), [grapinator/settings.py](grapinator/settings.py), [docker/Dockerfile.alpine](docker/Dockerfile.alpine)).
   - Trust boundaries: HTTP request handlers, GraphQL resolvers, DB access, auth/JWT flows, file/config loaders, subprocess calls.
   - Third-party dependencies and their pinned versions.

2. **Analyze for vulnerability classes.** At minimum cover the OWASP Top 10 plus categories relevant to this stack:
   - Injection (SQL / GraphQL / command / template).
   - Broken authentication & session management (JWT validation, token expiry, refresh, OIDC/Keycloak integration).
   - Broken access control / RBAC bypass (review `grapinator_rbac*.ini` and resolver guards).
   - Cryptographic failures (weak hashing, hardcoded secrets, TLS config).
   - Insecure deserialization / unsafe `yaml.load` / `pickle` / `eval` usage.
   - Security misconfiguration (debug flags, CORS, permissive defaults, exposed admin endpoints).
   - Vulnerable & outdated dependencies (run `pip-audit` or equivalent if available; otherwise list versions and flag known-CVE packages).
   - SSRF, XXE, path traversal, open redirects.
   - Logging of secrets / PII; missing audit logging.
   - Docker image hygiene (root user, pinned base, unnecessary packages, exposed ports).
   - Secrets in source (`.ini`, `.json`, `.sh`, `.sql`, `tools/dev_jwt.py`).

3. **Do NOT modify code.** This is a planning task. If you run commands, restrict them to read-only analysis (`pip list`, `pip-audit`, `bandit -r grapinator`, `grep`, etc.). Do not install global packages without asking.

4. **Produce the plan.** Structure it as:
   - **Summary** — 2–4 sentence overview of posture and biggest risks.
   - **Findings table** — columns: `ID | Severity (Critical/High/Medium/Low/Info) | Category | Location (file:line) | Description | Evidence | Recommended fix`. Use the file-link format `[path](path#L10)` for locations.
   - **Suggested remediation phases** — group findings into ordered phases (e.g. Phase 1: Critical auth fixes; Phase 2: Dependency upgrades; Phase 3: Hardening). Each phase lists finding IDs and a rough effort tag (S/M/L).
   - **Open questions / assumptions** — anything that needs user input before remediation can start.
   - **Tooling recommendations** — suggested static analyzers, dependency scanners, or CI integrations to prevent regressions.

5. **File the GitHub issue.** After the plan is written:
   - Save the plan to a temporary file at `/tmp/security-audit-plan.md`.
   - Detect the repo's GitHub remote with `git remote get-url origin`.
   - Create the issue using the GitHub CLI:
     ```sh
     gh issue create \
       --title "Security audit plan — $(date +%Y-%m-%d)" \
       --label "security,audit" \
       --body-file /tmp/security-audit-plan.md
     ```
   - If labels do not yet exist, create them first with `gh label create security --color B60205 --force` and `gh label create audit --color FBCA04 --force`.
   - If `gh` is not installed or not authenticated, stop and report the exact command(s) the user must run instead — do not attempt to use a personal access token or any other credential.
   - Print the resulting issue URL back to the user.

## Output

End your turn with:
1. The issue URL (or the fallback command the user must run).
2. A one-line summary of the highest-severity finding so the user knows whether to act immediately.

## Constraints

- Read-only on the codebase. No edits, no commits, no pushes.
- Do not invent CVEs — if you cite one, it must come from a tool's actual output or a verified source.
- Do not include real secrets in the issue body; redact any discovered credentials as `<REDACTED>` and reference the file/line only.
- Keep evidence snippets short (≤ 5 lines each).
