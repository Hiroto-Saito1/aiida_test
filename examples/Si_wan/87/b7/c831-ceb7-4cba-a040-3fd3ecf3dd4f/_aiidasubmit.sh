#!/bin/bash
#PBS -r n
#PBS -m n
#PBS -N aiida-1640
#PBS -o _scheduler-stdout.txt
#PBS -e _scheduler-stderr.txt
#PBS -q GroupA
#PBS -l walltime=168:00:00
#PBS -l select=12:mpiprocs=1
cd "$PBS_O_WORKDIR"


source /home2/hirotosaito/github_projects/aiida_test/examples/Si_wan/setting.sh

 

'mpirun' '-np' '12' '/home/hirotosaito/codes/qe-7.3_mag/PP/src_orig/pw2wannier90.x' < 'aiida.in' > 'aiida.out'

 
