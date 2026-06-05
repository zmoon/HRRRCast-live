#!/bin/bash
#SBATCH --job-name=fcst
#SBATCH --output=logs/fcst_%j.out
#SBATCH --partition=gpu
##SBATCH --qos=@[FCST_QOS]
#SBATCH --gres=gpu:a100:1
#SBATCH --account=@[FCST_ACCNR]
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=48
#SBATCH --time=@[FCST_WALLTIME]
#SBATCH --deadline=@[DEADLINE]
#SBATCH --mem=192G

# set vars
INIT_TIME="@[INIT_TIME]"
LEAD_HOUR=@[LEAD_HOUR]
PACKAGEROOT=@[PACKAGEROOT]
DATAROOT=@[DATAROOT]
ENVMODE=@[ENVMODE]
N_ENSEMBLES=@[N_ENSEMBLES]
N_GPUS=@[N_GPUS]

export NETCDF2GRIB_SECTION3=@[NETCDF2GRIB_SECTION3]
export WGRIB2=@[WGRIB2]

# conda
if [ "$ENVMODE" == "OPN" ]; then
    source ${PACKAGEROOT}/etc/env_emc.sh
else
    source ${PACKAGEROOT}/etc/env.sh
fi

# job array task -> compute member range for this task
TASK_ID=${SLURM_ARRAY_TASK_ID:-0}

# Compute start-end range for this task using block distribution
chunk=$(( N_ENSEMBLES / N_GPUS ))
rem=$(( N_ENSEMBLES % N_GPUS ))
extra=0
if (( TASK_ID < rem )); then extra=1; fi
if (( TASK_ID < rem )); then
    start=$(( TASK_ID * chunk + TASK_ID ))
else
    start=$(( TASK_ID * chunk + rem ))
fi
end=$(( start + chunk + extra - 1 ))

if (( start > end )); then
    echo "No members assigned to array task ${TASK_ID} (N_ENSEMBLES=${N_ENSEMBLES}, N_GPUS=${N_GPUS}). Exiting."
    exit 0
fi
MEMBER_RANGE="${start}-${end}"

echo "In fcst, INIT_TIME=${INIT_TIME}, LEAD_HOUR=${LEAD_HOUR}, TASK_ID=${TASK_ID}, MEMBER_RANGE=${MEMBER_RANGE}, base_dir=${DATAROOT}"

# Reduce memory usage
export TF_GPU_ALLOCATOR=cuda_malloc_async
# export TF_XLA_FLAGS="--tf_xla_auto_jit=0"

python ${PACKAGEROOT}/src/fcst.py $PACKAGEROOT/net-diffusion/model.keras ${INIT_TIME} ${LEAD_HOUR} \
    --num_members ${N_ENSEMBLES} --members ${MEMBER_RANGE} --base_dir ${DATAROOT} --output_dir ${DATAROOT}
