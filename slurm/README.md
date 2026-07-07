# Slurm Jobs

Use `job_template.sbatch` as the starting point for cluster runs. It routes
normal output, errors, and generated run artifacts away from the repository root:

- stdout: `slurm/logs/<job-name>-<job-id>.out`
- stderr and Python tracebacks: `slurm/errors/<job-name>-<job-id>.err`
- run artifacts: `slurm/results/<job-name>/<job-id>/`

Before submitting from a clean checkout, make sure the fixed routing folders
exist:

```bash
mkdir -p slurm/logs slurm/errors slurm/results
sbatch slurm/job_template.sbatch
```

Do not point `--output` or `--error` at the project root. Root-level Slurm logs
make source diffs noisy and mix runtime failures with maintained documents.

For job-specific reports, write into `$RUN_DIR` inside the script:

```bash
python -m pytest --junitxml "$RUN_DIR/pytest.xml"
python run_ko2_daw.py --status > "$RUN_DIR/status.txt"
```

If a job fails, inspect the matching file in `slurm/errors/` first. It should
contain shell errors, Python exceptions, and command trace output when
`set -euo pipefail` aborts the job.
