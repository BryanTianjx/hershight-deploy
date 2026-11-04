# Memory Bank Manifest and Lifecycle

The 03-memory-bank directory is the desired-state source for project Memory Banks. Each child directory contains one manifest.json and an optional seed file. The manifest.schema.json file defines schema version 1.0 and is validated before any server mutation.

## Commands

Install the toolkit from the repository root:

```bash
python -m pip install -e .
hindsight-memory --help
```

Validate manifests without contacting Hindsight:

```bash
hindsight-memory validate --manifest-dir 03-memory-bank
```

Provision banks and seed each content revision once:

```bash
hindsight-memory --api-url http://127.0.0.1:8889 provision
```

Inspect server drift and create a deployment report:

```bash
hindsight-memory --api-url http://127.0.0.1:8889 drift
hindsight-memory --api-url http://127.0.0.1:8889 report --output ./deployment-report.json
```

Poll asynchronous seed operations:

```bash
hindsight-memory --api-url http://127.0.0.1:8889 seed-status
```

Use --state-file to select a durable state file. Back it up with the deployment configuration. Do not delete it between runs.

## Idempotency and failure safety

- Seed revisions are keyed by SHA-256 of normalized seed content, scoped by Bank ID.
- The submitting state is persisted before the retain request. If the request outcome is ambiguous, the revision becomes unknown and is not automatically retried.
- Accepted asynchronous operations are recorded as submitted. seed-status polls operation IDs; only terminal successful operations are marked completed.
- A completed revision is skipped on subsequent runs. A changed seed content hash is a new revision.
- State is local to the provisioner host. Use one designated controller if multiple hosts can provision the same Bank; distributed locking is not implemented in this version.

## Drift boundaries

The current REST adapter can create a Bank and reconcile its mission. Ownership, tags, scope, exclusions and recording policy are manifest metadata, not fields this adapter claims to persist on the server. These fields are listed as unmanaged in drift and report output. Tags are passed to retain when submitting seed content.

## Safety

Provisioning never deletes Banks or memories. It creates missing Banks and reconciles the server-supported mission field. Schema errors abort manifest loading before API writes. Do not put secrets or personal data in manifests or seed files.