source /home/hirotosaito/.bashrc
source /home/hirotosaito/intel/oneapi/2025.0/oneapi-vars.sh --force
conda activate aiida
unset -f conda
export PYTHONPATH="/home2/hirotosaito/github_projects/aiida_test/examples/Si_scf:$PYTHONPATH"