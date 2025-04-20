#!/bin/bash
#PBS -r n
#PBS -m n
#PBS -N aiida-3783
#PBS -o _scheduler-stdout.txt
#PBS -e _scheduler-stderr.txt
#PBS -q GroupE
#PBS -l walltime=168:00:00
#PBS -l select=1:mpiprocs=12
cd "$PBS_O_WORKDIR"


source /home2/hirotosaito/github_projects/aiida_test/examples/Si_wt/setting.sh

 

'mpirun' '-np' '12' '/home/hirotosaito/codes/qe-7.3_mag/bin/pw.x' '-in' 'aiida.in'  > 'aiida.out'

 
