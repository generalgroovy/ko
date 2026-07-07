#!/usr/bin/env bash
#SBATCH --job-name=ko2-daw-check
#SBATCH --output=slurm/logs/%x-%j.out
#SBATCH --error=slurm/errors/%x-%j.err
#SBATCH --time=00:15:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=2G

set -euo pipefail

PROJECT_ROOT="${SLURM_SUBMIT_DIR:-$(pwd)}"
cd "$PROJECT_ROOT"

JOB_NAME="${SLURM_JOB_NAME:-ko2-daw-check}"
JOB_ID="${SLURM_JOB_ID:-local}"
RUN_DIR="$PROJECT_ROOT/slurm/results/$JOB_NAME/$JOB_ID"
mkdir -p "$RUN_DIR"

{
  echo "job_name=$JOB_NAME"
  echo "job_id=$JOB_ID"
  echo "project_root=$PROJECT_ROOT"
  echo "run_dir=$RUN_DIR"
  python --version
} > "$RUN_DIR/environment.txt"

python -m pytest --junitxml "$RUN_DIR/pytest.xml"
