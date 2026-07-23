cpupower frequency-set --governor powersave

for d in /sys/devices/system/cpu/cpu*/cpufreq; do
	echo 4680000 | tee $d/scaling_max_freq
	echo 400000 | tee $d/scaling_min_freq
done

echo 1 | tee /sys/devices/system/cpu/cpu3/online
#echo 1 | tee /sys/devices/system/cpu/cpu5/online
#echo 1 | tee /sys/devices/system/cpu/cpu7/online
#echo 1 | tee /sys/devices/system/cpu/cpu9/online
