#!/bin/bash
#PBS -r n
#PBS -m n
#PBS -N aiida-6726
#PBS -o _scheduler-stdout.txt
#PBS -e _scheduler-stderr.txt
#PBS -q GroupC
#PBS -l walltime=168:00:00
#PBS -l select=1:mpiprocs=12:ncpus=12
cd "$PBS_O_WORKDIR"


source /home2/hirotosaito/github_projects/aiida_test/examples/Si_symwan/setting.sh

 

"/home/hirotosaito/github_projects/ishiwata_lab/src/symwannier_qe-7.3/symwannier/write_full_data.py" "aiida"  > 'stdout' 2> 'stderr'

> stdout 2> stderr

echo $? > status

 
