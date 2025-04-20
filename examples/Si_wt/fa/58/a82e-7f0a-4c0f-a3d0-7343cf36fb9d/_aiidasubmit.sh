#!/bin/bash
#PBS -r n
#PBS -m n
#PBS -N aiida-3818
#PBS -o _scheduler-stdout.txt
#PBS -e _scheduler-stderr.txt
#PBS -q GroupE
#PBS -l walltime=168:00:00
#PBS -l select=1:mpiprocs=12
cd "$PBS_O_WORKDIR"


source /home2/hirotosaito/github_projects/aiida_test/examples/Si_wt/setting.sh

 

'/home/hirotosaito/codes/wannier_tools-2.7.1/bin/wt.x'  > 'stdout' 2> 'stderr'

echo $? > status

 
