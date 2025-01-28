#!/bin/bash
#PBS -r n
#PBS -m n
#PBS -N aiida-167
#PBS -V
#PBS -o _scheduler-stdout.txt
#PBS -e _scheduler-stderr.txt
#PBS -q GroupC
#PBS -l select=1:mpiprocs=1
cd "$PBS_O_WORKDIR"


export PATH=/opt/pbs/bin:$PATH

'mpirun' '-np' '1' '/home/hirotosaito/codes/qe-7.3_mag/PW/src/pw.x' '-in' 'aiida.in'  > 'aiida.out'
