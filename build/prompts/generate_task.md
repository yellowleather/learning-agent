Generate the current-week implementation task for the Junior SWE.
Use only the provided current-week plan and ledger state. Output JSON only.
Current week plan:
{{WEEK_PLAN}}
Current ledger state:
{{LEDGER_STATE_JSON}}
Include an explicit `verification_command` field. It must be a single command
the build agent can run from the target repository root to verify the work
without inferring from prose.

Required JSON shape: {"week": 1, "title": "...", "objective": "...", "allowed_dirs": ["..."], "required_files": ["..."], "implementation_steps": ["..."], "acceptance_checks": ["..."], "verification_expectations": ["..."], "verification_command": "pytest", "summary": "..."}
