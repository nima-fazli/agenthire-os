# Source distribution

Run from the real Git checkout after reviewing and committing the changes:

    uv run --locked --no-sync python -m scripts.source_bundle
    uv run --locked --no-sync python -m scripts.source_bundle --execute

The first command prints a plan and creates nothing. Export requires a clean
tracked working tree. The default output is a new ZIP beside the repository,
named with the pinned commit. An existing output is never overwritten.
Use --output with an absolute ZIP path outside the repository to choose a name.

The exporter reads the committed tree, not an Explorer directory selection.
It includes every permitted tracked file, including both .github CI files,
and rejects an incomplete tree. Git history, ignored/untracked files, .env,
private PDFs/storage, personal recovery documents, bytecode, links and submodules
are excluded or rejected. .env.example is permitted. A forbidden tracked file
causes rejection rather than silent omission. The path policy is not a scanner
for secrets accidentally written inside otherwise permitted source files.

SOURCE_MANIFEST.json records the commit and SHA-256 of every source file.
It is generated inside the archive; do not add it to the working tree.
The CLI reports the archive SHA-256. Manifest metadata is deterministic.
The maximum source content is 50 MiB. Publication uses an exclusive hard link
in the output directory, so that filesystem must support hard links.

Review the source before distribution. The archive is neither a database/PDF
backup nor a replacement for Git history. Operational backup commands still
belong in a real checkout with the required historical commits. See backups.md.

No runtime environment, private file, Git index, branch or remote is modified.

Common safe diagnostics are uncommitted_source_changes (commit reviewed changes),
incomplete_committed_tree (restore missing source/CI), private_tracked_file
(remove private data from the intended tracked distribution), and
output_exists_or_parent_missing (choose a new output in an existing directory).
Raw Git errors or file contents are never printed by the exporter.
