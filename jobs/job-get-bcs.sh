#!/bin/bash
#SBATCH --job-name=get_bcs
#SBATCH --output=logs/get_bcs_%j.out
#SBATCH --partition=short
#SBATCH --account=@[ACCNR]
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem-per-cpu=4G
#SBATCH --time=@[GET_BCS_WALLTIME]
#SBATCH --deadline=@[DEADLINE]

module load WebProxy

# set vars
INIT_TIME="@[INIT_TIME]"
LEAD_HOUR=@[LEAD_HOUR]
PACKAGEROOT=@[PACKAGEROOT]
DATAROOT=@[DATAROOT]
 
# conda
source ${PACKAGEROOT}/etc/env.sh

# job
echo "In get_bcs, init_time=${INIT_TIME}, lead_hour=${LEAD_HOUR}"
python3 ${PACKAGEROOT}/src/get_bcs.py ${INIT_TIME} ${LEAD_HOUR} --base_dir ${DATAROOT}
