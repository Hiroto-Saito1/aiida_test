#!/bin/bash
#PBS -r n
#PBS -m n
#PBS -N aiida-180
#PBS -o _scheduler-stdout.txt
#PBS -e _scheduler-stderr.txt
#PBS -l select=1:mpiprocs=2
#PBS -q lx
#PBS -l elapstim_req=00:10:00
cd "$PBS_O_WORKDIR"


source /uhome/a01774/github_projects/aiida_test/examples/Si_scf_aoba/setting.sh

 which mpirun

'mpirun' '-np' '2' '/uhome/a01774/codes/qe-7.3_mag/bin/pw.x' '-in' 'aiida.in'  > 'aiida.out'

 
