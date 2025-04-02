#!/bin/bash
#PBS -r n
#PBS -m n
#PBS -N aiida-179
#PBS -o _scheduler-stdout.txt
#PBS -e _scheduler-stderr.txt
#PBS -q GroupE
#PBS -l select=12:mpiprocs=1
cd "$PBS_O_WORKDIR"


source /home2/hirotosaito/github_projects/aiida_test/examples/Si_scf/setting.sh

 

'mpirun' '-np' '12' '/home/hirotosaito/codes/qe-7.3_mag/bin/pw.x' '-in' 'aiida.in'  > 'aiida.out'

 
