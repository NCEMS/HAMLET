#!/bin/bash
#SBATCH -J HAMLET_0
#SBATCH --partition=standard
#SBATCH -N 1
#SBATCH -n 10
#SBATCH -t 48:00:00
#SBATCH --account=read_crch_ims86
#SBATCH --mem=128G
#SBATCH --gres=gpu:1
#SBATCH -o assets/slurm/logs/%x-%j.out
#SBATCH -e assets/slurm/logs/%x-%j.err


CONDA_BASE=/storage/group/epo2/default/ims86/miniconda3

# Redirect Nextflow home away from /storage/home (limited quota)
export NXF_HOME=/storage/group/epo2/default/ims86/.nextflow

cd /storage/group/epo2/default/ims86/git_repos/HAMLET

source ${CONDA_BASE}/etc/profile.d/conda.sh
conda activate meti_env

nextflow run main.nf -profile roar --pxd_csv tmp.csv
