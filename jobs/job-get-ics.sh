#!/bin/bash
#SBATCH --job-name=get_ics
#SBATCH --output=logs/get_ics_%j.out
#SBATCH --partition=short
#SBATCH --account=@[ACCNR]
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem-per-cpu=4G
#SBATCH --time=@[GET_ICS_WALLTIME]
#SBATCH --deadline=@[DEADLINE]

module load WebProxy

# set vars
INIT_TIME="@[INIT_TIME]"
PACKAGEROOT="@[PACKAGEROOT]"
DATAROOT="@[DATAROOT]"

# conda
source ${PACKAGEROOT}/etc/env.sh

# job
echo "In get_ics, init_time=${INIT_TIME} "
python3 ${PACKAGEROOT}/src/get_ics.py ${INIT_TIME} --base_dir ${DATAROOT}
