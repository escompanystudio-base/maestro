# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a security vulnerability or for data that may contain credentials.

Send a concise report to [destek@escompanystudio.com](mailto:destek@escompanystudio.com) with:

- the affected version or commit;
- a reproducible description of the issue;
- the expected impact;
- any suggested mitigation.

We will acknowledge the report before discussing disclosure or a fix publicly.

## Local data

Maestro can create logs, prompts, run history and workflow state inside its local project directory. These files may contain user-provided content and should not be committed or shared. The repository's `.gitignore` excludes the default runtime paths.
