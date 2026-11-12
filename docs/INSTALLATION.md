# Installation and use in Antigravity

## Recommended V0.1 setup

Use this repository as a workspace/project checkout. Antigravity discovers the Skill at:

    .agents/skills/datafication-of-reproducibility/SKILL.md

The repository also contains the references, domain profiles, schemas, and runtime expected by the Skill. Keeping the checkout intact avoids broken relative references.

## Install the local Python runtime

From the repository root:

    python -m venv .venv
    # Activate the virtual environment.
    python -m pip install -e ./runtime

Verify:

    dor --help

V0.1 runtime has no third-party Python runtime dependencies.

## Configure a project

Create a local project configuration based on the project schema. Store machine-specific file paths in a local config file that is not committed to Git. Point it to the user's source CSV/JSON and a separate derived-data workspace.

Do not commit private source databases, PDFs, API credentials, access tokens, absolute personal paths, or generated run artifacts.

## Invoke

Use Antigravity's Skill discovery or invoke the Skill explicitly with /datafication-of-reproducibility, then provide the research domain and project configuration. The Skill follows the guided G0-G4 process.

## OpenCode Workers

The Skill defines portable task/result contracts. Connect these to the user's existing Antigravity-to-OpenCode Worker Manager. The repository intentionally does not hard-code an MCP endpoint, worker slot, or manager-specific API.

## Global installation

Workspace installation is the supported V0.1 path. A later installation helper may package the Skill plus its references/runtime for the selected Antigravity IDE/CLI surface. Do not copy only the SKILL.md file: its relative references and runtime are part of the bundle.
