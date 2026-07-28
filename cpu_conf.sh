cpupower frequency-set --governor performance

for d in /sys/devices/system/cpu/cpu*/cpufreq; do
	echo 3200000 | tee $d/scaling_max_freq
	echo 3200000 | tee $d/scaling_min_freq
done

#echo 0 | tee /sys/devices/system/cpu/cpu3/online
#echo 0 | tee /sys/devices/system/cpu/cpu5/online
#echo 0 | tee /sys/devices/system/cpu/cpu7/online
#echo 0 | tee /sys/devices/system/cpu/cpu9/online
