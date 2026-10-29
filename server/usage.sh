#!/bin/bash
# usage.sh: a snapshot of how busy this server is: CPU load, memory, and for each GPU its use and who holds it.
# It only reads and takes about a second. Run it as any user.
#
#   bash server/usage.sh
#
# Everything is inside one { } block that reads from /dev/null, so no command can wait for keyboard input.
{
export LC_ALL=C
echo "== $(hostname -s) $(date '+%F %T')"
echo "load $(cut -d' ' -f1-3 /proc/loadavg) on $(nproc) cpus"
free -g | grep -E 'total|Mem'

echo "-- gpus: index, bus, use, memory used, memory total, power, power limit"
timeout 30 nvidia-smi --query-gpu=index,pci.bus_id,utilization.gpu,memory.used,memory.total,power.draw,power.limit --format=csv,noheader
grep . /sys/class/drm/card*/device/{gpu_busy_percent,mem_info_vram_used} 2>/dev/null

echo "-- gpu holders: bus, user, pid, memory"
timeout 30 nvidia-smi --query-compute-apps=gpu_bus_id,pid,used_memory --format=csv,noheader |
    while IFS=', ' read -r bus pid mem unit; do echo "$bus $(ps -o user= -p "$pid") $pid $mem $unit"; done
for p in /sys/class/kfd/kfd/proc/*; do
    [ -e "$p" ] && echo "amd $(ps -o user= -p "${p##*/}") ${p##*/}"
done

echo "== END"
} </dev/null 2>&1
